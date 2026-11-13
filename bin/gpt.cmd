@echo off
setlocal
set "SETUP_HOME=%CODEX_HOME%"
if not defined SETUP_HOME set "SETUP_HOME=%USERPROFILE%\.codex"
if not exist "%SETUP_HOME%\gpt.config.toml" (
  python "%~dp0..\install.py" codex >nul
  if errorlevel 1 exit /b 1
)
set "AGENT_ROLE=router"
set "CONTEXT_CAP_MAIN=185"
codex --no-daemon --approve-for-me --profile gpt %*
exit /b %errorlevel%
