import csv
import json

import numpy as np

from bot.journal import excursion, export_docs, features, parse_buy, summary, write_row
from bot.manual import ManualTrader
from telegram_bot import Controller
from tests.test_telegram_bot import FakeEx, FakeTg, msg


def bars(close, vol=None):
    close = np.asarray(close, dtype=float)
    vol = np.ones_like(close) if vol is None else np.asarray(vol, dtype=float)
    return {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": vol}


def test_parse_buy_accepts_short_symbol_amount_and_reason():
    assert parse_buy("/mua sol 200 vượt đỉnh 1h, volume lớn") == ("SOLUSDT", 200.0, "vượt đỉnh 1h, volume lớn")
    assert parse_buy("/mua BTCUSDT") == ("BTCUSDT", 100.0, "")


def test_parse_buy_rejects_bad_input():
    for text in ("/mua", "/mua XYZ 100", "/mua SOL 5", "/mua SOL 5000", "/mua SOL abc"):
        assert isinstance(parse_buy(text), str), text


def test_features_compute_context_from_closed_bars():
    up = np.linspace(100, 110, 300)
    f = features({"5m": bars(up, [1] * 299 + [3]), "15m": bars(up), "1h": bars(up)}, bars(up))
    assert f["rsi_5m"] > 70 and f["above_ema200_1h"] and f["btc_above_ema200_1h"]
    assert abs(f["vol_ratio_5m"] - 3.0) < 0.2
    assert f["ret_1h_pct"] > 0 and 0 <= f["range_pos_24h"] <= 1


def test_excursion_reports_best_and_worst_move():
    k = [[0, "100", "103", "99", "101"], [60000, "101", "102", "97", "98"]]
    mfe, mae = excursion(k, 100.0)
    assert round(mfe, 2) == 3.0 and round(mae, 2) == -3.0


def test_write_row_and_summary_apply_real_fee(tmp_path):
    p = tmp_path / "j.csv"
    write_row(p, {"symbol": "SOLUSDT", "ret_market_pct": 0.6, "minutes": 20})
    write_row(p, {"symbol": "ETHUSDT", "ret_market_pct": 0.0, "minutes": 25, "new_col": 1})
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    assert len(rows) == 2 and rows[0]["symbol"] == "SOLUSDT" and rows[1]["new_col"] == "1"
    s = summary(p)
    # sau phí thật 0,2 % khứ hồi: +0.4 và -0.2 → TB +0.10 %, thắng 50 %
    assert "2 lệnh" in s and "+0.10%" in s and "50%" in s


def make(tmp_path):
    ex, tg = FakeEx(), FakeTg()
    trader = ManualTrader(ex, tmp_path / "manual.json", atr_fn=lambda s: 500.0,
                          journal=tmp_path / "journal.csv",
                          context_fn=lambda s: {"price": 50000.0, "rsi_5m": 55.0},
                          excursion_fn=lambda s, a, b, e: (0.8, -0.3))
    c = Controller(tg, trader, tmp_path / "telegram.json", check=lambda: (False, "x"))
    c.handle(msg(42, "/start"))
    return c, ex, tg


def test_buy_command_saves_reason_and_context_then_sell_writes_journal(tmp_path):
    c, ex, tg = make(tmp_path)
    c.handle(msg(42, "/mua btc 500 phá đỉnh 4h"))
    assert ex.calls[0] == ("buy", "BTCUSDT", 500.0, "tg")
    p = c.trader.pos["BTCUSDT"]
    assert p["reason"] == "phá đỉnh 4h" and p["ctx"]["rsi_5m"] == 55.0
    c.handle(msg(42, "/ban btc"))
    assert "Đã BÁN" in tg.sent[-1][1]
    rows = list(csv.DictReader((tmp_path / "journal.csv").open(encoding="utf-8")))
    r = rows[0]
    assert r["symbol"] == "BTCUSDT" and r["reason"] == "phá đỉnh 4h" and r["exit_how"] == "tay"
    assert r["e_rsi_5m"] == "55.0" and r["mfe_pct"] == "0.8" and r["mae_pct"] == "-0.3"
    assert float(r["ret_testnet_pct"]) == 2.0


def test_bad_buy_command_replies_with_error_and_no_order(tmp_path):
    c, ex, tg = make(tmp_path)
    c.handle(msg(42, "/mua XYZ 100"))
    assert ex.calls == [] and "Không" in tg.sent[-1][1]


def test_export_docs_has_open_closed_and_stats(tmp_path):
    c, ex, tg = make(tmp_path)
    c.handle(msg(42, "/mua btc 500 lý do A"))
    c.handle(msg(42, "/mua eth 100"))
    c.handle(msg(42, "/ban btc"))
    out = tmp_path / "docs" / "manual.json"
    d = export_docs(c.trader, out)
    assert json.loads(out.read_text(encoding="utf-8")) == d
    assert [o["symbol"] for o in d["open"]] == ["ETHUSDT"]
    assert d["closed"][0]["symbol"] == "BTCUSDT" and d["closed"][0]["reason"] == "lý do A"
    assert d["closed"][0]["net_pct"] == -0.2  # giá thị trường giả không đổi → chỉ còn phí thật
    assert d["stats"]["trades"] == 1 and d["fee_rt_pct"] == 0.2


def test_controller_publishes_after_buy_sell_and_stop(tmp_path):
    c, ex, tg = make(tmp_path)
    calls = []
    c.publish = lambda: calls.append(1)
    c.handle(msg(42, "/mua btc 500"))
    c.handle(msg(42, "/lenh"))
    assert len(calls) == 1
    c.handle(msg(42, "/ban btc"))
    assert len(calls) == 2
    c.handle(msg(42, "/mua btc 500"))
    ex.orders[c.trader.pos["BTCUSDT"]["stop_order_id"]]["status"] = "FILLED"
    c.tick()
    assert len(calls) == 4


def test_reminders_at_15_and_30_minutes_once_each(tmp_path):
    c, ex, tg = make(tmp_path)
    c.handle(msg(42, "/mua btc 500"))
    clock = {"t": c.trader.pos["BTCUSDT"]["ts"]}
    c.now = lambda: clock["t"]
    c.tick()
    clock["t"] += 15 * 60 + 1
    c.tick()
    c.tick()
    clock["t"] += 15 * 60
    c.tick()
    texts = [t for _, t, _ in tg.sent if "đã giữ" in t]
    assert len(texts) == 2 and "15 phút" in texts[0] and "30 phút" in texts[1]
