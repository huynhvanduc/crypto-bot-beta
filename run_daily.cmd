@echo off
cd /d D:\LearnCode\bot
if not exist live mkdir live
.venv\Scripts\python.exe live_trade.py --push >> live\run.log 2>&1
