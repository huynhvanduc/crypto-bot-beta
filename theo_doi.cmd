@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
:loop
.venv\Scripts\python.exe watch.py
timeout /t 10 /nobreak >nul
goto loop
