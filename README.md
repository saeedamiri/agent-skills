# agent-skills

Repo-agnostic rules for running coding agents as a **router -> coder ->
independent verifier** cycle, plus the small tools that make the rules cheap to
follow. A repository adds its own facts in its own role skills, which extend
these.

| Path | What it is |
| --- | --- |
| `cycle-router/` | Router role: reconcile, pick work, choose the worker tier, brief, wait by event, handoff checks, batching, CI, escalation. `reference.md` holds the marker formats and commands. |
| `cycle-router/heavy_slot.py` | Host-wide memory lock for heavy commands (full suites, Docker builds). Python 3.9+, no dependencies, any harness. `self-test` proves it. |
| `cycle-coder/` | Builder role: scope, regression test per fix, small context, transfer note, handoff by commit. |
| `cycle-verifier/` | Verifier role: failing test before a finding, fake-fix list, what blocks, handoff by commit. |
| `hooks/context_cap.py` | Context-cap hook: a note at a worker's cap, and at 1.2 x the cap every tool is refused except git inspection and commits. Main sessions are never blocked. |
| `adapters/claude-code/` | Worker roles as agent types (model + effort per tier) and the settings to register the hook. |
| `adapters/codex/` | Worker roles as agent TOML files and `hooks.json`. |
| `adapters/instructions.snippet.md` | The lines to add to a harness's global instructions file. |
| `install.py` | Links the skills into each harness and installs the adapters without overwriting anything. |
| `bin/router`, `bin/router.ps1` | Start a router session with its own compaction window and notes. |

Skills use the open `SKILL.md` format (`name` and `description` frontmatter,
Markdown body), so any tool that reads skills can use them as they are.

## Worker tiers

| Role | Tier | Claude Code | Codex |
| --- | --- | --- | --- |
| `coder-strong`, `verifier-strong` | strong | opus, high | gpt-6-astra, high |
| `coder-standard`, `verifier-standard` | standard | sonnet, high | gpt-6.1-sol, high |
| `worker-light` | light | haiku | gpt-6-luna, low |

The router picks the tier per dispatch, standard first, and escalates to strong
when a round fails for lack of depth. Full-lane verification is always strong.
Change a model here, not in the skills.

## Install

```bash
python install.py check
python install.py claude            # ~/.claude/skills, ~/.claude/agents; prints the settings to merge
python install.py codex             # ~/.agents/skills, ~/.codex/agents, ~/.codex/hooks.json
python install.py skills-dir <DIR>  # any other tool that reads <DIR>/<name>/SKILL.md
```

Skills are linked (a directory junction on Windows, a symlink elsewhere), so an
edit here reaches every harness at once. Then add
`adapters/instructions.snippet.md` to the harness's global instructions file
(`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, or your tool's equivalent).

Codex runs a hook only after you trust it: run `/hooks` in Codex once, and
again after editing the hook.

## Router sessions compact on their own (Claude Code)

Start a router with `bin/router` (PowerShell: `bin/router.ps1`) instead of
`claude`; arguments pass through (`router --continue`). For that session only:

- the compaction window is 200k, so it compacts at roughly 165k instead of near
  the model's full window;
- at 145k the hook tells the router to bring its state file up to date and
  commit it;
- right after any compaction the hook tells it to re-read the state file and
  reconcile from git before trusting the summary.

Other sessions, such as research, keep the default window and get no notes.
Subagents of a router session share its window, so they compact at the same
point; their caps remain the backstop elsewhere. For a router already running,
type `/autocompact 200k` in it; it then compacts early, without the two notes.

## What each harness gets

| | Claude Code | Codex | Any other tool |
| --- | --- | --- | --- |
| Role skills | yes | yes | yes, if it reads `SKILL.md`; otherwise paste the role's `SKILL.md` into its instructions |
| Model per worker tier | agent types | agent roles | a fresh process per worker with the tier's model flag |
| Context cap, soft note | hook | hook | the checkpoint rule in the coder and verifier skills |
| Context cap, hard stop | hook | hook | none; bound the work by package size and one round per fresh worker |
| Heavy-command lock | `heavy_slot.py` | `heavy_slot.py` | `heavy_slot.py` |

How the hook finds its numbers: in Claude Code it reads the calling subagent's
own transcript; in Codex it reads the thread's session file, whose first line
says whether the thread is a spawned subagent and its role, and whose
`token_count` events give the context size. If it cannot tell, it does nothing.

Without a hook, a worker cannot see its own context size, so the coder and
verifier skills give it a proxy: commit after every coherent step, and treat
about 40 tool calls in a round as the cap.
