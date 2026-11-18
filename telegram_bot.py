import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from bot.exchange import BinanceSpot
from bot.filelock import file_lock
from bot.gitops import git
from bot.gitops import push as git_push
from bot.journal import export_docs, market_excursion, parse_buy, snapshot, summary
from bot.common import now_iso
from bot.manual import ManualTrader, recovery
from bot.telegram import Telegram, button

sys.stdout.reconfigure(encoding="utf-8")

USDT = 500
SYMBOL = "BTCUSDT"
TICK_EVERY = 60
REMIND_MIN = (15, 30)
HELP = ("Lệnh tay (testnet, lưu nhật ký để phân tích):\n"
        "/mua <coin> [USDT] [lý do] — vd: /mua SOL 200 phá đỉnh 1h, volume lớn (mặc định 100 USDT)\n"
        "/ban <coin> — bán (không ghi coin: hiện nút Bán)\n"
        "/lenh — lệnh đang mở, lãi/lỗ hiện tại\n"
        "/ketqua — tổng kết các lệnh đã đóng (tính phí thật 0,2 % khứ hồi)\n"
        "/thitruong — tình hình BTC\n"
        f"Mỗi lệnh có stop 2×ATR 1h đặt sẵn trên sàn; bot nhắc khi giữ {REMIND_MIN[0]} và {REMIND_MIN[1]} phút.")


class Controller:
    def __init__(self, tg, trader: ManualTrader, path=Path("live/telegram.json"), check=recovery):
        self.tg, self.trader, self.path, self.check = tg, trader, Path(path), check
        self.now = time.time
        self.publish = lambda: None
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.state.setdefault("recovered", False)
        self.state.setdefault("offset", 0)

    @property
    def owner(self):
        return self.state.get("owner")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state), encoding="utf-8")

    def sell_buttons(self):
        return [[button(f"Bán {s}", f"sell:{s}")] for s in self.trader.pos] or None

    def handle(self, update: dict) -> None:
        if "message" in update:
            m = update["message"]
            chat, text = m["chat"]["id"], m.get("text", "")
            if self.owner is None and text.startswith("/start"):
                self.state["owner"] = chat
                self.save()
            if chat != self.owner:
                return
            cmd = text.split(maxsplit=1)[0].lower() if text else ""
            try:
                if cmd == "/thitruong":
                    ok, info = self.check()
                    self.tg.send(chat, ("KHỞI SẮC: " if ok else "Chưa khởi sắc: ") + info)
                elif cmd in ("/trangthai", "/lenh"):
                    self.tg.send(chat, self.trader.status(), self.sell_buttons())
                elif cmd == "/mua":
                    self.manual_buy(chat, text)
                elif cmd == "/ban":
                    self.manual_sell(chat, text)
                elif cmd == "/ketqua":
                    self.tg.send(chat, summary(self.trader.journal))
                else:
                    self.tg.send(chat, HELP)
            except Exception as e:
                self.tg.send(chat, f"LỖI: {type(e).__name__}: {e}")
            return
        cb = update.get("callback_query")
        if not cb:
            return
        chat, mid = cb["message"]["chat"]["id"], cb["message"]["message_id"]
        if chat != self.owner:
            self.tg.answer(cb["id"], "Không có quyền")
            return
        action, _, symbol = cb["data"].partition(":")
        self.tg.answer(cb["id"], "Đang xử lý…")
        try:
            if action == "buy":
                result = self.trader.buy(symbol, USDT)
            elif action == "sell":
                result = self.trader.sell(symbol)
            else:
                result = "Đã bỏ qua."
        except Exception as e:
            result = f"LỖI: {type(e).__name__}: {e}"
        self.tg.edit(chat, mid, f"{cb['message'].get('text', '')}\n\n{now_iso()} {result}")
        if action in ("buy", "sell"):
            self.publish()

    def manual_buy(self, chat, text: str) -> None:
        parsed = parse_buy(text)
        if isinstance(parsed, str):
            self.tg.send(chat, parsed)
            return
        symbol, usdt, reason = parsed
        result = self.trader.buy(symbol, usdt, reason)
        if not reason and symbol in self.trader.pos:
            result += "\nGợi ý: ghi lý do vào lệnh (vd /mua SOL 200 phá đỉnh 1h) để sau này phân tích."
        self.tg.send(chat, result, self.sell_buttons())
        self.publish()

    def manual_sell(self, chat, text: str) -> None:
        parts = text.split()
        if len(parts) < 2:
            if len(self.trader.pos) == 1:
                self.tg.send(chat, self.trader.sell(next(iter(self.trader.pos))))
                self.publish()
            else:
                self.tg.send(chat, self.trader.status(), self.sell_buttons())
            return
        sym = parts[1].upper()
        self.tg.send(chat, self.trader.sell(sym if sym.endswith("USDT") else sym + "USDT"))
        self.publish()

    def reminders(self) -> None:
        now = self.now()
        changed = False
        for sym, p in list(self.trader.pos.items()):
            held = (now - p.get("ts", now)) / 60
            due = [m for m in REMIND_MIN if held >= m and m not in p.setdefault("reminded", [])]
            if not due:
                continue
            p["reminded"].extend(due)
            changed = True
            self.tg.send(self.owner, f"{sym} đã giữ {due[-1]} phút{self.trader.open_pnl(sym)}.",
                         [[button(f"Bán {sym}", f"sell:{sym}")]])
        if changed:
            self.trader.save()

    def tick(self) -> None:
        if self.owner is None:
            return
        stops = self.trader.check_stops()
        for text in stops:
            self.tg.send(self.owner, text)
        if stops:
            self.publish()
        self.reminders()
        ok, info = self.check()
        if ok and not self.state["recovered"]:
            self.tg.send(self.owner, f"KHỞI SẮC\n{info}\n\nĐề xuất: MUA {USDT} USDT {SYMBOL}, stop 2×ATR 1h đặt sẵn "
                                     "trên sàn. Lưu ý: tín hiệu này chưa được backtest.",
                         [[button(f"Mua {USDT} USDT {SYMBOL}", f"buy:{SYMBOL}"), button("Bỏ qua", "skip")]])
        if ok != self.state["recovered"]:
            self.state["recovered"] = ok
            self.save()


