import io
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

from bot.intraday import Variant, backtest, bars, exit_trade, flow, prepare, trade_return
from bot.minute_data import MissingData, load_minutes, parse_zip, periods, to_ms

MIN = 60_000_000_000


def minutes(n, start="2026-01-01", price=100.0, step=0.0, vol=10.0, buy=0.5):
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    close = price + step * np.arange(n)
    return pd.DataFrame({"open": close, "high": close + 0.05, "low": close - 0.05, "close": close,
                         "volume": vol, "taker_buy_volume": vol * buy}, index=idx)


def zipped(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


def row(open_time, price=100.0):
    return f"{open_time},{price},{price + 1},{price - 1},{price},10,0,1000,5,6,600,0\n"


class Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        pass


def test_to_ms_converts_microseconds():
    out = to_ms(pd.Series(["1730419200000", "1794528000000000"]))
    assert out.tolist() == [1730419200000, 1794528000000]


def test_parse_zip_skips_header_and_mixed_units():
    df = parse_zip(zipped("open_time,open,high,low,close,volume,close_time,qv,count,tb,tbq,ignore\n"
                          + row(1730419200000) + row(1794528000000000, 200.0)))
    assert df["open_time"].tolist() == [1730419200000, 1794528000000]
    assert df["close"].tolist() == [100.0, 200.0]
    assert df["taker_buy_volume"].tolist() == [6.0, 6.0]


def test_periods_monthly_then_daily():
    p = periods(date(2026, 9, 20), date(2026, 11, 14), date(2026, 11, 15))
    assert p[:2] == [("monthly", "2026-09"), ("monthly", "2026-10")]
    assert p[2] == ("daily", "2026-11-01") and p[-1] == ("daily", "2026-11-14") and len(p) == 16


def test_load_minutes_falls_back_to_daily_and_uses_cache(tmp_path):
    calls = []

    def get(url, timeout):
        calls.append(url)
        if "/monthly/" in url:
            return Resp(404)
        day = url.rsplit("-1m-", 1)[1][:-4]
        ms = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)
        return Resp(200, zipped(row(ms)))

    df = load_minutes("ETHUSDT", date(2026, 10, 1), date(2026, 10, 2), tmp_path, date(2026, 11, 15), get)
    assert len(df) == 2 and str(df.index[0]) == "2026-10-01 00:00:00+00:00"
    assert len(calls) == 32

    def fail(url, timeout):
        raise AssertionError("không được gọi mạng khi đã có cache")

    assert len(load_minutes("ETHUSDT", date(2026, 10, 1), date(2026, 10, 2), tmp_path, date(2026, 11, 15), fail)) == 2


def test_load_minutes_missing_day_raises(tmp_path):
    with pytest.raises(MissingData):
        load_minutes("ETHUSDT", date(2026, 11, 1), date(2026, 11, 2), tmp_path, date(2026, 11, 15),
                     lambda url, timeout: Resp(404))


def test_bars_drop_incomplete_and_mark_ready():
    m = minutes(10).drop(pd.Timestamp("2026-01-01 00:07", tz="UTC"))
    b = bars(m, 5)
    assert len(b) == 1
    assert str(b["ready"].iloc[0]) == "2026-01-01 00:05:00+00:00"


def test_flow_range_and_zero_volume():
    df = pd.DataFrame({"volume": [10.0, 0.0], "taker_buy_volume": [8.0, 0.0]})
    assert flow(df).round(6).tolist() == [0.6, 0.0]


def path(n=70, price=100.0):
    o, h, l, c = (np.full(n, price) for _ in range(4))
    return np.arange(n) * MIN, o, h.copy() + 0.1, l.copy() - 0.1, c


def test_exit_stop():
    t, o, h, l, c = path()
    l[2] = 98.0
    assert exit_trade(t, o, h, l, c, 0, 1.0, "fixed") == (2, 98.5, "stop")


def test_exit_target():
    t, o, h, l, c = path()
    h[3] = 103.5
    assert exit_trade(t, o, h, l, c, 0, 1.0, "fixed") == (3, 103.0, "target")


