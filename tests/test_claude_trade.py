import sys
from types import SimpleNamespace

sys.stdout.reconfigure = lambda **k: None
import claude_trade


class Ex:
    def __init__(self, status):
        self.status = status

    def order_list(self, list_id):
        return {"orders": [{"orderId": 1}, {"orderId": 2}]}

    def get_order(self, symbol, order_id):
        return {"orderId": order_id, "status": self.status.get(order_id, "NEW"), "type": "LIMIT_MAKER" if order_id == 1 else "STOP_LOSS"}


def trader(status, pos):
    done = []
    t = SimpleNamespace(ex=Ex(status), pos=pos, done=done)
    t._result = lambda s, o, how, exit_how: done.append((s, o["orderId"], exit_how)) or how
    return t


def test_sync_closes_filled_take_profit():
    t = trader({1: "FILLED", 2: "EXPIRED"}, {"BTCUSDT": {"oco": 9, "stop_order_id": 2}})
    assert claude_trade.sync(t) == ["Chốt lời BTCUSDT:"]
    assert t.done == [("BTCUSDT", 1, "tp")]


def test_sync_closes_filled_stop_without_oco():
    t = trader({2: "FILLED"}, {"ETHUSDT": {"stop_order_id": 2}})
    assert claude_trade.sync(t) == ["Cắt lỗ ETHUSDT:"]
    assert t.done == [("ETHUSDT", 2, "stop")]


def test_sync_keeps_open_positions():
    t = trader({}, {"SOLUSDT": {"oco": 9, "stop_order_id": 2}, "XRPUSDT": {"stop_order_id": None}})
    assert claude_trade.sync(t) == [] and t.done == []
