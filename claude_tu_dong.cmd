@echo off
rem Claude tu nghien cuu va giao dich tren testnet. Task Scheduler "CryptoBotClaude" goi moi 30 phut.
rem Nhat ky: live\claude_auto.log (quyet dinh cua Claude), live\claude_watch.log (ban theo TP/SL/30 phut).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Tien trinh tu ban theo TP/SL; neu da co mot ban dang chay thi ban moi tu thoat.
start "claude-watch" /min cmd /c ".venv\Scripts\python.exe -u claude_trade.py watch forever >> live\claude_watch.log 2>&1"
echo ===== %date% %time% >> live\claude_auto.log
type claude_tu_dong.md | "%APPDATA%\npm\claude.cmd" -p --permission-mode dontAsk --allowedTools "Bash(.venv/Scripts/python.exe claude_trade.py:*)" "WebSearch" >> live\claude_auto.log 2>&1
