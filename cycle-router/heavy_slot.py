"""Host-wide heavy-slot lock: run a memory-heavy command only when the host has room.

Replaces the HEAVY SLOT REQUEST / GRANTED / RELEASED message exchange with a
router. A worker wraps its heavy step:

    python ~/agent-skills/cycle-router/heavy_slot.py run --need-gb 6 --name "lane-x full suite" \
        --log .heavy/suite.log -- python scripts/run_local_ci.py --full

The script waits until free memory covers the stated need plus a margin and no
other slot was granted in the last settle window (so the previous holder's
allocation shows up in the measurement), records the holder in a host-wide
ledger, runs the command, and releases the slot when the command ends -- also on
failure or Ctrl-C. Holders whose process has died are dropped from the ledger.

While the command runs, free memory is re-measured; if it stays under the floor
for two consecutive checks the command is stopped and the exit code is 137 with
a line saying the run is unmeasured (a low-memory kill is not a result).

Output: with --log, the command's output goes to that file and only the last
--tail lines are printed, which keeps the caller's context small.

Subcommands: run, status, self-test.
Exit codes: the command's own exit code; 75 if --max-wait-min passed without a
grant; 137 low-memory stop; 2 usage or harness error.

Optional --reclaim-cmd runs before a re-measure when the need is not met (for
example dropping a VM page cache); it is never run while another slot holder is
active.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

LEDGER_DIR = Path(os.environ.get("HEAVY_SLOT_DIR", Path.home() / ".agent-cycle" / "heavy-slots"))
LEDGER = LEDGER_DIR / "ledger.json"
LOCK = LEDGER_DIR / "ledger.lock"


def free_gb() -> float:
    fake = os.environ.get("HEAVY_SLOT_FAKE_FREE_GB")
    if fake is not None:
        return float(Path(fake).read_text().strip()) if Path(fake).exists() else float(fake)
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / 2**30
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2**20
    try:
        import psutil  # type: ignore
        return psutil.virtual_memory().available / 2**30
    except ImportError as exc:
        raise SystemExit(f"heavy-slot: cannot measure free memory on {sys.platform}") from exc


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # Never os.kill(pid, 0) on Windows: it terminates the process.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def ledger_lock(timeout: float = 30.0):
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - LOCK.stat().st_mtime > 60:  # stale lock from a crashed writer
                    LOCK.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise SystemExit("heavy-slot: ledger lock busy")
            time.sleep(0.2)
    try:
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def read_ledger() -> list[dict]:
    try:
        holders = json.loads(LEDGER.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        holders = []
    return [h for h in holders if pid_alive(int(h["pid"]))]


def write_ledger(holders: list[dict]) -> None:
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(holders, indent=1))
    os.replace(tmp, LEDGER)


def try_grant(name: str, need: float, margin: float, settle: float) -> tuple[bool, str]:
    with ledger_lock():
        holders = read_ledger()
        now = time.time()
        recent = [h for h in holders if now - h["granted"] < settle]
        free = free_gb()
        if recent:
            write_ledger(holders)
            return False, f"waiting: slot granted {int(now - recent[-1]['granted'])}s ago to {recent[-1]['name']!r}"
        if free < need + margin:
            write_ledger(holders)
            return False, f"waiting: {free:.1f} GB free, need {need:.1f} + {margin:.1f} GB; holders: {[h['name'] for h in holders]}"
        holders.append({"pid": os.getpid(), "name": name, "need_gb": need, "granted": now})
        write_ledger(holders)
        return True, f"granted: {free:.1f} GB free, need {need:.1f} GB"


def release() -> None:
    with ledger_lock():
        write_ledger([h for h in read_ledger() if int(h["pid"]) != os.getpid()])


def tail(path: Path, n: int) -> str:
    try:
        return "".join(path.read_text(errors="replace").splitlines(keepends=True)[-n:])
    except FileNotFoundError:
        return ""


def cmd_run(args: argparse.Namespace) -> int:
    if not args.command:
        print("heavy-slot: no command given after --", file=sys.stderr)
        return 2
    start = time.time()
    last = ""
    reclaimed = False
    while True:
        ok, msg = try_grant(args.name, args.need_gb, args.margin_gb, args.settle_s)
        if ok:
            print(f"heavy-slot: {msg}", flush=True)
            break
        if args.reclaim_cmd and not reclaimed and "GB free" in msg and "holders: []" in msg:
            subprocess.run(args.reclaim_cmd, shell=True, capture_output=True)
            reclaimed = True
            continue
        if msg.split(":")[0] + msg.split(";")[-1] != last:  # print only when the situation changes
            print(f"heavy-slot: {msg}", flush=True)
            last = msg.split(":")[0] + msg.split(";")[-1]
        if time.time() - start > args.max_wait_min * 60:
            print("heavy-slot: no grant within --max-wait-min; nothing ran", flush=True)
            return 75
        time.sleep(args.poll_s)

    low_memory = threading.Event()
    log_handle = None
    try:
        if args.log:
            Path(args.log).parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(args.log, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(args.command, stdout=log_handle, stderr=subprocess.STDOUT if log_handle else None)

        def watch() -> None:
            strikes = 0
            while proc.poll() is None:
                time.sleep(args.poll_s)
                strikes = strikes + 1 if free_gb() < args.floor_gb else 0
                if strikes >= 2:
                    low_memory.set()
                    proc.kill()
                    return

        threading.Thread(target=watch, daemon=True).start()
        code = proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        code = 130
    finally:
        if log_handle:
            log_handle.close()
        release()
        print("heavy-slot: released", flush=True)

    if args.log:
        print(f"heavy-slot: last {args.tail} lines of {args.log}:")
        print(tail(Path(args.log), args.tail), end="")
    if low_memory.is_set():
        print(f"heavy-slot: stopped below {args.floor_gb} GB free -- the run is UNMEASURED, not red or green")
        return 137
    print(f"heavy-slot: command exit {code}")
    return code


def cmd_status(_: argparse.Namespace) -> int:
    with ledger_lock():
        holders = read_ledger()
        write_ledger(holders)
    print(json.dumps({"free_gb": round(free_gb(), 1), "holders": holders}, indent=1))
    return 0


def cmd_self_test(_: argparse.Namespace) -> int:
    py = sys.executable
    me = str(Path(__file__).resolve())
    with tempfile.TemporaryDirectory() as tmp:
        free_file = Path(tmp) / "free"
        env = {**os.environ, "HEAVY_SLOT_DIR": tmp, "HEAVY_SLOT_FAKE_FREE_GB": str(free_file)}
        base = [py, me, "run", "--poll-s", "0.2", "--settle-s", "4", "--margin-gb", "1"]
        failures = []

        free_file.write_text("10")
        r = subprocess.run(base + ["--need-gb", "4", "--name", "a", "--", py, "-c", "import sys; sys.exit(3)"],
                           env=env, capture_output=True, text=True)
        if r.returncode != 3 or "granted" not in r.stdout:
            failures.append(f"grant + exit code passthrough: {r.returncode} {r.stdout!r}")
        if json.loads((Path(tmp) / "ledger.json").read_text()) != []:
            failures.append("slot not released after the command ended")

        free_file.write_text("2")
        r = subprocess.run(base + ["--need-gb", "4", "--name", "b", "--max-wait-min", "0.02", "--", py, "-c", "print(1)"],
                           env=env, capture_output=True, text=True)
        if r.returncode != 75 or "nothing ran" not in r.stdout:
            failures.append(f"insufficient memory must wait then give up: {r.returncode} {r.stdout!r}")

        free_file.write_text("10")
        holder = subprocess.Popen(base + ["--need-gb", "4", "--name", "c", "--", py, "-c", "import time; time.sleep(3)"],
                                  env=env, stdout=subprocess.PIPE, text=True)
        time.sleep(1.0)
        t0 = time.time()
        r = subprocess.run(base + ["--need-gb", "4", "--name", "d", "--", py, "-c", "print(1)"],
                           env=env, capture_output=True, text=True)
        holder.wait()
        if r.returncode != 0 or "waiting: slot granted" not in r.stdout or time.time() - t0 < 0.1:
            failures.append(f"second request inside the settle window must wait: {r.stdout!r}")

        free_file.write_text("10")
        log = Path(tmp) / "out.log"
        killer = subprocess.Popen(base + ["--need-gb", "1", "--floor-gb", "1.5", "--name", "e", "--log", str(log),
                                          "--", py, "-c", "import time; print('started', flush=True); time.sleep(20)"],
                                  env=env, stdout=subprocess.PIPE, text=True)
        time.sleep(1.0)
        free_file.write_text("0.5")
        out, _ = killer.communicate(timeout=30)
        if killer.returncode != 137 or "UNMEASURED" not in out or "started" not in out:
            failures.append(f"low-memory stop: {killer.returncode} {out!r}")

        for f in failures:
            print("FAIL", f)
        print("heavy-slot self-test:", "OK" if not failures else f"{len(failures)} failure(s)")
        return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--need-gb", type=float, required=True)
    run.add_argument("--name", required=True)
    run.add_argument("--margin-gb", type=float, default=2.0)
    run.add_argument("--floor-gb", type=float, default=1.5)
    run.add_argument("--settle-s", type=float, default=90.0)
    run.add_argument("--poll-s", type=float, default=30.0)
    run.add_argument("--max-wait-min", type=float, default=180.0)
    run.add_argument("--reclaim-cmd")
    run.add_argument("--log")
    run.add_argument("--tail", type=int, default=40)
    run.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.cmd == "run":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        return cmd_run(args)
    if args.cmd == "status":
        return cmd_status(args)
    return cmd_self_test(args)


if __name__ == "__main__":
    sys.exit(main())
