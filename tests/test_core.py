import numpy as np
import pandas as pd
import pytest

from bot.backtest import run_backtest
from bot.config import Config
from bot.indicators import atr, rsi
from bot.labeling import triple_barrier
from bot.metrics import compute_metrics, oos_ratio



def arrays(highs, lows, closes):
    return np.array(highs, float), np.array(lows, float), np.array(closes, float)


def test_tp_hit_is_win():
    h, l, c = arrays([101, 103], [99.5, 100], [100, 102])
    r = triple_barrier(h, l, c, 0, 100.0, 1.0, max_bars=2)
    assert r.barrier == "tp" and r.exit_price == 102.0 and r.exit_idx == 1


def test_sl_hit_is_loss():
    h, l, c = arrays([100.5, 100.2], [99.5, 98.9], [100, 99])
    r = triple_barrier(h, l, c, 0, 100.0, 1.0, max_bars=2)
    assert r.barrier == "sl" and r.exit_price == 99.0


def test_both_hit_same_bar_counts_as_loss():
    h, l, c = arrays([102.5], [98.5], [100])
    r = triple_barrier(h, l, c, 0, 100.0, 1.0, max_bars=1)
    assert r.barrier == "sl"


def test_time_barrier_closes_at_last_close():
    h, l, c = arrays([100.5] * 3, [99.5] * 3, [100, 100.2, 100.4])
    r = triple_barrier(h, l, c, 0, 100.0, 1.0, max_bars=3)
    assert r.barrier == "time" and r.exit_idx == 2 and r.exit_price == 100.4


def test_incomplete_returns_none():
    h, l, c = arrays([100.5] * 2, [99.5] * 2, [100, 100])
    assert triple_barrier(h, l, c, 0, 100.0, 1.0, max_bars=5) is None



def test_trailing_stop_raises_after_bar_closes():
    from bot.exits import trailing_stop
    o = np.array([100, 101, 104, 105], float)
    h = np.array([101, 105, 106, 105.5], float)
    l = np.array([99.5, 100.5, 103.5, 103.0], float)
    c = np.array([100.5, 104, 105, 104], float)
    r = trailing_stop(o, h, l, c, 0, 100.0, 1.0, sl_atr=2, trail_atr=2, max_bars=4)
    assert r.barrier == "stop" and r.exit_idx == 3 and r.exit_price == 104.0


def test_trailing_stop_exits_even_if_max_bars_beyond_data():
    from bot.exits import trailing_stop
    o = np.array([100, 99], float)
    h = np.array([100.5, 99.5], float)
    l = np.array([99.5, 97], float)
    c = np.array([100, 97.5], float)
    r = trailing_stop(o, h, l, c, 0, 100.0, 1.0, sl_atr=2, trail_atr=3, max_bars=240)
    assert r is not None and r.exit_idx == 1 and r.exit_price == 98.0


def test_trailing_stop_gap_exits_at_open():
    from bot.exits import trailing_stop
    o = np.array([100, 95], float)
    h = np.array([100.5, 96], float)
    l = np.array([99.5, 94], float)
    c = np.array([100, 95], float)
    r = trailing_stop(o, h, l, c, 0, 100.0, 1.0, sl_atr=2, trail_atr=3, max_bars=2)
    assert r.exit_idx == 1 and r.exit_price == 95.0



def test_rsi_bounds_and_monotonic_up():
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert rsi(up).dropna().eq(100).all()
    noise = pd.Series(np.random.default_rng(0).normal(0, 1, 500).cumsum() + 100)
    v = rsi(noise).dropna()
    assert ((v >= 0) & (v <= 100)).all()


def test_atr_constant_range():
    n = 50
    df = pd.DataFrame({"high": [101.0] * n, "low": [99.0] * n, "close": [100.0] * n})
    assert atr(df).dropna().iloc[-1] == pytest.approx(2.0)



def test_metrics_examples_from_doc():
    trades = pd.DataFrame({"return_pct": [3.0] * 4 + [-1.0] * 6})
    m = compute_metrics(trades)
    assert m["win_rate_pct"] == pytest.approx(40)
    assert m["expectancy_pct"] == pytest.approx(0.6)
    assert m["profit_factor"] == pytest.approx(2.0)


def test_portfolio_drawdown_splits_capital_equally():
    t = pd.Timestamp("2024-01-01", tz="UTC")
    trades = pd.DataFrame({
        "symbol": ["A", "B"],
        "exit_time": [t, t + pd.Timedelta(hours=1)],
        "return_pct": [-20.0, 0.0],
    })
    assert compute_metrics(trades)["max_drawdown_pct"] == pytest.approx(10.0)


