# Launch an isolated router session; all remaining arguments go to the CLI.
$ErrorActionPreference = 'Stop'
$base = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
if (-not (Test-Path -LiteralPath (Join-Path $base 'gpt.config.toml'))) {
    python (Join-Path $PSScriptRoot '..\install.py') codex | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Router setup failed.' }
}
$cli = Join-Path $env:LOCALAPPDATA 'Programs\OpenAI\Codex\bin\codex.exe'
if (-not (Test-Path -LiteralPath $cli)) {
    $cli = (Get-Command codex.exe -ErrorAction Stop).Source
}
$previousRole = [Environment]::GetEnvironmentVariable('AGENT_ROLE', 'Process')
$previousCap = [Environment]::GetEnvironmentVariable('CONTEXT_CAP_MAIN', 'Process')
try {
    $env:AGENT_ROLE = 'router'
    $env:CONTEXT_CAP_MAIN = '185'
    & $cli --no-daemon --approve-for-me --profile gpt @args
    $result = $LASTEXITCODE
}
finally {
    [Environment]::SetEnvironmentVariable('AGENT_ROLE', $previousRole, 'Process')
    [Environment]::SetEnvironmentVariable('CONTEXT_CAP_MAIN', $previousCap, 'Process')
}
exit $result
