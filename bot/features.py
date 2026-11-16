import numpy as np
import pandas as pd

from .data import resample_ohlc
from .indicators import adx, atr, ema, rsi

BAR = pd.Timedelta(hours=1)

BASE = [
    "rsi", "adx", "atr_pct", "vol_ratio", "dist_ema200", "ema50_slope",
    "hour_sin", "hour_cos", "regime_volatile", "regime_trending",
]
MOMENTUM = ["ret_1", "ret_6", "ret_24", "ret_72", "dd_24h", "atr_ratio"]
HTF = ["h4_dist_ema50", "h4_rsi", "d1_dist_ema50", "d1_ema20_50"]
BTC = ["btc_ret_24", "btc_dist_ema200", "btc_d1_dist_ema50", "btc_atr_pct"]
FEATURES = BASE + MOMENTUM + HTF + BTC


def _closed_bars(df: pd.DataFrame, interval: str, hours: int) -> pd.DataFrame:
    agg = resample_ohlc(df, interval)
    agg.index = agg.index + pd.Timedelta(hours=hours)
    return agg


def _align(htf: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    left = pd.DataFrame({"t": df.index + BAR})
    right = htf.reset_index(names="t").sort_values("t")
    out = pd.merge_asof(left, right, on="t", direction="backward")
    out.index = df.index
    return out.drop(columns="t")


def _htf_features(df: pd.DataFrame) -> pd.DataFrame:
    h4 = _closed_bars(df, "4h", 4)
    h4f = pd.DataFrame({
        "h4_dist_ema50": (h4["close"] / ema(h4["close"], 50) - 1) * 100,
        "h4_rsi": rsi(h4["close"], 14),
    })
    d1 = _closed_bars(df, "1d", 24)
    d1f = pd.DataFrame({
        "d1_dist_ema50": (d1["close"] / ema(d1["close"], 50) - 1) * 100,
        "d1_ema20_50": (ema(d1["close"], 20) / ema(d1["close"], 50) - 1) * 100,
    })
    return pd.concat([_align(h4f, df), _align(d1f, df)], axis=1)


def _btc_features(btc: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    c = btc["close"]
    raw = pd.DataFrame({
        "btc_ret_24": (c / c.shift(24) - 1) * 100,
        "btc_dist_ema200": (c / ema(c, 200) - 1) * 100,
        "btc_atr_pct": atr(btc, 14) / c * 100,
    }, index=btc.index)
    raw["btc_d1_dist_ema50"] = _htf_features(btc)["d1_dist_ema50"]
    return raw.reindex(df.index, method="ffill")


def compute_features(df: pd.DataFrame, btc: pd.DataFrame | None = None) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    c = df["close"]
    f["rsi"] = df["rsi"]
    f["adx"] = adx(df, 14)
    f["atr_pct"] = df["atr"] / c * 100
    f["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
    f["dist_ema200"] = (c / df["ema_trend"] - 1) * 100
    f["ema50_slope"] = (df["ema_slow"] / df["ema_slow"].shift(10) - 1) * 100

    hour = df.index.hour
    f["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    atr_rank = f["atr_pct"].rolling(500).rank(pct=True)
    f["regime_volatile"] = (atr_rank >= 0.8).astype(float)
    f["regime_trending"] = ((f["adx"] > 25) & (f["regime_volatile"] == 0)).astype(float)
    f.loc[atr_rank.isna(), ["regime_volatile", "regime_trending"]] = np.nan

    for n in (1, 6, 24, 72):
        f[f"ret_{n}"] = (c / c.shift(n) - 1) * 100
    f["dd_24h"] = (c / df["high"].rolling(24).max() - 1) * 100
    f["atr_ratio"] = df["atr"] / atr(df, 100)

    f = pd.concat([f, _htf_features(df), _btc_features(df if btc is None else btc, df)], axis=1)
    return f[FEATURES]
