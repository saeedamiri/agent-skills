"""Install the cycle skills, worker roles, context-cap hook and `router` command.

    python install.py                       # detect the OS and the installed tools, install everything
    python install.py check                 # what is installed where
    python install.py claude | codex        # one tool only
    python install.py router                # only put bin/ on your PATH so `router` works
    python install.py skills-dir <DIR>      # any other tool that reads <DIR>/<name>/SKILL.md

Works on Windows, macOS and Linux (any distribution; what matters is the shell,
and bash, zsh and fish are handled). Python 3.9+, no dependencies; use
`python3 install.py` where `python` is not Python 3.

Skills are linked, not copied (a directory junction on Windows, a symlink
elsewhere), so editing this repository updates every tool at once. Existing
files are never overwritten: settings and hook files are merged, with a backup
beside them, and anything that conflicts is reported and left for you.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
SKILLS = ["cycle-router", "cycle-coder", "cycle-verifier"]
HOOK = (ROOT / "hooks" / "context_cap.py").as_posix()
PYTHON = Path(sys.executable).as_posix()
BIN = ROOT / "bin"
SNIPPET = ROOT / "adapters" / "instructions.snippet.md"
SNIPPET_MARK = "## Multi-agent package cycles"
PATH_MARK = "# agent-skills: router command"
OS = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")


def same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def fill(text: str) -> str:
    return text.replace("{HOOK}", HOOK).replace("{PYTHON}", PYTHON)


def link_dir(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        ok = same(src, dst)
        print(f"  {'ok  ' if ok else 'SKIP'} {dst}" + ("" if ok else "  (exists, not this repo's; left alone)"))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if OS == "windows":  # a junction needs no admin rights or developer mode
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], check=True, capture_output=True)
    else:
        dst.symlink_to(src, target_is_directory=True)
    print(f"  link {dst} -> {src}")


def copy_new(src: Path, dst: Path) -> None:
    if dst.exists():
        ok = dst.read_bytes().replace(b"\r\n", b"\n") == src.read_bytes().replace(b"\r\n", b"\n")
        print(f"  {'ok  ' if ok else 'DIFF'} {dst}" + ("" if ok else "  (differs from the repo; left alone)"))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"  copy {dst}")


def merge_hooks(target: Path, template: Path) -> None:
    """Add the template's hook groups to a JSON settings or hooks file, unless the hook is already there."""
    wanted = json.loads(fill(template.read_text(encoding="utf-8")))
    if target.exists():
        text = target.read_text(encoding="utf-8")
        if HOOK in text:
            print(f"  ok   {target} (hook registered)")
            return
        try:
            data = json.loads(text or "{}")
        except ValueError:
            print(f"  SKIP {target} is not valid JSON; add the hooks from {template} by hand")
            return
        shutil.copyfile(target, target.with_name(target.name + ".bak-agent-skills"))
    else:
        data = {}
    hooks = data.setdefault("hooks", {})
    for event, groups in wanted["hooks"].items():
        hooks.setdefault(event, []).extend(groups)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  merged hook into {target}" + (" (backup beside it)" if target.with_name(target.name + ".bak-agent-skills").exists() else ""))


def add_snippet(target: Path) -> None:
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    if SNIPPET_MARK in text:
        print(f"  ok   {target} (instructions present)")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + ("\n\n" if text.strip() else "") + SNIPPET.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  added cycle instructions to {target}")


def claude() -> None:
    base = HOME / ".claude"
    print("Claude Code")
    for name in SKILLS:
        link_dir(ROOT / name, base / "skills" / name)
    agents = ROOT / "adapters" / "claude-code" / "agents"
    if not (base / "agents").exists():
        link_dir(agents, base / "agents")
    elif same(agents, base / "agents"):
        print(f"  ok   {base / 'agents'}")
    else:
        for f in sorted(agents.glob("*.md")):
            copy_new(f, base / "agents" / f.name)
    merge_hooks(base / "settings.json", ROOT / "adapters" / "claude-code" / "settings.snippet.json")
    add_snippet(base / "CLAUDE.md")
    router = ROOT / "adapters" / "claude-code" / "router.settings.local.json"
    router.write_text(fill((ROOT / "adapters" / "claude-code" / "router.settings.json").read_text(encoding="utf-8")),
                      encoding="utf-8")
    print(f"  wrote {router}")
    settings = base / "settings.json"
    text = settings.read_text(encoding="utf-8") if settings.exists() else ""
    if '"attribution"' not in text or "CLAUDE_CODE_SUBAGENT_MODEL" not in text:
        print('  optional, in settings.json: "attribution": {"commit": "", "pr": ""} (no tool trailers) and\n'
              '  "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"} (untyped helpers on the standard tier)')