def test_oos_ratio_fails_when_is_not_positive():
    assert oos_ratio({"expectancy_pct": -0.1}, {"expectancy_pct": 0.5}) == 0.0



def test_simulate_skipped_signal_frees_slot_for_next():
    t = pd.Timestamp("2024-01-01", tz="UTC")
    h = pd.Timedelta(hours=1)
    cands = pd.DataFrame({
        "symbol": ["A", "A", "B"],
        "signal_time": [t, t + h, t + h],
        "exit_time": [t + 10 * h, t + 5 * h, t + 3 * h],
        "return_pct": [1.0, 2.0, 3.0],
    })
    from bot.backtest import simulate
    assert simulate(cands)["return_pct"].tolist() == [1.0, 3.0]
    assert sorted(simulate(cands, [False, True, True])["return_pct"]) == [2.0, 3.0]



def test_htf_features_use_only_closed_bars():
    from bot.features import _htf_features
    n = 24 * 60
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    close = pd.Series(np.linspace(100, 200, n), index=idx)
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0})
    full = _htf_features(df)
    k = 1000
    df2 = df.copy()
    df2.iloc[k:, :4] *= 3
    cut = _htf_features(df2)
    pd.testing.assert_frame_equal(full.iloc[:k], cut.iloc[:k])


def test_resample_keeps_only_complete_bars():
    from bot.data import resample_ohlc
    idx = pd.date_range("2024-01-01 00:00", periods=10, freq="h", tz="UTC")
    df = pd.DataFrame({"open": np.arange(10.0), "high": np.arange(10.0) + 1,
                       "low": np.arange(10.0) - 1, "close": np.arange(10.0) + 0.5,
                       "volume": 1.0}, index=idx)
    out = resample_ohlc(df, "4h")
    assert len(out) == 2
    assert out.iloc[0].tolist() == [0.0, 4.0, -1.0, 3.5, 4.0]


def test_paper_matches_backtest():
    from bot.paper import run_paper
    from bot.variants import VARIANTS, backtest_variant
    rng = np.random.default_rng(3)
    n = 1500
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.03, n)))
    df = pd.DataFrame({
        "open": np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n)),
        "high": close * 1.02, "low": close * 0.98, "close": close, "volume": 1.0,
    }, index=pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"))
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    v = next(x for x in VARIANTS if x.name.startswith("D1"))
    cfg = Config()
    bt = backtest_variant(df, cfg, v)
    pp = run_paper(df, cfg, v, df.index[0])
    assert len(bt) > 5
    cols = ["entry_time", "exit_time", "entry_price", "exit_price", "return_pct"]
    pd.testing.assert_frame_equal(pp.trades[cols], bt[cols])



def test_backtest_does_not_use_future_bars():
    rng = np.random.default_rng(1)
    n = 3000
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    df = pd.DataFrame({
        "open": np.r_[close[0], close[:-1]],
        "high": close * 1.005, "low": close * 0.995, "close": close,
        "volume": 1.0,
    }, index=pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC"))
    cfg = Config()
    full = run_backtest(df, cfg)
    cut = run_backtest(df.iloc[:2000], cfg)
    assert not full.empty
    done = full[full["exit_time"] < df.index[1999]]
    pd.testing.assert_frame_equal(done.reset_index(drop=True),
                                  cut.iloc[: len(done)].reset_index(drop=True))



def test_signature_matches_binance_docs_example():
    from bot.exchange import sign
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    q = ("symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
         "&recvWindow=5000&timestamp=1499827319559")
    assert sign(secret, q) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_round_step_rounds_down_without_scientific_notation():
    from bot.exchange import round_step
    assert round_step(1.23456, "0.01000000") == "1.23"
    assert round_step(0.000012345, "0.00000100") == "0.000012"
    assert round_step(1234.9, "1.00000000") == "1234"



class FakeExchange:
    def __init__(self):
        self.px, self.orders, self.n = 100.0, {}, 0

    def sync_time(self): pass
    def filters(self, s): return {"base": "X", "step": "0.0001", "tick": "0.01", "min_notional": 5, "min_qty": 0}
    def price(self, s): return self.px
    def free(self, a): return 1e9

    def _fill(self, qty, px):
        self.n += 1
        return {"orderId": self.n, "status": "FILLED", "executedQty": str(qty),
                "cummulativeQuoteQty": str(qty * px), "fills": []}

    def market_buy_quote(self, s, q, tag=None): return self._fill(q / self.px, self.px)
    def market_sell(self, s, qty, tag=None): return self._fill(qty, self.px)

    def stop_loss_sell(self, s, qty, stop, tag=None):
        self.n += 1
        self.orders[self.n] = {"status": "NEW", "qty": qty, "stop": stop}
        return {"orderId": self.n}

    def get_order(self, s, oid):
        o = self.orders[oid]
        if o["status"] == "FILLED":
            return {"status": "FILLED", "executedQty": str(o["qty"]),
                    "cummulativeQuoteQty": str(o["qty"] * o["stop"]), "fills": []}
        return {"status": o["status"]}

    def cancel_order(self, s, oid): self.orders[oid]["status"] = "CANCELED"


def _daily(n, last_close):
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    close = np.linspace(50, 90, n)
    close[-1] = last_close
    df = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0},
                      index=idx)
    from bot.strategy import add_indicators
    return add_indicators(df, Config())


