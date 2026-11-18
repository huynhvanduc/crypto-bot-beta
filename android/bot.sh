#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR" || exit 1
export PYTHONIOENCODING=utf-8
PID=live/android.pid
mkdir -p live

running() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }

supervise() {
    (while true; do python watch.py >> live/watch.out 2>&1; sleep 10; done) &
    if grep -q '^TELEGRAM_BOT_TOKEN=..*' .env 2>/dev/null; then
        (while true; do python telegram_bot.py >> live/telegram.log 2>&1; sleep 10; done) &
    fi
    wait
}

case "${1:-status}" in
    start)
        if running; then echo "Bot đang chạy (pid $(cat "$PID"))."; exit 0; fi
        termux-wake-lock 2>/dev/null || true
        setsid bash "$DIR/android/bot.sh" _supervise >> live/android.log 2>&1 < /dev/null &
        echo $! > "$PID"
        echo "Đã chạy watcher lệnh khớp + Telegram (pid $!)."
        ;;
    stop)
        if running; then kill -- -"$(cat "$PID")" 2>/dev/null || kill "$(cat "$PID")"; fi
        rm -f "$PID"
        termux-wake-unlock 2>/dev/null || true
        echo "Đã dừng bot."
        ;;
    status)
        if running; then echo "Đang chạy (pid $(cat "$PID"))."; else echo "KHÔNG chạy."; fi
        echo "--- watcher"; tail -n 5 live/watch.log 2>/dev/null
        echo "--- telegram"; tail -n 3 live/telegram.log 2>/dev/null || echo "(không chạy: .env thiếu TELEGRAM_BOT_TOKEN)"
        ;;
    _supervise) supervise ;;
    *) echo "Dùng: bash $DIR/android/bot.sh {start|stop|status}"; exit 1 ;;
esac