class DocsPublisher:
    """Ghi docs/manual.json rồi đẩy GitHub ở luồng nền (không làm chậm Telegram)."""

    def __init__(self, trader: ManualTrader):
        self.trader, self._lock, self._pending = trader, threading.Lock(), False

    def __call__(self) -> None:
        try:
            export_docs(self.trader)
        except Exception:
            traceback.print_exc()
            return
        with self._lock:
            if self._pending:
                return
            self._pending = True
        threading.Thread(target=self._push, daemon=True).start()

    def _push(self) -> None:
        try:
            with file_lock():
                with self._lock:
                    self._pending = False
                git("add", "docs/manual.json")
                if git("diff", "--cached", "--quiet", "--", "docs/manual.json").returncode == 0:
                    return
                git("commit", "-m", f"Lệnh tay {now_iso()}", "--", "docs/manual.json")
                r = git_push()
                print(f"{now_iso()} " + ("Đã đẩy docs/manual.json lên GitHub." if r.returncode == 0
                                         else f"Đẩy GitHub lỗi: {r.stderr.strip()}"), flush=True)
        except Exception:
            traceback.print_exc()


def main() -> None:
    ex = BinanceSpot()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or not ex.has_keys:
        sys.exit("Cần TELEGRAM_BOT_TOKEN, BINANCE_API_KEY, BINANCE_API_SECRET trong .env")
    ex.sync_time()
    c = Controller(Telegram(token), ManualTrader(ex, context_fn=snapshot, excursion_fn=market_excursion))
    c.publish = DocsPublisher(c.trader)
    c.publish()
    print(f"{now_iso()} Bot Telegram chạy" + ("" if c.owner else " — nhắn /start cho bot để nhận quyền điều khiển"),
          flush=True)
    last_tick = 0.0
    while True:
        try:
            for u in c.tg.updates(c.state["offset"]):
                c.state["offset"] = u["update_id"] + 1
                c.save()
                c.handle(u)
            if time.time() - last_tick >= TICK_EVERY:
                last_tick = time.time()
                c.tick()
        except Exception:
            traceback.print_exc()
            time.sleep(10)


if __name__ == "__main__":
    main()
