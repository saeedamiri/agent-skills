"""Install the cycle skills, worker roles, context-cap hook and router commands.

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
hook settings are merged with a backup. The router profile receives only a
missing child context setting, with a backup; explicit preferences are kept.
"""
from __future__ import annotations

import json
import math
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # Fresh installs still support Python 3.9 and 3.10.
    tomllib = None

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
    return (text.replace("{HOOK}", HOOK).replace("{PYTHON}", PYTHON)
            .replace("{ROUTER_SKILL}", (ROOT / "cycle-router" / "SKILL.md").as_posix())
            .replace("{ROUTER_REFERENCE}", (ROOT / "cycle-router" / "reference.md").as_posix()))


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


def profile_edit_points(text: str):
    """Yield root table headers and inline tables, outside strings/comments."""
    position = 0
    depth = 0
    root = True
    while position < len(text):
        char = text[position]
        if char == "#":
            end = text.find("\n", position)
            position = len(text) if end < 0 else end + 1
            continue
        if char in "\"'":
            multiline = text.startswith(char * 3, position)
            position += 3 if multiline else 1
            while position < len(text):
                if char == '"' and text[position] == "\\":
                    position += 2
                elif text.startswith(char * (3 if multiline else 1), position):
                    position += 3 if multiline else 1
                    if multiline:
                        # Four/five closing quotes include one/two value quotes.
                        while position < len(text) and text[position] == char:
                            position += 1
                    break
                else:
                    position += 1
            continue
        if char == "[" and depth == 0:
            start = text.rfind("\n", 0, position) + 1
            if not text[start:position].strip():
                end = text.find("\n", position)
                end = len(text) if end < 0 else end + 1
                yield "header", start, end
                root = False
                position = end
                continue
        if char == "{" and depth == 0 and root:
            start = text.rfind("\n", 0, position) + 1
            yield "inline", start, position + 1
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        position += 1


def same_toml(left, right) -> bool:
    """Compare parsed values including TOML's non-reflexive NaN floats."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_toml(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_toml(a, b) for a, b in zip(left, right))
    return left == right or (isinstance(left, float) and math.isnan(left) and math.isnan(right))


def refresh_router_profile(target: Path) -> None:
    """Enable child-owned context defaults in an existing router profile."""
    if tomllib is None:
        print(f"  SKIP {target} (existing profile upgrade requires Python 3.11+; left alone)")
        return
    original = target.read_bytes()
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError:
        print(f"  SKIP {target} (not UTF-8; left alone)")
        return
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        print(f"  SKIP {target} (invalid TOML; left alone)")
        return
    features = data.get("features", {})
    if not isinstance(features, dict):
        print(f"  SKIP {target} (features is not a table; left alone)")
        return
    key = "subagent_default_context_limits"
    if key in features:
        if features[key] is True:
            print(f"  ok   {target} (child context defaults enabled)")
        else:
            print(f"  DIFF {target} (child context defaults explicitly set; left alone)")
        return

    newline = "\r\n" if "\r\n" in text else "\n"
    setting = f"{key} = true"
    edits = []
    for kind, start, end in profile_edit_points(text):
        fragment = text[start:end] + ("}" if kind == "inline" else "")
        try:
            table = tomllib.loads(fragment)
        except tomllib.TOMLDecodeError:
            continue
        if table == {"features": {}}:
            if kind == "header":
                separator = "" if text[:end].endswith("\n") else newline
                edits.append((end, separator + setting + newline))
            else:
                edits.append((end, " " + setting + ("," if features else "")))
    separator = "" if not text or text.endswith("\n") else newline
    edits.extend(((len(text), separator + f"[features]{newline}{setting}{newline}"),
                  (0, f"features.{setting}{newline}")))
    expected = dict(data, features=dict(features, **{key: True}))
    for position, addition in edits:
        updated = text[:position] + addition + text[position:]
        try:
            result = tomllib.loads(updated)
        except tomllib.TOMLDecodeError:
            continue
        if same_toml(result, expected):
            break
    else:
        print(f"  SKIP {target} (cannot safely add child context defaults; left alone)")
        return
    backup = target.with_name(target.name + ".bak-agent-skills")
    number = 1
    while backup.exists():
        backup = target.with_name(target.name + f".bak-agent-skills-{number}")
        number += 1
    backup.write_bytes(original)
    target.write_bytes(updated.encode("utf-8"))
    print(f"  updated {target} (backup: {backup})")


def merge_hooks(target: Path, template: Path) -> None:
    """Add the template's hook groups to a JSON settings or hooks file, unless the hook is already there."""
    wanted = json.loads(fill(template.read_text(encoding="utf-8")))
    if target.exists():
        text = target.read_text(encoding="utf-8")
        try:
            data = json.loads(text or "{}")
        except ValueError:
            print(f"  SKIP {target} is not valid JSON; add the hooks from {template} by hand")
            return
    else:
        data = {}
    hooks = data.setdefault("hooks", {})
    changed = False
    for event, groups in wanted["hooks"].items():
        existing = hooks.setdefault(event, [])
        for group in groups:
            # Preserve already trusted commands, including a different Python path.
            matcher = group.get("matcher", "").strip("^$")
            registered = any(
                old.get("matcher", "").strip("^$") == matcher
                and any(HOOK in h.get("command", "") for h in old.get("hooks", []))
                for old in existing
            )
            if not registered:
                existing.append(group)
                changed = True
    if not changed:
        print(f"  ok   {target} (hooks registered)")
        return
    if target.exists():
        shutil.copyfile(target, target.with_name(target.name + ".bak-agent-skills"))
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
    profile = base / "gpt.config.toml"
    if profile.exists():
        refresh_router_profile(profile)
    else:
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(fill((ROOT / "adapters" / "codex" / profile.name).read_text(encoding="utf-8")), encoding="utf-8")
        print(f"  wrote {profile}")
    router_path()
    print("  TODO once: start gpt, run /hooks and trust the context-cap hooks (again after editing them)")


def router_path() -> None:
    print(f"router commands ({OS})")
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
        print(f"  added {BIN} to your user PATH; open a new terminal, then type `router` or `gpt`")
        return
    for name in ("router", "gpt"):
        script = BIN / name
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
    print("  open a new terminal, then type `router` or `gpt`")


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
    base = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
    profile = base / "gpt.config.toml"
    print(f"  {'profile' if profile.exists() else 'missing'} {profile}")
    for src in sorted((ROOT / "adapters" / "codex" / "agents").glob("*.toml")):
        target = base / "agents" / src.name
        print(f"  {'role   ' if target.exists() else 'missing'} {target}")
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
