import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from websocket import WebSocketTimeoutException, create_connection

from bot.config import Config
from bot.exchange import BinanceSpot, sign
from bot.filelock import file_lock
from bot.gitops import git
from bot.gitops import push as git_push
from bot.live import UNSUPPORTED, now_iso
from bot.watcher import FillWatcher, ntfy_publisher

sys.stdout.reconfigure(encoding="utf-8")

PUSH_EVERY = 60.0
BOT_RUN_EVERY = 60.0
LOG = Path("live/watch.log")


def log(msg: str) -> None:
    line = f"{now_iso()} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ws_url(ex: BinanceSpot) -> str:
    return ("wss://ws-api.testnet.binance.vision/ws-api/v3" if ex.is_testnet
            else "wss://ws-api.binance.com:443/ws-api/v3")


def subscribe(ws, ex: BinanceSpot) -> None:
    p = {"apiKey": ex.key, "recvWindow": 10000, "timestamp": int(time.time() * 1000) + ex._offset}
    p["signature"] = sign(ex.secret, "&".join(f"{k}={p[k]}" for k in sorted(p)))
    ws.send(json.dumps({"id": "sub", "method": "userDataStream.subscribe.signature", "params": p}))
    r = json.loads(ws.recv())
    if r.get("status") != 200:
        raise RuntimeError(f"Đăng ký nhận lệnh khớp bị từ chối: {r.get('error', r)}")


def push_fills() -> bool:
    try:
        with file_lock(wait=300):
            git("add", "docs/fills.json")
            if git("diff", "--cached", "--quiet", "--", "docs/fills.json").returncode == 0:
                return True
            c = git("commit", "-m", f"Lệnh khớp {now_iso()}", "--", "docs/fills.json")
            if c.returncode != 0:
                log(f"Commit lỗi: {(c.stderr or c.stdout).strip()}")
                return False
            r = git_push()
            log("Đã đẩy docs/fills.json lên GitHub." if r.returncode == 0 else f"Đẩy GitHub lỗi: {r.stderr.strip()}")
            return r.returncode == 0
    except Exception as e:
        log(f"Đẩy GitHub lỗi: {type(e).__name__}: {e}")
        return False


def run_bot() -> None:
    log("Stop của bot D1 vừa khớp → chạy live_trade.py --push để chốt sổ")
    r = subprocess.run([sys.executable, "live_trade.py", "--push"], capture_output=True, text=True,
                       encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    log(f"live_trade.py kết thúc (mã {r.returncode})")


class Background:

    def __init__(self):
        self.thread: threading.Thread | None = None

    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, fn) -> None:
        self.thread = threading.Thread(target=fn, daemon=True)
        self.thread.start()


def main() -> None:
    no_push = "--no-push" in sys.argv
    ex = BinanceSpot()
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not ex.has_keys or not topic:
        sys.exit("Cần BINANCE_API_KEY, BINANCE_API_SECRET và NTFY_TOPIC trong .env")
    symbols = [s for s in Config().symbols if s not in UNSUPPORTED]
    w = FillWatcher(ex, ntfy_publisher(topic, log), symbols, topic=topic)
    w.load()
    w.dirty = True
    pusher, bot = Background(), Background()
    last_push = last_bot = 0.0
    delay = 5
    log(f"Bắt đầu theo dõi ({'testnet' if ex.is_testnet else 'LIVE'}), {len(symbols)} coin"
        + (", KHÔNG đẩy GitHub" if no_push else ""))

    def push_job() -> None:
        if not push_fills():
            w.dirty = True

    while True:
        ws = None
        try:
            ex.sync_time()
            n = w.backfill()
            log(f"Lấy bù {n} lệnh khớp; số dư USDT {w.usdt:,.2f}")
            ws = create_connection(ws_url(ex), timeout=10)
            subscribe(ws, ex)
            ws.settimeout(0.5)
            log("Đang nghe lệnh khớp qua WebSocket")
            delay = 5
            while True:
                try:
                    out = w.handle(json.loads(ws.recv()))
                except WebSocketTimeoutException:
                    out = []
                for f in out + w.tick():
                    log(f"KHỚP {f['side']} {f['qty']:g} {f['symbol']} @ {f['price']:g} ({f['source']}) → đã phát ntfy")
                now = time.time()
                if w.dirty and not pusher.busy() and now - last_push >= PUSH_EVERY:
                    w.export()
                    last_push = now
                    if not no_push:
                        pusher.start(push_job)
                if w.bot_stop_filled and not bot.busy() and now - last_bot >= BOT_RUN_EVERY:
                    w.bot_stop_filled = False
                    last_bot = now
                    bot.start(run_bot)
        except KeyboardInterrupt:
            log("Dừng theo dõi")
            break
        except Exception as e:
            log(f"Mất kết nối ({type(e).__name__}: {e}); nối lại sau {delay} giây")
            time.sleep(delay)
            delay = min(delay * 2, 60)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
