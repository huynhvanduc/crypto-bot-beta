import json
import os
import sys
import time
import traceback
from pathlib import Path

from bot.exchange import BinanceSpot
from bot.live import now_iso
from bot.manual import ManualTrader, recovery
from bot.telegram import Telegram, button

sys.stdout.reconfigure(encoding="utf-8")

USDT = 500
SYMBOL = "BTCUSDT"
TICK_EVERY = 300
HELP = ("Lệnh: /trangthai — lệnh đang mở + nút Bán, /thitruong — tình hình BTC.\n"
        f"Khi thị trường khởi sắc bot gửi đề xuất kèm nút Mua {USDT} USDT {SYMBOL} (stop 2×ATR 1h đặt sẵn trên sàn).")


class Controller:
    def __init__(self, tg, trader: ManualTrader, path=Path("live/telegram.json"), check=recovery):
        self.tg, self.trader, self.path, self.check = tg, trader, Path(path), check
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
            if text.startswith("/thitruong"):
                ok, info = self.check()
                self.tg.send(chat, ("KHỞI SẮC: " if ok else "Chưa khởi sắc: ") + info)
            elif text.startswith("/trangthai"):
                self.tg.send(chat, self.trader.status(), self.sell_buttons())
            else:
                self.tg.send(chat, HELP)
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

    def tick(self) -> None:
        if self.owner is None:
            return
        for text in self.trader.check_stops():
            self.tg.send(self.owner, text)
        ok, info = self.check()
        if ok and not self.state["recovered"]:
            self.tg.send(self.owner, f"KHỞI SẮC\n{info}\n\nĐề xuất: MUA {USDT} USDT {SYMBOL}, stop 2×ATR 1h đặt sẵn "
                                     "trên sàn. Lưu ý: tín hiệu này chưa được backtest.",
                         [[button(f"Mua {USDT} USDT {SYMBOL}", f"buy:{SYMBOL}"), button("Bỏ qua", "skip")]])
        if ok != self.state["recovered"]:
            self.state["recovered"] = ok
            self.save()


def main() -> None:
    ex = BinanceSpot()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or not ex.has_keys:
        sys.exit("Cần TELEGRAM_BOT_TOKEN, BINANCE_API_KEY, BINANCE_API_SECRET trong .env")
    ex.sync_time()
    c = Controller(Telegram(token), ManualTrader(ex))
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