def codex() -> None:
    base = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
    print("Codex")
    for name in SKILLS:
        link_dir(ROOT / name, HOME / ".agents" / "skills" / name)
    for f in sorted((ROOT / "adapters" / "codex" / "agents").glob("*.toml")):
        copy_new(f, base / "agents" / f.name)
    merge_hooks(base / "hooks.json", ROOT / "adapters" / "codex" / "hooks.json")
    add_snippet(base / "AGENTS.md")
    print("  TODO once: in Codex run /hooks and trust the context-cap hook (again after editing it)")


def router_path() -> None:
    print(f"router command ({OS})")
    if OS == "windows":
        import winreg
        import ctypes
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                current, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, kind = "", winreg.REG_EXPAND_SZ
            parts = [p for p in current.split(";") if p]
            if any(os.path.normcase(p.rstrip("\\/")) == os.path.normcase(str(BIN)) for p in parts):
                print(f"  ok   {BIN} is on your user PATH")
                return
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(parts + [str(BIN)]))
        # tell running programs the environment changed
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, ctypes.byref(ctypes.c_ulong()))
        print(f"  added {BIN} to your user PATH; open a new terminal, then type `router`")
        return
    script = BIN / "router"
    script.chmod(script.stat().st_mode | 0o111)
    shell = Path(os.environ.get("SHELL", "")).name
    rc_files = {
        "zsh": [HOME / ".zshrc"],
        "bash": [HOME / (".bash_profile" if OS == "macos" else ".bashrc")],
        "fish": [HOME / ".config" / "fish" / "config.fish"],
    }
    targets = rc_files.get(shell, [HOME / ".profile"])
    targets += [p for files in rc_files.values() for p in files if p.exists() and p not in targets]
    for rc in targets:
        text = rc.read_text(encoding="utf-8") if rc.exists() else ""
        if PATH_MARK in text:
            print(f"  ok   {rc}")
            continue
        line = f'fish_add_path "{BIN}"' if rc.name == "config.fish" else f'export PATH="{BIN}:$PATH"'
        rc.parent.mkdir(parents=True, exist_ok=True)
        rc.write_text(text + ("\n" if text and not text.endswith("\n") else "") + f"{PATH_MARK}\n{line}\n", encoding="utf-8")
        print(f"  added {BIN} to PATH in {rc}")
    print("  open a new terminal, then type `router`")


def skills_dir(target: str) -> None:
    print(f"Skills into {target}")
    for name in SKILLS:
        link_dir(ROOT / name, Path(target).expanduser() / name)


def detected() -> list[str]:
    found = []
    if shutil.which("claude") or (HOME / ".claude").exists():
        found.append("claude")
    if shutil.which("codex") or Path(os.environ.get("CODEX_HOME", HOME / ".codex")).exists():
        found.append("codex")
    return found


def install_all() -> None:
    tools = detected()
    print(f"OS: {OS}; Python: {PYTHON}; tools found: {', '.join(tools) or 'none'}\n")
    if not tools:
        print("Neither Claude Code nor Codex found. For another tool: python install.py skills-dir <its skills folder>")
        return
    if "claude" in tools:
        claude()
        router_path()
    if "codex" in tools:
        codex()


def check() -> None:
    print(f"OS: {OS}; tools found: {', '.join(detected()) or 'none'}")
    rows = [(HOME / ".claude" / "skills" / n, ROOT / n) for n in SKILLS]
    rows += [(HOME / ".agents" / "skills" / n, ROOT / n) for n in SKILLS]
    for dst, src in rows:
        print(f"  {'linked ' if same(src, dst) else ('other  ' if dst.exists() else 'missing')} {dst}")
    for f in (HOME / ".claude" / "settings.json", Path(os.environ.get("CODEX_HOME", HOME / ".codex")) / "hooks.json"):
        print(f"  {'hook   ' if f.exists() and HOOK in f.read_text(encoding='utf-8') else 'no hook'} {f}")
    on_path = any(same(Path(p), BIN) for p in os.environ.get("PATH", "").split(os.pathsep) if p)
    print(f"  {'on PATH' if on_path else 'not on PATH (yet; new terminals pick it up)'} {BIN}")


if __name__ == "__main__":
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9 or newer is needed; try python3")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "skills-dir" and len(sys.argv) > 2:
        skills_dir(sys.argv[2])
    elif cmd in ("all", "claude", "codex", "check", "router"):
        {"all": install_all, "claude": claude, "codex": codex, "check": check, "router": router_path}[cmd]()
    else:
        print(__doc__)
        sys.exit(2)
