import pytest

from bot.fills import classify, fill_from_event, fill_from_rest, merge, round_trips

EV = {"e": "executionReport", "E": 1794669000100, "s": "BTCUSDT", "c": "scalp-1794669000000-1", "S": "BUY",
      "o": "MARKET", "f": "GTC", "q": "0.14421000", "p": "0.00000000", "x": "TRADE", "X": "FILLED",
      "i": 123, "l": "0.14421000", "z": "0.14421000", "L": "65871.90000000", "n": "0.00000000", "N": "BTC",
      "T": 1794669000000, "t": 555, "Z": "9499.39000000", "Y": "9499.39000000"}


def test_fill_from_trade_event():
    assert fill_from_event(EV) == {
        "trade_id": 555, "order_id": 123, "client_id": "scalp-1794669000000-1", "symbol": "BTCUSDT",
        "side": "BUY", "type": "MARKET", "qty": 0.14421, "price": 65871.9, "quote": 9499.39,
        "fee": 0.0, "fee_asset": "BTC", "time": "2026-11-14T15:10:00.000Z", "ms": 1794669000000,
        "source": "scalp"}


def test_non_trade_events_ignored():
    assert fill_from_event({**EV, "x": "NEW"}) is None
    assert fill_from_event({"e": "outboundAccountPosition"}) is None


def test_classify():
    assert classify("d1-1-0", 1, set()) == "d1"
    assert classify("scalp-1-0", 1, set()) == "scalp"
    assert classify("ai-1-0", 1, set()) == "ai"
    assert classify("web_abc", 7, {7}) == "d1"
    assert classify("", 1, set()) == "tay"
    assert classify(None, 1, set()) == "tay"


def test_fill_from_rest_matches_event_shape():
    t = {"symbol": "BTCUSDT", "id": 555, "orderId": 123, "price": "65871.9", "qty": "0.14421",
         "quoteQty": "9499.39", "commission": "0", "commissionAsset": "BTC", "time": 1794669000000,
         "isBuyer": True, "isMaker": False}
    assert fill_from_rest(t, "scalp-1794669000000-1", "MARKET") == fill_from_event(EV)


def test_merge_dedupes_and_sorts():
    a = fill_from_event(EV)
    b = fill_from_event({**EV, "t": 556, "T": 1794668000000})
    assert [f["trade_id"] for f in merge([a], [b, a])] == [556, 555]


def F(tid, side, qty, price, oid=None, fee=0.0, fee_asset="USDT", source="tay", sym="BTCUSDT"):
    return {"trade_id": tid, "order_id": tid if oid is None else oid, "client_id": "", "symbol": sym,
            "side": side, "type": "MARKET", "qty": qty, "price": price, "quote": qty * price, "fee": fee,
            "fee_asset": fee_asset, "time": f"t{tid}", "ms": tid, "source": source}


def test_fee_in_coin_on_buy_and_usdt_on_sell():
    r = round_trips([F(1, "BUY", 1.0, 100.0, fee=0.001, fee_asset="BTC"),
                     F(2, "SELL", 0.999, 110.0, fee=0.10989, fee_asset="USDT")])
    (t,) = r["trades"]
    assert t["qty"] == pytest.approx(0.999)
    assert t["entry_price"] == pytest.approx(100.0) and t["exit_price"] == pytest.approx(110.0)
    assert t["pnl_usdt"] == pytest.approx(9.78011) and t["return_pct"] == pytest.approx(9.78011)
    assert r["open"] == [] and r["pnl_usdt"] == pytest.approx(9.78011) and r["count"] == 1


def test_one_sell_spans_two_buys_and_leaves_open_lot():
    r = round_trips([F(1, "BUY", 1.0, 100.0), F(2, "BUY", 1.0, 120.0), F(3, "SELL", 1.5, 130.0)])
    (t,) = r["trades"]
    assert t["qty"] == pytest.approx(1.5) and t["entry_price"] == pytest.approx(106.6666667)
    assert t["pnl_usdt"] == pytest.approx(35.0)
    assert t["entry_time"] == "t1" and t["exit_time"] == "t3"
    (o,) = r["open"]
    assert o["qty"] == pytest.approx(0.5) and o["entry_price"] == pytest.approx(120.0)
    assert o["cost"] == pytest.approx(60.0) and o["entry_time"] == "t2"


def test_selling_preexisting_coins_has_no_pnl():
    r = round_trips([F(1, "SELL", 1.0, 65000.0)])
    (t,) = r["trades"]
    assert t["pnl_usdt"] is None and t["entry_price"] is None and t["entry_time"] is None
    assert r["pnl_usdt"] == 0 and r["count"] == 0


def test_bot_d1_fills_are_excluded():
    r = round_trips([F(1, "BUY", 1.0, 100.0, source="d1"), F(2, "SELL", 1.0, 110.0, source="d1")])
    assert r == {"trades": [], "open": [], "pnl_usdt": 0, "count": 0}


def test_partial_fills_of_one_order_are_combined():
    r = round_trips([F(1, "BUY", 2.0, 100.0), F(2, "SELL", 1.0, 110.0, oid=9), F(3, "SELL", 1.0, 111.0, oid=9)])
    (t,) = r["trades"]
    assert t["qty"] == pytest.approx(2.0) and t["exit_price"] == pytest.approx(110.5)
    assert t["pnl_usdt"] == pytest.approx(21.0)


def test_newest_round_trip_first():
    r = round_trips([F(1, "BUY", 1.0, 100.0), F(2, "SELL", 1.0, 101.0),
                     F(3, "BUY", 1.0, 100.0), F(4, "SELL", 1.0, 99.0)])
    assert [t["exit_time"] for t in r["trades"]] == ["t4", "t2"]
    assert r["pnl_usdt"] == pytest.approx(0.0) and r["count"] == 2
