@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
:loop
.venv\Scripts\python.exe telegram_bot.py >> live\telegram.log 2>&1
timeout /t 10 /nobreak >nul
goto loop
