@echo off
rem Start a router session (see README). Arguments pass through: router --resume <id>
set "SETTINGS=%~dp0..\adapters\claude-code\router.settings.local.json"
if not exist "%SETTINGS%" python "%~dp0..\install.py" claude >nul
claude --settings "%SETTINGS%" --autocompact 235k %*
