# Cycle Router Reference

Occasional detail for `cycle-router/SKILL.md`: the settings file, marker
formats, batch procedures, generic commands and the heavy-slot script. A
repository's router skill adds its own scripts and paths.

## Local settings file

Untracked, at the path the repository's router skill names (commonly
`.router.local.json` in the repository root). Settings only, never secrets or
personal addresses.

```json
{ "dispatch": "subagents | sessions | manual",
  "workers": ["<session name>"],
  "worktreeRoot": "<directory package worktrees are created under>",
  "push": "ask | standing",
  "notify": "none | <configured channel>",
  "batch": 1,
  "batchMaxAgeHours": 12 }
```

- `dispatch` is the owner's choice of channel; never pick or change it.
- `worktreeRoot` must be a directory the sandbox trusts.
- `push: ask` (default) stops once, at the push. `standing` lets the verifier
  push its accepted branch and the router push batch checkpoints and open a
  flush or wave PR on a green local full suite. It never authorizes a merge
  onto the main branch.
- `batch` is never asked for or written by a router; absent means `1`.
- `batchMaxAgeHours` is read only when `batch` is above `1`.
- Two routers never share a settings file.

## Marker commits

Empty commits (`git commit --allow-empty -m <subject> -m <body>`) on the
package or batch branch; the newest marker of a kind wins.

```text
Router: parked after four verification rounds
<diagnosis: what was tried, options, recommendation, default if unanswered>

Router: unparked
<what the owner decided, and what to do differently>

Router: bundle opened
Router-Bundle-Member: <package> (guess ~<n> lines)

Router: bundle amended
Router-Bundle-Removed: <package>

Router: tier escalated
Router-Tier: strong (round <n>: <reason in one line>)
```

Bundle members' commits carry `Bundle-Member: <package>`; the verifier's commit
carries one `Bundle-Member-Verdict: <package> <verdict>` line per member, and
uses `Handoff: integrate` only when all remaining members are accepted. A
member still not accepted after round two is removed by marker, its commits
reverted by a fresh coder (never a history rewrite), and returned to the queue.

A worker's **transfer note** is an empty commit whose body states facts for its
successor: established, midway, would be rediscovered, next step.

### Batch markers

```text
Router: batch opened
Router-Batch-ID: router/batch-<lane>-<yyyymmdd>-<seq>
Router-Batch-Lane: <lane>
Router-Batch-Baseline: <baseline sha>
Router-Batch-Baseline-Run: <run id that proved the baseline green>
Router-Batch-Limit: <batch>
Router-Batch-Max-Age-Hours: <batchMaxAgeHours>
```

A member checkpoint is a merge:

```bash
git merge --no-ff <accepted branch> -m "Router: batch member integrated" \
  -m "Router-Batch-ID: <batch id>
Router-Batch-Member: <package>
Accepted-SHA: <verifier-accepted sha>"
git push origin <batch branch>
```

Only `Router-Batch-Member:` lines count toward `batch`. Status rows cite the
`Accepted-SHA`, never the checkpoint. Push the batch ref after the marker and
every checkpoint.

## Batch state is derived

```bash
git ls-remote --heads origin 'router/batch-*'                        # open batches
git log --format='%H %cI %B' --grep='^Router: batch opened$' <batch>  # age, baseline
git log --format=%B <batch> | grep -c '^Router-Batch-Member:'         # count vs batch
gh pr list --state open --json number,headRefName                     # frozen by a PR?
```

## Waves

A wave is a batch whose flush PR stays open to measure. Each wave gets its own
branch `router/batch-<lane>-w<N>-<yyyymmdd>-<seq>`, created from the previous
wave's tip; packages run focused tests only; the flush is a standard-tier batch
review plus one local full suite; on green with standing push the PR opens and
the router moves on. A program closes with one PR to the main branch from the
last wave's branch, merged only on the owner's word.

## When the main branch moves under an open batch

1. Stop dispatching into the batch; establish the new baseline by run id.
2. Never rebase the batch.
3. Branch a refresh from the batch tip; a fresh coder merges the new main
   branch, resolves conflicts, regenerates committed recordings, runs the
   shared preflight.
4. Fast-lane if under the threshold with no behaviour change; otherwise a fresh
   verifier.
5. Integrate as `Router: batch refreshed` with `Router-Batch-Refresh:`,
   `Router-Batch-Baseline:` and `Router-Batch-Baseline-Run:`.

## A red batch

1. Record the failing run id; do not diagnose it yourself.
2. A fresh CI-fix coder gets the ordered checkpoint list, the run id and the
   failed log, tests prefixes `M1`, `M2`, ... with the failing job's local entry
   point, and names the first failing prefix.
3. It fixes the cause; a non-fast-lane fix gets a fresh verifier.
4. If it cannot go green, flush only the maximal green, dependency-closed
   prefix, on the owner's word.

## Retiring by object

| what | retire when |
| --- | --- |
| member worktree | clean, merged into the integration ref, branch pushed, nothing only there |
| local member branch | the run that carries it on the main branch is green |
| remote member branch | that run is green, accepted SHA reachable from the remote main branch, deletion authorized |
| batch worktree and branch | that run is green and the merge is reachable from the remote main branch |

## Generic commands

```bash
# reconcile
git worktree list
git log <ref>..<branch> --format=%B | grep -E '^(Router:|Handoff:)'
git -C <worktree> status --short
gh pr list --state open --json number,headRefName
gh run list --branch <main> --limit 10 --json headSha,conclusion

# handoff checks
git log -1 --format=%B <sha> | grep -i '^Handoff:'
git log <ref>..<branch> --format=%B | grep -ci '^Handoff: verify'    # round count
git diff <ref>...<branch> | grep '^+.*REVIEW'                        # use the repo's marker; expect none
git log -S'<review marker>' <ref>..<branch> --format='%h %an %s'     # who removed
git log <ref>..<branch> --format=%B | grep -iE 'co-authored-by|generated with'  # inspect any hit
gh run view <id> --log-failed
```

## Heavy-slot script

`heavy_slot.py` beside this file. Python 3.9+, no dependencies. The ledger is
host-wide (`~/.agent-cycle/heavy-slots/`, or `HEAVY_SLOT_DIR`), so slots are shared across repositories
and sessions on one machine.

```bash
# the brief gives the worker this form; --log keeps output out of its context
python ~/agent-skills/cycle-router/heavy_slot.py run --need-gb 6 --name "<package> full suite" \
    --log .heavy/<package>.log -- <command> <args>

python ~/agent-skills/cycle-router/heavy_slot.py status      # who holds what, free memory
python ~/agent-skills/cycle-router/heavy_slot.py self-test   # proves grant, wait, release, low-memory stop
```

Behaviour: waits until free memory is at least need + 2 GB and no slot was
granted in the last 90 s; runs the command; releases on exit, failure or
interrupt; stops the command and exits 137 ("UNMEASURED") if free memory stays
below 1.5 GB for two checks; exits 75 if no grant within `--max-wait-min`
(default 180). `--reclaim-cmd "<cmd>"` runs once before re-measuring when no
other holder is active (for example a VM page-cache drop). Heavy work is run as
a detached or background command by the worker so its session is not blocked
for hours.
