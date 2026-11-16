import json
from datetime import datetime, timezone

import pytest

from bot.watcher import FillWatcher


def report(**kw):
    ev = {"e": "executionReport", "E": 1794669000000, "s": "BTCUSDT", "c": "scalp-1", "S": "BUY", "o": "MARKET",
          "q": "0.1", "p": "0", "x": "TRADE", "X": "FILLED", "i": 11, "l": "0.1", "L": "65000", "Y": "6500",
          "n": "0", "N": "BTC", "T": 1794669000000, "t": 501, "z": "0.1", "Z": "6500"}
    ev.update(kw)
    return {"subscriptionId": 0, "event": ev}


def balance(usdt):
    return {"subscriptionId": 0, "event": {"e": "outboundAccountPosition", "E": 1, "u": 1,
                                           "B": [{"a": "USDT", "f": str(usdt), "l": "0"}]}}


def rest(tid, ms, order):
    return {"symbol": "BTCUSDT", "id": tid, "orderId": order, "price": "65000", "qty": "0.1", "quoteQty": "6500",
            "commission": "0", "commissionAsset": "BTC", "time": ms, "isBuyer": True, "isMaker": False}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeEx:
    def __init__(self, trades=None, orders=None):
        self.trades, self.orders, self.calls = trades or {}, orders or {}, []

    def my_trades(self, symbol, from_id=None, limit=1000):
        self.calls.append((symbol, from_id))
        return [t for t in self.trades.get(symbol, []) if from_id is None or t["id"] >= from_id]

    def get_order(self, symbol, order_id):
        return self.orders[order_id]

    def free(self, asset):
        return 9996.82


def make(tmp_path, ex=None, state=None, clock=None):
    sent = []
    sp = tmp_path / "state.json"
    if state is not None:
        sp.write_text(json.dumps(state), encoding="utf-8")
    w = FillWatcher(ex or FakeEx(), sent.append, ["BTCUSDT"], topic="t", fills_path=tmp_path / "fills.json",
                    docs_path=tmp_path / "docs" / "fills.json", state_path=sp, clock=clock or Clock())
    return w, sent


def test_fill_published_together_with_balance(tmp_path):
    w, sent = make(tmp_path)
    assert w.handle(report()) == [] and sent == []
    out = w.handle(balance(9990))
    assert len(out) == 1 and sent == [{"v": 1, "kind": "fill", "fill": out[0], "usdt": 9990.0}]
    assert out[0]["source"] == "scalp"
    assert json.loads((tmp_path / "fills.json").read_text(encoding="utf-8"))["fills"] == [out[0]]
    assert w.dirty


def test_fill_published_after_wait_without_balance(tmp_path):
    clock = Clock()
    w, sent = make(tmp_path, clock=clock)
    w.handle(report())
    assert w.tick() == []
    clock.t += 0.6
    assert len(w.tick()) == 1 and len(sent) == 1


def test_duplicate_event_not_republished(tmp_path):
    w, sent = make(tmp_path)
    for _ in range(2):
        w.handle(report())
        w.handle(balance(1))
    assert len(sent) == 1 and len(w.fills) == 1


def test_bot_stop_fill_sets_flag(tmp_path):
    w, _ = make(tmp_path, state={"positions": {"BTCUSDT": {"stop_order_id": 11}}})
    w.handle(report(c="web_x", o="STOP_LOSS", S="SELL"))
    assert w.bot_stop_filled
    assert w.handle(balance(1))[0]["source"] == "d1"


def test_stream_terminated_raises(tmp_path):
    w, _ = make(tmp_path)
    with pytest.raises(ConnectionError):
        w.handle({"subscriptionId": 0, "event": {"e": "eventStreamTerminated", "E": 1}})


def test_backfill_respects_start_then_continues_from_last_id(tmp_path):
    start_ms = int(datetime(2026, 11, 14, 13, 50, 31, tzinfo=timezone.utc).timestamp() * 1000)
    ex = FakeEx({"BTCUSDT": [rest(1, start_ms - 1000, 6), rest(2, start_ms + 1000, 7)]},
                {7: {"clientOrderId": "scalp-1-0", "type": "MARKET"}})
    w, sent = make(tmp_path, ex=ex, state={"start": "2026-11-14T13:50:31Z", "positions": {}})
    assert w.backfill() == 1
    assert w.fills[0]["trade_id"] == 2 and w.fills[0]["source"] == "scalp"
    assert w.usdt == 9996.82 and w.dirty and sent == []
    assert w.backfill() == 0
    assert ex.calls[-1] == ("BTCUSDT", 3)


def test_load_restores_saved_fills(tmp_path):
    w, _ = make(tmp_path)
    w.handle(report())
    w.handle(balance(5))
    w2, _ = make(tmp_path)
    w2.load()
    assert w2.fills == w.fills and w2.usdt == 5.0


def test_export_writes_public_file(tmp_path):
    w, _ = make(tmp_path)
    w.handle(report(t=1, i=1))
    w.handle(report(t=2, i=2, S="SELL", L="65100", Y="6510", N="USDT", T=1794669001000))
    w.handle(balance(10010))
    data = w.export()
    assert json.loads((tmp_path / "docs" / "fills.json").read_text(encoding="utf-8")) == data
    assert data["topic"] == "t" and data["usdt"] == 10010.0
    assert [f["trade_id"] for f in data["fills"]] == [2, 1]
    assert data["round_trips"]["count"] == 1 and data["round_trips"]["pnl_usdt"] == pytest.approx(10.0)
    assert data["updated"].endswith("Z") and w.dirty is False


def test_poll_publishes_only_new_fills(tmp_path):
    ex = FakeEx({"BTCUSDT": [rest(1, 2000, 7), rest(2, 3000, 8)]},
                {7: {"clientOrderId": "scalp-1-0", "type": "MARKET"}, 8: {"clientOrderId": "x", "type": "MARKET"}})
    w, sent = make(tmp_path, ex)
    first = w.poll()
    assert [f["trade_id"] for f in first] == [1, 2]
    assert [m["fill"]["trade_id"] for m in sent] == [1, 2]
    assert w.poll() == []
    assert len(sent) == 2
    assert not w.bot_stop_filled


def test_poll_flags_bot_stop_fill(tmp_path):
    ex = FakeEx({"BTCUSDT": [rest(1, 2000, 7)]}, {7: {"clientOrderId": "d1-1-0", "type": "STOP_LOSS"}})
    w, _ = make(tmp_path, ex)
    w.poll()
    assert w.bot_stop_filled
