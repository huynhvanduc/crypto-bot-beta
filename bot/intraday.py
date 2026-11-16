from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import atr, ema, rsi
from .metrics import net_return

FEE = 0.001
SLIP = 0.0005
STOP_ATR = 1.5
TARGET_ATR = 3.0
MIN_TARGET = 0.006
HOLD_NS = 60 * 60_000_000_000
MINUTE_NS = 60_000_000_000
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "taker_buy_volume": "sum"}
ENTRIES = {"A": "Phá đỉnh", "B": "Nhịp chỉnh", "C": "Dòng tiền"}
EXITS = {"fixed": "cố định", "trail": "trailing"}
TRADE_COLUMNS = ["signal_time", "entry_time", "exit_time", "entry_price", "exit_price", "barrier", "minutes",
                 "return_pct", "win"]


@dataclass(frozen=True)
class Variant:
    name: str
    entry: str
    exit: str


VARIANTS = [Variant(f"{e} {ENTRIES[e]} · {EXITS[x]}", e, x) for e in ENTRIES for x in EXITS]


def bars(m: pd.DataFrame, minutes: int) -> pd.DataFrame:
    g = m.resample(f"{minutes}min", label="left", closed="left")
    out = g.agg(AGG)
    out = out[g["close"].count() == minutes].copy()
    out["ready"] = out.index + pd.Timedelta(minutes=minutes)
    return out


def flow(df: pd.DataFrame) -> pd.Series:
    v = df["volume"]
    return ((2 * df["taker_buy_volume"] - v) / v.where(v > 0)).fillna(0.0)


def _known_at(flag: pd.Series, ready: pd.Series, at: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(flag.to_numpy(dtype=float), index=pd.DatetimeIndex(ready))
    return (s.reindex(at, method="ffill") > 0.5).to_numpy()


def regime(h1: pd.DataFrame, btc_h1: pd.DataFrame, at: pd.DatetimeIndex) -> np.ndarray:
    c, b = h1["close"], btc_h1["close"]
    e200 = ema(c, 200)
    coin_up = (c > e200) & (ema(c, 50) > e200)
    btc_up = b > ema(b, 200)
    return _known_at(coin_up, h1["ready"], at) & _known_at(btc_up, btc_h1["ready"], at)


def prepare(m: pd.DataFrame, btc_m: pd.DataFrame) -> pd.DataFrame:
    f = bars(m, 5)
    fl, r = flow(f), rsi(f["close"], 14)
    out = pd.DataFrame(index=pd.DatetimeIndex(f["ready"], name="ready"))
    out["A"] = ((f["close"] > f["high"].shift(1).rolling(12).max()) & (fl > 0.2)).to_numpy()
    out["B"] = ((r.shift(1) < 40) & (r >= 40)).to_numpy()
    out["C"] = ((fl > 0.3) & (f["close"] > f["open"])).to_numpy()
    out["atr"] = atr(f, 14).to_numpy()
    out["contiguous"] = (f.index.to_series().diff() == pd.Timedelta(minutes=5)).to_numpy()
    out["regime"] = regime(bars(m, 60), bars(btc_m, 60), out.index)
    return out


def exit_trade(t, o, h, l, c, j0: int, atr_value: float, kind: str):
    entry = o[j0]
    stop, target, peak = entry - STOP_ATR * atr_value, entry + TARGET_ATR * atr_value, -np.inf
    end = t[j0] + HOLD_NS
    if t[-1] < end - MINUTE_NS:
        return None
    last = int(np.searchsorted(t, end)) - 1
    for j in range(j0, last + 1):
        if o[j] <= stop:
            return j, float(o[j]), "stop"
        if l[j] <= stop:
            return j, float(stop), "stop"
        if kind == "fixed" and h[j] >= target:
            return j, float(target), "target"
        if kind == "trail":
            peak = max(peak, h[j])
            stop = max(stop, peak - STOP_ATR * atr_value)
    return last, float(c[last]), "time"


def trade_return(entry: float, exit_price: float) -> float:
    return net_return(entry * (1 + SLIP), exit_price * (1 - SLIP), FEE)


def backtest(m: pd.DataFrame, prep: pd.DataFrame, v: Variant, use_regime: bool = True) -> pd.DataFrame:
    t = m.index.as_unit("ns").asi8
    o, h, l, c = (m[k].to_numpy() for k in ("open", "high", "low", "close"))
    ok = prep[v.entry].to_numpy(dtype=bool) & prep["contiguous"].to_numpy(dtype=bool)
    if use_regime:
        ok &= prep["regime"].to_numpy(dtype=bool)
    ready, atr_v = prep.index.as_unit("ns").asi8, prep["atr"].to_numpy()
    trades, busy = [], -1
    for i in np.flatnonzero(ok):
        if ready[i] <= busy:
            continue
        j0 = int(np.searchsorted(t, ready[i]))
        if j0 >= len(t) or t[j0] != ready[i]:
            continue
        entry = o[j0]
        if not TARGET_ATR * atr_v[i] / entry >= MIN_TARGET:
            continue
        res = exit_trade(t, o, h, l, c, j0, atr_v[i], v.exit)
        if res is None:
            break
        j, px, why = res
        ret = trade_return(entry, px)
        trades.append([prep.index[i], m.index[j0], m.index[j], entry, px, why, int((t[j] - t[j0]) // MINUTE_NS) + 1,
                       ret * 100, ret > 0])
        busy = t[j]
    return pd.DataFrame(trades, columns=TRADE_COLUMNS)
