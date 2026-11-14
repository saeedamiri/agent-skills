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
| `install.py` | Links the skills and installs the adapters, with scoped backed-up profile upgrades. |
| `bin/router`, `router.cmd`, `router.ps1` | The `router` command: a router session with its own compaction point and notes. |
| `bin/gpt`, `gpt.cmd`, `gpt.ps1` | The `gpt` command: a Codex router with automatic approval review, router instructions and context hooks. |

Skills use the open `SKILL.md` format (`name` and `description` frontmatter,
Markdown body), so any tool that reads skills can use them as they are.

## Worker tiers

| Role | Tier | Claude Code | Codex |
| --- | --- | --- | --- |
| `coder-strong`, `verifier-strong` | strong | opus, high | gpt-6-astra, high |
| `coder-standard`, `verifier-standard` | standard | sonnet, high | gpt-6-sol, high |
| `worker-light` | light | haiku | gpt-6-luna, high |
| `trial-sonnet` | trial | sonnet, high | - |
| `research-fable`, `research-opus`, `research-sonnet` | research | fable / opus / sonnet, high | - |
| `research-astra`, `research-sol` | research | - | gpt-6-astra / gpt-6.1-sol, high |
| `advanced-research-fable`, `advanced-research-opus`, `advanced-research-sonnet` | advanced research | fable / opus / sonnet, max | - |
| `advanced-research-astra`, `advanced-research-sol` | advanced research | - | gpt-6-astra / gpt-6.1-sol, high |

The router picks the tier per dispatch, standard first, and escalates to strong
when a round fails for lack of depth. Full-lane verification is always strong.
Change a model here, not in the skills.

Trial and research agents are outside the package cycle: `trial-sonnet` takes a benchmark
task as a test taker; the research agents work an open research question. Both have a 400k
context cap (450k hard limit) and keep a notes file for a successor. The advanced research
agents use max effort in Claude Code and high in Codex, with a 500k cap (550k hard
limit), for questions a research run did not crack; they cost far more per run.
These are policy caps, not extra model capacity. The selected model's actual
context window and automatic compaction may be smaller.

## Install

Windows, macOS or Linux (any distribution), Python 3.9 or newer:

```bash
git clone https://github.com/saeedamiri/agent-skills ~/agent-skills
python ~/agent-skills/install.py        # python3 where python is not Python 3
```

The installer detects the OS and which of Claude Code and Codex are installed,
then for each one links the skills, installs the worker roles, merges the
context-cap hook into its settings (with a backup beside the file), adds the
cycle instructions to its global instructions file, and puts `bin/` on your
PATH so `router` and `gpt` work in a new terminal (Windows: user PATH; macOS and Linux:
your bash, zsh or fish profile). Running it again changes nothing.

```bash
python install.py check             # what is installed where
python install.py claude | codex    # one tool only
python install.py skills-dir <DIR>  # any other tool that reads <DIR>/<name>/SKILL.md
```

Skills are linked (a directory junction on Windows, a symlink elsewhere), so an
edit here reaches every tool at once. Codex runs a hook only after you trust
it: start `gpt` and run `/hooks` once to review and trust the context-cap hooks,
and again after changing their definitions. Trust is saved; `gpt` does not
bypass hook trust. The installer preserves existing profiles and trust settings.

## Codex router: `gpt`

Type `gpt` instead of `codex` in PowerShell, Command Prompt, or a POSIX shell:

```powershell
gpt
gpt "Route the next dispatchable package in this repository."
gpt resume
gpt resume <session-id>
```

The command loads `~/.codex/gpt.config.toml` (or `$CODEX_HOME/gpt.config.toml`),
which assigns the router role and tells it to read the cycle-router skill and
the repository's router instructions before dispatching. It starts with
**Workspace (Approve for me)** permissions: sandbox escalation requests go to
automatic review. This does not grant push, merge or deployment authority.

Only this launch sets `AGENT_ROLE=router` and `CONTEXT_CAP_MAIN=185`, enables
hooks, and requests automatic compaction at 202k tokens. The hook reminds the
router to save its one-page state at 185k, then to re-read it and reconcile from
git after compaction, before the next model request. The command uses
`--no-daemon` so the session and its hooks inherit the router environment.
Normal `codex` sessions keep their existing settings; the Claude Code `router`
command is unchanged. Arguments pass through, including resume options.

The installer registers the tool hooks and the `SessionStart` compaction hook,
including when upgrading an installation that already has the tool hooks.
It also installs the coder, verifier, light worker, regular research and senior
research roles. The senior roles are `advanced-research-astra` and
`advanced-research-sol`. New router profiles enable child context defaults, so
workers no longer inherit the router's 202k compaction setting. Each worker
uses the selected model's native compaction point. The context-cap hook still
enforces these separate policy limits:

| Worker role | Warning | Hard stop |
| --- | ---: | ---: |
| `coder-*` | 250k | 300k |
| `verifier-*` | 200k | 240k |
| `worker-*` | 100k | 120k |
| `research-*` | 400k | 450k |
| `advanced-research-*` | 500k | 550k |
| Other spawned roles | 200k | 240k |

These are policy backstops, not automatic compaction thresholds. The CLI version
used here does not apply a compaction setting from an individual role file, so
roles sharing a model also share its native compaction point. That point may be
below a policy warning and never increases the model's context window. A role
without an explicit configuration also uses its selected model's default.

Use a CLI version supporting `--approve-for-me`, `--no-daemon`, profile
files, the documented hook events and `subagent_default_context_limits`
(verified with 0.169.0). To install just
this adapter and put the commands on your PATH, run `python install.py codex`.
The installer adds the child context default setting to an existing router
profile if the setting is absent. It saves the exact prior bytes beside the
profile and leaves other settings and hook trust intact. An explicit `false`
is left alone and reported. The change applies to newly started router and
worker sessions; running sessions retain the configuration they started with.
Upgrading an existing profile requires Python 3.11+ for TOML validation;
Python 3.9 and 3.10 leave it untouched and report that requirement. Invalid
TOML or a non-table `features` value is also reported and left untouched.
Quoted keys, dotted keys and inline feature tables are supported. Each edit
must parse and change only the missing setting before any file is written.

## Router sessions compact on their own (Claude Code)

Type `router` instead of `claude` when you start or resume a router; arguments
pass through (`router --resume <id>`, `router --continue`). Everything else
stays `claude`. For a router session only:

- it compacts at about 202k (a 235k window minus 33k) instead of near the
  model's full window;
- at 185k the hook tells the router to bring its state file up to date and
  commit it;
- right after any compaction the hook tells it to re-read the state file and
  reconcile from git before trusting the summary.

Other sessions, such as research, keep the default window and get no notes.
Subagents of a router session share its window, so they compact at the same
point; their caps remain the backstop elsewhere. A router resumed with plain
`claude` loses all three; for one already running, `/autocompact 235k` restores
the early compaction, without the notes.

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

## Licence

MIT, copyright (c) 2026 Saeed Amiri; see [LICENSE](LICENSE). Use, change and share it freely; keep the copyright notice in copies.
