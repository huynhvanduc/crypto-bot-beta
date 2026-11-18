@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PATH=%~dp0.venv\Scripts;%PATH%
echo ===== %date% %time% >> live\claude_auto.log
type claude_tu_dong.md | "%APPDATA%\npm\claude.cmd" -p --permission-mode dontAsk --allowedTools "Bash(python claude_trade.py:*)" "WebSearch" >> live\claude_auto.log 2>&1
