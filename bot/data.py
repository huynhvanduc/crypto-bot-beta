from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

PUBLIC_API = "https://data-api.binance.vision/api/v3"
BASE_URL = f"{PUBLIC_API}/klines"
LIMIT = 1000
COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def _fetch_batch(symbol: str, interval: str, start_ms: int) -> list:
    for attempt in range(5):
        try:
            r = requests.get(
                BASE_URL,
                params={"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": LIMIT},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    return []


def fetch_klines(symbol: str, interval: str, start_ms: int) -> pd.DataFrame:
    rows: list = []
    cursor = start_ms
    while True:
        batch = _fetch_batch(symbol, interval, cursor)
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < LIMIT:
            break
        time.sleep(0.2)
    df = pd.DataFrame([r[:7] for r in rows], columns=COLUMNS)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    df["close_time"] = df["close_time"].astype("int64")
    return df


RULES = {"1h": ("1h", 1), "4h": ("4h", 4), "1d": ("1D", 24)}


def resample_ohlc(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    rule, hours = RULES[interval]
    if hours == 1:
        return df
    g = df[["open", "high", "low", "close", "volume"]].resample(rule, label="left", closed="left")
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out[g["close"].count() == hours]


def load_klines(symbol: str, interval: str, start: str, data_dir: str = "data") -> pd.DataFrame:
    path = Path(data_dir) / f"{symbol}_{interval}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        df = pd.read_csv(path)
        start_ms = int(df["open_time"].iloc[-1]) + 1
    else:
        df = pd.DataFrame(columns=COLUMNS)
        start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)

    new = fetch_klines(symbol, interval, start_ms)
    if not new.empty:
        df = new if df.empty else pd.concat([df, new], ignore_index=True)
        df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)

    now_ms = int(time.time() * 1000)
    df = df[df["close_time"] < now_ms].reset_index(drop=True)
    df.to_csv(path, index=False)

    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.index.name = "time"
    return df


def load_bars(symbol: str, cfg, interval: str = "1h") -> pd.DataFrame:
    return resample_ohlc(load_klines(symbol, cfg.interval, cfg.start, cfg.data_dir), interval)


def load_all(cfg) -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    data = {s: load_bars(s, cfg) for s in cfg.symbols}
    return data, max(df.index[-1] for df in data.values())
