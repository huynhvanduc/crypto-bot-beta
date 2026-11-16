import pandas as pd

from .config import Config
from .indicators import atr, ema, rsi


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    df = df.copy()
    df["ema_trend"] = ema(df["close"], cfg.ema_trend)
    df["ema_fast"] = ema(df["close"], cfg.ema_fast)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow)
    df["rsi"] = rsi(df["close"], cfg.rsi_period)
    df["atr"] = atr(df, cfg.atr_period)
    return df


def generate_signals(df: pd.DataFrame, cfg: Config) -> pd.Series:
    uptrend = (df["close"] > df["ema_trend"]) & (df["ema_fast"] > df["ema_slow"])
    rsi_cross = (df["rsi"].shift(1) < cfg.rsi_trigger) & (df["rsi"] >= cfg.rsi_trigger)
    valid = df[["ema_trend", "ema_fast", "ema_slow", "rsi", "atr"]].notna().all(axis=1)
    return (uptrend & rsi_cross & valid).fillna(False)
