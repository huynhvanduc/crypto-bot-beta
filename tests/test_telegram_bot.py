import pytest

from bot.manual import ManualTrader
from telegram_bot import Controller


class FakeEx:
    is_testnet = True

    def __init__(self):
        self.calls, self.orders, self.next_id = [], {}, 100

    def filters(self, symbol):
        return {"base": symbol[:-4], "step": "0.00001", "tick": "0.01"}

    def market_buy_quote(self, symbol, quote, tag=None):
        self.calls.append(("buy", symbol, quote, tag))
        return {"executedQty": "0.01", "cummulativeQuoteQty": "500", "fills": []}

    def market_sell(self, symbol, qty, tag=None):
        self.calls.append(("sell", symbol, qty, tag))
        return {"executedQty": str(qty), "cummulativeQuoteQty": str(qty * 51000), "fills": []}

    def stop_loss_sell(self, symbol, qty, stop, tag=None):
        self.next_id += 1
        self.orders[self.next_id] = {"status": "NEW", "executedQty": str(qty), "cummulativeQuoteQty": str(qty * stop)}
        self.calls.append(("stop", symbol, round(stop, 2), tag))
        return {"orderId": self.next_id}

    def cancel_order(self, symbol, order_id):
        self.calls.append(("cancel", symbol, order_id))
        self.orders[order_id]["status"] = "CANCELED"

    def get_order(self, symbol, order_id):
        return self.orders[order_id]


class FakeTg:
    def __init__(self):
        self.sent, self.edited, self.answered = [], [], []

    def send(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": len(self.sent)}

    def edit(self, chat_id, message_id, text):
        self.edited.append((chat_id, message_id, text))

    def answer(self, callback_id, text=""):
        self.answered.append((callback_id, text))


def make(tmp_path, recovered=False):
    ex, tg = FakeEx(), FakeTg()
    trader = ManualTrader(ex, tmp_path / "manual.json", atr_fn=lambda s: 500.0)
    state = {"recovered": recovered}
    c = Controller(tg, trader, tmp_path / "telegram.json", check=lambda: (state["recovered"], "BTC trên EMA200"))
    return c, ex, tg, state


def msg(chat, text):
    return {"message": {"chat": {"id": chat}, "text": text}}


def press(chat, data, cb="cb1", message_id=7):
    return {"callback_query": {"id": cb, "data": data, "message": {"chat": {"id": chat}, "message_id": message_id,
                                                                   "text": "Đề xuất"}}}


def test_first_start_sets_owner_and_others_are_ignored(tmp_path):
    c, ex, tg, _ = make(tmp_path)
    c.handle(msg(42, "/start"))
    assert c.owner == 42 and tg.sent[-1][0] == 42
    c.handle(press(99, "buy:BTCUSDT"))
    assert ex.calls == [] and tg.answered[-1][1] == "Không có quyền"


def test_buy_places_market_order_and_stop(tmp_path):
    c, ex, tg, _ = make(tmp_path)
    c.handle(msg(42, "/start"))
    c.handle(press(42, "buy:BTCUSDT"))
    assert ex.calls[0] == ("buy", "BTCUSDT", 500, "tg")
    assert ex.calls[1] == ("stop", "BTCUSDT", 49000.0, "tg")
    assert "Đã MUA" in tg.edited[-1][2]


def test_second_buy_same_coin_refused(tmp_path):
    c, ex, tg, _ = make(tmp_path)
    c.handle(msg(42, "/start"))
    c.handle(press(42, "buy:BTCUSDT"))
    c.handle(press(42, "buy:BTCUSDT", cb="cb2"))
    assert sum(1 for x in ex.calls if x[0] == "buy") == 1
    assert "không mua thêm" in tg.edited[-1][2]


def test_sell_cancels_stop_then_sells(tmp_path):
    c, ex, tg, _ = make(tmp_path)
    c.handle(msg(42, "/start"))
    c.handle(press(42, "buy:BTCUSDT"))
    c.handle(press(42, "sell:BTCUSDT", cb="cb2"))
    assert [x[0] for x in ex.calls] == ["buy", "stop", "cancel", "sell"]
    assert "Đã BÁN" in tg.edited[-1][2] and "+10.00 USDT" in tg.edited[-1][2]
    assert c.trader.pos == {}


def test_stop_fill_is_reported_once(tmp_path):
    c, ex, tg, _ = make(tmp_path)
    c.handle(msg(42, "/start"))
    c.handle(press(42, "buy:BTCUSDT"))
    oid = c.trader.pos["BTCUSDT"]["stop_order_id"]
    ex.orders[oid]["status"] = "FILLED"
    c.tick()
    c.tick()
    assert sum("Stop BTCUSDT đã khớp" in t for _, t, _ in tg.sent) == 1
    assert c.trader.pos == {}


def test_recovery_sends_one_proposal_with_buttons(tmp_path):
    c, ex, tg, state = make(tmp_path)
    c.handle(msg(42, "/start"))
    c.tick()
    assert not any("KHỞI SẮC" in t for _, t, _ in tg.sent)
    state["recovered"] = True
    c.tick()
    c.tick()
    proposals = [(t, b) for _, t, b in tg.sent if "KHỞI SẮC" in t]
    assert len(proposals) == 1
    assert [x["callback_data"] for x in proposals[0][1][0]] == ["buy:BTCUSDT", "skip"]


def test_skip_only_edits_message(tmp_path):
    c, ex, tg, _ = make(tmp_path)
    c.handle(msg(42, "/start"))
    c.handle(press(42, "skip"))
    assert ex.calls == [] and "bỏ qua" in tg.edited[-1][2]


def test_refuses_non_testnet(tmp_path):
    ex = FakeEx()
    ex.is_testnet = False
    with pytest.raises(RuntimeError):
        ManualTrader(ex, tmp_path / "m.json", atr_fn=lambda s: 1.0)
