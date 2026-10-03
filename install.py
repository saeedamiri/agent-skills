"""Install the cycle skills, worker roles and context-cap hook for one or more harnesses.

    python install.py check                 # what is installed where
    python install.py claude                # ~/.claude: skills, agent types, hook (settings printed, not edited)
    python install.py codex                 # ~/.agents/skills, ~/.codex/agents, ~/.codex/hooks.json
    python install.py skills-dir <DIR>      # any other tool that reads <DIR>/<name>/SKILL.md

Skills are linked, not copied (a directory junction on Windows, a symlink
elsewhere), so editing this repository updates every harness. Nothing that
already exists is overwritten; a conflict is reported and left for you.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
SKILLS = ["cycle-router", "cycle-coder", "cycle-verifier"]
HOOK = (ROOT / "hooks" / "context_cap.py").as_posix()


def same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def link_dir(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        print(f"  {'ok  ' if same(src, dst) else 'SKIP'} {dst}" + ("" if same(src, dst) else "  (exists, not this repo's; left alone)"))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], check=True, capture_output=True)
    else:
        dst.symlink_to(src, target_is_directory=True)
    print(f"  link {dst} -> {src}")


def copy_new(src: Path, dst: Path) -> None:
    if dst.exists():
        state = "ok  " if dst.read_bytes() == src.read_bytes() else "DIFF"
        print(f"  {state} {dst}" + ("  (differs from the repo; left alone)" if state == "DIFF" else ""))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"  copy {dst}")


def write_template(src: Path, dst: Path) -> None:
    text = src.read_text(encoding="utf-8").replace("{HOOK}", HOOK)
    if dst.exists():
        print(f"  {'ok  ' if HOOK in dst.read_text(encoding='utf-8') else 'MERGE'} {dst}"
              + ("" if HOOK in dst.read_text(encoding="utf-8") else f"  (exists; merge the hooks from {src} by hand)"))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    print(f"  wrote {dst}")


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
    settings = base / "settings.json"
    if settings.exists() and HOOK in settings.read_text(encoding="utf-8"):
        print(f"  ok   {settings} (hook registered)")
    else:
        print(f"  TODO merge into {settings}:")
        print((ROOT / "adapters" / "claude-code" / "settings.snippet.json").read_text(encoding="utf-8").replace("{HOOK}", HOOK))
    print("  TODO once: add adapters/instructions.snippet.md to ~/.claude/CLAUDE.md if it is not there")


def codex() -> None:
    base = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
    print("Codex")
    for name in SKILLS:
        link_dir(ROOT / name, HOME / ".agents" / "skills" / name)
    for f in sorted((ROOT / "adapters" / "codex" / "agents").glob("*.toml")):
        copy_new(f, base / "agents" / f.name)
    write_template(ROOT / "adapters" / "codex" / "hooks.json", base / "hooks.json")
    print("  TODO once: in Codex run /hooks and trust the context-cap hook (re-trust after editing it)")
    print(f"  TODO once: add adapters/instructions.snippet.md to {base / 'AGENTS.md'} if it is not there")


def skills_dir(target: str) -> None:
    print(f"Skills into {target}")
    for name in SKILLS:
        link_dir(ROOT / name, Path(target).expanduser() / name)


def check() -> None:
    rows = [(HOME / ".claude" / "skills" / n, ROOT / n) for n in SKILLS]
    rows += [(HOME / ".agents" / "skills" / n, ROOT / n) for n in SKILLS]
    rows += [(HOME / "agent-skills" / n, ROOT / n) for n in SKILLS]
    for dst, src in rows:
        print(f"  {'linked ' if same(src, dst) else ('other  ' if dst.exists() else 'missing')} {dst}")
    for f in ("~/.claude/settings.json", "~/.codex/hooks.json"):
        p = Path(f).expanduser()
        print(f"  {'hook   ' if p.exists() and HOOK in p.read_text(encoding='utf-8') else 'no hook'} {p}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "skills-dir" and len(sys.argv) > 2:
        skills_dir(sys.argv[2])
    elif cmd in ("claude", "codex", "check"):
        {"claude": claude, "codex": codex, "check": check}[cmd]()
    else:
        print(__doc__)
        sys.exit(2)
