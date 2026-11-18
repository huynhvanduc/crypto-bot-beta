from bot.exchange import BinanceSpot, client_id


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



def test_oco_sell_tags_both_legs():
    ex = Rec()
    ex.oco_sell("BTCUSDT", 0.0012345, 61000.123, 59000.456, tag="ai")
    m, path, p = ex.calls[0]
    assert (m, path) == ("POST", "/api/v3/orderList/oco")
    assert p["side"] == "SELL" and p["quantity"] == "0.00123"
    assert p["aboveType"] == "LIMIT_MAKER" and p["abovePrice"] == "61000.12"
    assert p["belowType"] == "STOP_LOSS" and p["belowStopPrice"] == "59000.45"
    assert all(p[k].startswith("ai-") for k in ("listClientOrderId", "aboveClientOrderId", "belowClientOrderId"))
