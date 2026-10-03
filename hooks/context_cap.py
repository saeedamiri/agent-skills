"""Context cap hook: warn an agent at its cap, and hard-stop its work past a hard limit.

Works for two harnesses with the same hook protocol: Claude Code (subagent
transcripts, agent_id/agent_type in the hook input) and Codex CLI (rollout files
whose first line says whether the thread is a spawned subagent and its role, and
whose token_count events carry the context size).

PostToolUse (soft): tell the agent once, then every further 40k, that it is over
its cap and must commit a transfer note at the next safe point.

PreToolUse (hard): past HARD_FACTOR x cap, refuse every tool call except git
inspection and commits (status, diff, log, show, add, commit, worktree list), so
the agent cannot keep working but can still save what it has. Applies to
subagents only; the main session (the person's own console or a router) is
never blocked.

Replaces routers polling workers for their size. After each tool call this reads
the tail of the calling agent's own transcript, takes the context size of its
latest model turn (input + cache read + cache write tokens), and if that is over
the cap for its agent type, injects one short note into that agent's context.
It reminds again only after a further step of growth. It never blocks a tool
and never fails the call: any error is swallowed.

Caps by agent type (prefix match), overridable with CONTEXT_CAP_<PREFIX> env
vars in thousands of tokens, e.g. CONTEXT_CAP_CODER=250:
  coder*     250k  builder: commit + transfer note, stop
  verifier*  200k  verifier: commit what you have as Handoff: verify, stop
  worker-*   100k  light helper: report and stop (a bare "worker" is a general role)
  (other subagent) 200k
  main session     180k  router-style: commit one-page state, restart at a phase boundary
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

CAPS = {"coder": 250, "verifier": 200, "worker": 100}
OTHER_SUBAGENT = 200
MAIN = 180
REMIND_STEP = 40  # thousand tokens between reminders
HARD_FACTOR = 1.2
ALLOWED_GIT = ("status", "diff", "log", "show", "add", "commit", "worktree list", "rev-parse", "branch --show-current")
HARD_MESSAGE = ("Hard context limit: your context is {k}k tokens, past the hard limit of {hard}k ({cap}k cap). Further "
                "work is refused. Only git status/diff/log/show/add/commit are allowed. Commit what you have now (WIP is "
                "fine, say so) and a transfer note as an empty commit: what is established, what you were midway "
                "through, what a successor would rediscover, the next step. Then end your turn with a short report.")

MESSAGES = {
    "coder": ("Context check: your context is {k}k tokens, over the {cap}k builder cap. At the next safe point "
              "(tests green or a coherent step done) commit your work and a transfer note (an empty commit with facts "
              "only: established, midway, would be rediscovered, next step), then stop and report. If you are a few "
              "turns from finishing the whole task, finish first."),
    "verifier": ("Context check: your context is {k}k tokens, over the {cap}k verifier cap. Finish the check you are "
                 "on, commit what you have as `Handoff: verify` stating what is still unresolved, then stop and report."),
    "worker": "Context check: your context is {k}k tokens, over the {cap}k cap for a light helper. Report what you have and stop.",
    "other": ("Context check: your context is {k}k tokens, over the {cap}k cap. Wrap up: return your conclusions "
              "now, briefly, rather than continuing to read."),
    "main": ("Context check: this session's context is {k}k tokens (cap {cap}k). If you are coordinating a cycle, "
             "commit your one-page state at the next phase boundary and let a fresh session continue from git. "
             "Otherwise consider /compact at a natural break."),
}


def latest_context_tokens(path: Path) -> int | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - 400_000))
            lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"token_count"' in line:  # Codex: input_tokens already includes cached input
            try:
                usage = json.loads(line)["payload"]["info"]["last_token_usage"]
                return int(usage.get("input_tokens") or 0)
            except (ValueError, KeyError, TypeError):
                continue
        if '"usage"' not in line:
            continue
        try:
            usage = json.loads(line)["message"]["usage"]
        except (ValueError, KeyError, TypeError):
            continue
        return sum(int(usage.get(k) or 0) for k in
                   ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return None


def identify(data: dict, path: Path) -> tuple[str | None, str | None] | None:
    """Return (agent_id, agent_type) for the caller; (None, None) is a main session; None means skip."""
    if data.get("agent_id") or data.get("agent_type"):
        return data.get("agent_id"), data.get("agent_type")
    try:
        with path.open("rb") as fh:
            first = json.loads(fh.readline().decode("utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None, None
    if first.get("type") != "session_meta":
        return None, None
    source = (first.get("payload") or {}).get("source")
    if not isinstance(source, dict) or "subagent" not in source:
        return None, None
    spawn = (source.get("subagent") or {}).get("thread_spawn") if isinstance(source.get("subagent"), dict) else None
    if not isinstance(spawn, dict):
        return None  # the harness's own helper threads (approval reviewers and similar): leave alone
    role = spawn.get("agent_role") or str(spawn.get("agent_path") or "").rstrip("/").rsplit("/", 1)[-1]
    return str(first["payload"].get("id") or "subagent"), role.replace("_", "-")


def classify(agent_type: str | None, agent_id: str | None) -> tuple[str, int]:
    if not agent_id and not agent_type:
        kind, cap = "main", MAIN
    else:
        name = (agent_type or "").lower()
        kind, cap = "other", OTHER_SUBAGENT
        for prefix, default in CAPS.items():
            if name.startswith(prefix + "-") or name == prefix != "worker":  # Codex's built-in "worker" is general-purpose
                kind, cap = prefix, default
                break
    env = os.environ.get(f"CONTEXT_CAP_{kind.upper()}")
    if env and env.isdigit():
        cap = int(env)
    return kind, cap


def transcript_for(data: dict) -> Path | None:
    agent_id = data.get("agent_id")
    main = data.get("transcript_path")
    if not main:
        return None
    main_path = Path(main)
    if agent_id:
        candidate = main_path.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
        if candidate.exists():
            return candidate
        if main_path.name == f"agent-{agent_id}.jsonl":
            return main_path
        return None  # never measure the parent's transcript on a subagent's behalf
    return main_path


def git_only(command: str) -> bool:
    import re
    segments = [seg.strip() for seg in re.split(r"&&|\|\||;|\||\n", command) if seg.strip()]
    if not segments:
        return False
    for seg in segments:
        seg = re.sub(r"^(cd\s+\S+|git\s+-C\s+\S+)\s*", lambda m: "git " if m.group(0).startswith("git") else "", seg).strip()
        if not seg:
            continue  # a bare `cd <dir>` segment
        if not seg.startswith("git "):
            return False
        rest = seg[4:].strip()
        if not any(rest.startswith(a) for a in ALLOWED_GIT):
            return False
    return True


def command_text(tool_input: dict) -> str:
    command = tool_input.get("command", "")
    if isinstance(command, list):  # argv form, e.g. ["bash", "-lc", "git status"]
        command = command[-1] if command else ""
    return command if isinstance(command, str) else ""


def pre_tool(data: dict) -> int:
    path = transcript_for(data)
    who = identify(data, path) if path else None
    if not who or not who[0]:
        return 0  # never block the main session
    kind, cap = classify(who[1], who[0])
    tokens = latest_context_tokens(path)
    if tokens is None:
        return 0
    k, hard = tokens // 1000, int(cap * HARD_FACTOR)
    if k < hard:
        return 0
    if git_only(command_text(data.get("tool_input") or {})):
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": HARD_MESSAGE.format(k=k, hard=hard, cap=cap)}}))
    return 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if data.get("hook_event_name") == "PreToolUse":
            return pre_tool(data)
        path = transcript_for(data)
        if path is None:
            return 0
        who = identify(data, path)
        if who is None:
            return 0
        kind, cap = classify(who[1], who[0])
        tokens = latest_context_tokens(path)
        if tokens is None:
            return 0
        k = tokens // 1000
        if k < cap:
            return 0
        key = f"{data.get('session_id', 'x')}-{who[0] or 'main'}"
        state = Path(tempfile.gettempdir()) / "claude-context-cap" / f"{key}.txt"
        state.parent.mkdir(parents=True, exist_ok=True)
        try:
            last = int(state.read_text())
        except (OSError, ValueError):
            last = 0
        if last and k < last + REMIND_STEP:
            return 0
        state.write_text(str(k))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": MESSAGES[kind].format(k=k, cap=cap)}}))
    except Exception:  # a hook must never break the tool call
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