def test_live_trader_enter_trail_and_stop_fill(tmp_path, monkeypatch):
    from bot import live
    monkeypatch.setattr(live, "STATE_PATH", tmp_path / "state.json")
    ex = FakeExchange()
    st = live.load_state(1000.0, ["AAAUSDT"], "test")
    t = live.LiveTrader(ex, st)
    bars = {"AAAUSDT": _daily(300, 100.0)}
    monkeypatch.setattr(t, "daily", lambda s: bars[s])

    snap = t.run()
    pos = st["positions"]["AAAUSDT"]
    assert snap["entered"] == ["AAAUSDT"] and pos["stop"] < 100
    first_stop_id = pos["stop_order_id"]

    t.run()
    assert st["positions"]["AAAUSDT"]["stop_order_id"] == first_stop_id

    df = bars["AAAUSDT"]
    nxt = pd.DataFrame({"open": [100.0], "high": [130.0], "low": [99.0], "close": [128.0], "volume": [1.0]},
                       index=[df.index[-1] + pd.Timedelta(days=1)])
    from bot.strategy import add_indicators
    bars["AAAUSDT"] = add_indicators(pd.concat([df[["open", "high", "low", "close", "volume"]], nxt]), Config())
    t.run()
    pos = st["positions"]["AAAUSDT"]
    assert ex.orders[first_stop_id]["status"] == "CANCELED"
    assert pos["stop"] > 100 and pos["bars_held"] == 1

    ex.orders[pos["stop_order_id"]]["status"] = "FILLED"
    t.run()
    assert "AAAUSDT" not in st["positions"]
    assert st["trades"][0]["reason"] == "stop" and st["trades"][0]["return_pct"] > 0
    assert st["slots"]["AAAUSDT"] > 1000


def test_live_close_all_sells_and_pauses(tmp_path, monkeypatch):
    from bot import live
    monkeypatch.setattr(live, "STATE_PATH", tmp_path / "state.json")
    ex = FakeExchange()
    st = live.load_state(1000.0, ["AAAUSDT"], "test")
    t = live.LiveTrader(ex, st)
    bars = {"AAAUSDT": _daily(300, 100.0)}
    monkeypatch.setattr(t, "daily", lambda s: bars[s])
    t.run()
    sid = st["positions"]["AAAUSDT"]["stop_order_id"]
    ex.px = 95.0
    assert t.close_all() == 1
    assert st["positions"] == {} and st["paused"] is True
    assert ex.orders[sid]["status"] == "CANCELED"
    assert st["trades"][-1]["reason"] == "bán tay" and st["trades"][-1]["return_pct"] < 0
    st["last_bar"] = None
    assert t.run()["entered"] == []
    t.set_paused(False)
    st["last_bar"] = None
    st["last_exit_bar"] = {}
    assert t.run()["entered"] == ["AAAUSDT"]


def test_btc_filter_blocks_signals_when_btc_below_ema():
    from bot.variants import Variant
    from bot.exits import ExitRule
    from bot.strategy import add_indicators
    df = add_indicators(_daily(300, 100.0)[["open", "high", "low", "close", "volume"]], Config())
    v = Variant("x", "donchian20", ExitRule("trail", 2, 240, trail_atr=3), btc_filter=True)
    ok = pd.Series(True, index=df.index)
    assert bool(v.signals(df, Config(), ok).iloc[-1])
    assert not bool(v.signals(df, Config(), ~ok).iloc[-1])
