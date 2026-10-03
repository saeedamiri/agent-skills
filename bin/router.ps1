# Start a router session: it compacts at about 202k, with a save-state note before and a
# re-orientation note after it. Arguments pass through, e.g. `router --continue`.
$settings = Join-Path $PSScriptRoot "..\adapters\claude-code\router.settings.local.json"
if (-not (Test-Path $settings)) { python (Join-Path $PSScriptRoot "..\install.py") claude | Out-Null }
claude --settings $settings --autocompact 235k @args
