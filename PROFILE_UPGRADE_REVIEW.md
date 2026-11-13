# Profile upgrade verification, round 1

Verdict: needs changes. Reviewed implementation e64d252 against bbdc64d.

P1, install.py, refresh_router_profile: the upgrade must preserve valid TOML
and explicit preferences. A section header at EOF becomes an invalid statement.
Quoted, dotted and inline feature tables gain duplicate declarations. Quoted
or dotted false preferences are changed. A header inside a multiline string
causes the string itself to change, without enabling the actual setting.
Invalid input is also modified without validation. These failures prevent a
safe upgrade of customized profiles. Parse and validate before editing; keep
unrelated bytes and explicit preferences intact, and leave unsupported inputs
untouched with a clear report. Keep the documented runtime compatibility.

Evidence and commands (Python 3.12; the new parser checks require 3.11+):

- `python -m unittest -q test_install`: 5 tests pass.
- `python -m unittest -q test_profile_upgrade`: 5 tests run; 6 failed subcases,
  4 parser errors. Backup collision, exact backup bytes and repeat-upgrade checks
  pass. Failure output remains in `.review-tmp/round1-tests.log` in the worktree.
- Installed CLI version command reports 0.169.0. Its matching tagged runtime
  source clears both inherited context fields in the copied child configuration
  when the feature is enabled. The role override whitelist does not include
  either field. This supports native child defaults, not exact per-role
  automatic compaction thresholds. The feature is under development and off
  by default. Source inspection is not an executed runtime integration test.
- The supplied router template retains its 202000 limit. The unchanged hook
  caps agree with the documentation. Existing tests confirm ordinary explicit
  false preservation and exact trust bytes for the canonical section spelling.

No installation, push, merge, active-session inspection or runtime requests were
performed. Review scope is the upgrade, its template and documented behavior.
The source-level behavior is supported; acceptance awaits the upgrade repair.
