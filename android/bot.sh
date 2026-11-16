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
    while true; do
        today=$(date -u +%F)
        if [ "$(date -u +%H%M)" -ge 0005 ] && [ "$(cat live/last_daily 2>/dev/null)" != "$today" ]; then
            echo "$(date -u +%FT%TZ) chạy bot D1" >> live/run.log
            if python live_trade.py --push >> live/run.log 2>&1; then
                echo "$today" > live/last_daily
            else
                sleep 540
            fi
        fi
        sleep 60
    done
}

case "${1:-status}" in
    start)
        if running; then echo "Bot đang chạy (pid $(cat "$PID"))."; exit 0; fi
        termux-wake-lock 2>/dev/null || true
        setsid bash "$DIR/android/bot.sh" _supervise >> live/android.log 2>&1 < /dev/null &
        echo $! > "$PID"
        echo "Đã chạy bot (pid $!). Bot D1: 07:05 giờ VN mỗi ngày (chạy bù nếu điện thoại tắt lúc đó)."
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
        echo "--- bot D1 (lần chạy gần nhất: $(cat live/last_daily 2>/dev/null || echo chưa))"; tail -n 5 live/run.log 2>/dev/null
        ;;
    ban-het) python live_trade.py --close-all --push ;;
    tam-dung) python live_trade.py --pause --push ;;
    tiep-tuc) python live_trade.py --resume --push ;;
    _supervise) supervise ;;
    *) echo "Dùng: bash $DIR/android/bot.sh {start|stop|status|ban-het|tam-dung|tiep-tuc}"; exit 1 ;;
esac