def test_exit_both_in_same_minute_counts_as_stop():
    t, o, h, l, c = path()
    l[3], h[3] = 98.0, 104.0
    assert exit_trade(t, o, h, l, c, 0, 1.0, "fixed") == (3, 98.5, "stop")


def test_exit_after_60_minutes():
    t, o, h, l, c = path()
    assert exit_trade(t, o, h, l, c, 0, 1.0, "fixed") == (59, 100.0, "time")


def test_exit_gap_below_stop_uses_open():
    t, o, h, l, c = path()
    o[4], l[4] = 97.0, 96.9
    assert exit_trade(t, o, h, l, c, 0, 1.0, "fixed") == (4, 97.0, "stop")


def test_trailing_raises_stop():
    t, o, h, l, c = path()
    h[5] = 110.0
    o[6], h[6], l[6] = 109.0, 109.1, 108.0
    assert exit_trade(t, o, h, l, c, 0, 1.0, "trail") == (6, 108.5, "stop")


def test_exit_incomplete_data_returns_none():
    t, o, h, l, c = path(30)
    assert exit_trade(t, o, h, l, c, 0, 1.0, "fixed") is None


def test_trade_return_charges_fee_and_slippage_both_ways():
    expected = (103 * (1 - 0.0005) * (1 - 0.001)) / (100 * (1 + 0.0005) * (1 + 0.001)) - 1
    assert trade_return(100.0, 103.0) == pytest.approx(expected)


def test_regime_needs_btc_uptrend():
    coin = minutes(13_000, step=0.001)
    assert not prepare(coin, minutes(13_000, step=-0.001))["regime"].iloc[-1]
    assert prepare(coin, minutes(13_000, step=0.001))["regime"].iloc[-1]


def test_signals_do_not_look_ahead():
    rng = np.random.default_rng(0)
    m = minutes(3000)
    m["close"] = 100 + rng.normal(0, 0.2, 3000).cumsum()
    m["open"] = m["close"].shift(1).fillna(100.0)
    m["high"] = m[["open", "close"]].max(axis=1) + 0.05
    m["low"] = m[["open", "close"]].min(axis=1) - 0.05
    m["taker_buy_volume"] = rng.uniform(0, 10, 3000)
    cut = m.index[2000]
    later = m.copy()
    later.loc[later.index >= cut, ["open", "high", "low", "close"]] *= 1.5
    later.loc[later.index >= cut, "taker_buy_volume"] = 10.0
    a, b = prepare(m, m), prepare(later, later)
    pd.testing.assert_frame_equal(a[a.index <= cut], b[b.index <= cut])


def prep_for(m, rows):
    idx = pd.DatetimeIndex([r[0] for r in rows])
    return pd.DataFrame({"A": [r[1] for r in rows], "B": False, "C": False, "atr": [r[2] for r in rows],
                         "contiguous": True, "regime": [r[3] for r in rows]}, index=idx)


def test_backtest_entry_rules():
    m = minutes(200)
    m.iloc[20, m.columns.get_loc("high")] = 104.0
    t0 = m.index[0]
    rows = [(t0 + pd.Timedelta(minutes=5), True, 1.0, True),
            (t0 + pd.Timedelta(minutes=10), True, 1.0, True),
            (t0 + pd.Timedelta(minutes=30), True, 0.1, True),
            (t0 + pd.Timedelta(minutes=35), True, 1.0, False)]
    v = Variant("A · cố định", "A", "fixed")
    trades = backtest(m, prep_for(m, rows), v)
    assert len(trades) == 1
    assert trades["entry_time"].iloc[0] == t0 + pd.Timedelta(minutes=5)
    assert trades["barrier"].iloc[0] == "target"
    assert trades["return_pct"].iloc[0] == pytest.approx(trade_return(100.0, 103.0) * 100)
    assert len(backtest(m, prep_for(m, rows), v, use_regime=False)) == 2
