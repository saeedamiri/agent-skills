## Multi-agent package cycles (all repositories)

Repo-agnostic router, coder and verifier rules live in `~/agent-skills/cycle-router`,
`cycle-coder` and `cycle-verifier`. A repository's own role skills extend them and
win where stricter. Worker roles by tier: `coder-strong`, `coder-standard`,
`verifier-strong`, `verifier-standard`, `worker-light`. Where a context-cap hook is
installed it enforces worker caps; routers never poll workers for their size.

Nothing identifying an AI model, assistant, agent or vendor goes into anything
committed to git: no trailers, PR or issue text, branch names or code comments.
