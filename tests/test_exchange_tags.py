import inspect

from bot.exchange import BinanceSpot, client_id
from bot.live import LiveTrader
from bot.sim_exchange import SimExchange


class Rec(BinanceSpot):

    def __init__(self):
        super().__init__(key="k", secret="s", base_url="https://testnet.binance.vision")
        self.calls = []
        self._filters = {"BTCUSDT": {"base": "BTC", "quote": "USDT", "step": "0.00001", "min_qty": 0.00001,
                                     "tick": "0.01", "min_notional": 5.0, "order_types": []}}

    def _request(self, method, path, params=None, signed=False):
        self.calls.append((method, path, params))
        return {"orderId": 1}


def test_client_id_format():
    a, b = client_id("d1"), client_id("d1")
    assert a.startswith("d1-") and len(a) <= 36 and a != b
    assert client_id(None) is None and client_id("") is None


def test_orders_carry_tag():
    ex = Rec()
    ex.market_buy_quote("BTCUSDT", 100, tag="scalp")
    ex.market_sell("BTCUSDT", 0.001, tag="d1")
    ex.stop_loss_sell("BTCUSDT", 0.001, 60000, tag="d1")
    ids = [p["newClientOrderId"] for _, _, p in ex.calls]
    assert ids[0].startswith("scalp-") and ids[1].startswith("d1-") and ids[2].startswith("d1-")


def test_no_tag_sends_no_client_id():
    ex = Rec()
    ex.market_sell("BTCUSDT", 0.001)
    assert ex.calls[0][2].get("newClientOrderId") is None


def test_my_trades_request():
    ex = Rec()
    ex.my_trades("BTCUSDT", from_id=5)
    assert ex.calls[0] == ("GET", "/api/v3/myTrades", {"symbol": "BTCUSDT", "fromId": 5, "limit": 1000})


def test_sim_exchange_accepts_tag():
    for name in ("market_buy_quote", "market_sell", "stop_loss_sell"):
        assert "tag" in inspect.signature(getattr(SimExchange, name)).parameters


class StopEx:
    def __init__(self):
        self.calls = []

    def stop_loss_sell(self, sym, qty, stop, tag=None):
        self.calls.append(tag)
        return {"orderId": 1}


def test_bot_tags_its_orders():
    ex = StopEx()
    LiveTrader(ex, {"slots": {"BTCUSDT": 100.0}, "log": [], "positions": {}})._place_stop(
        "BTCUSDT", {"qty": 0.001, "stop": 60000.0})
    assert ex.calls == ["d1"]
