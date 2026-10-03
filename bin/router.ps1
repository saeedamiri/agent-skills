# Start a router session: 200k compaction window, a save-state note before it, and a
# re-orientation note after it. Arguments pass through, e.g. `router --continue`.
$settings = Join-Path $PSScriptRoot "..\adapters\claude-code\router.settings.local.json"
if (-not (Test-Path $settings)) { python (Join-Path $PSScriptRoot "..\install.py") claude | Out-Null }
claude --settings $settings --autocompact 200k @args
