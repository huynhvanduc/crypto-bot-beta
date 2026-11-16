from __future__ import annotations

import io
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/spot"
COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
           "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
VALUES = ["open", "high", "low", "close", "volume", "taker_buy_volume"]


class MissingData(RuntimeError):
    pass


def to_ms(values: pd.Series) -> pd.Series:
    v = values.astype("int64")
    return v.where(v < 10**14, v // 1000)


def parse_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), header=None, names=COLUMNS, dtype=str)
    df = df[df["open_time"].str.fullmatch(r"\d+", na=False)]
    out = df[VALUES].astype(float)
    out.insert(0, "open_time", to_ms(df["open_time"]))
    return out.reset_index(drop=True)


def month_end(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def daily_periods(first: date, last: date) -> list[tuple[str, str]]:
    return [("daily", f"{first + timedelta(days=i):%Y-%m-%d}") for i in range((last - first).days + 1)]


def periods(start: date, end: date, today: date) -> list[tuple[str, str]]:
    out, m, this_month = [], start.replace(day=1), today.replace(day=1)
    while m <= end:
        if m < this_month:
            out.append(("monthly", f"{m:%Y-%m}"))
        else:
            out += daily_periods(max(m, start), min(month_end(m), end, today - timedelta(days=1)))
        m = month_end(m) + timedelta(days=1)
    return out


def cache_path(cache_dir, symbol: str, period: str) -> Path:
    return Path(cache_dir) / symbol / f"{symbol}-1m-{period}.zip"


def fetch(symbol: str, kind: str, period: str, cache_dir, get=requests.get, retries: int = 5,
          wait: float = 1.0) -> bytes | None:
    path = cache_path(cache_dir, symbol, period)
    if path.exists():
        return path.read_bytes()
    url = f"{BASE}/{kind}/klines/{symbol}/1m/{symbol}-1m-{period}.zip"
    for attempt in range(retries):
        try:
            r = get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
        except requests.RequestException:
            if attempt == retries - 1:
                raise MissingData(f"Không tải được {symbol} {period}")
            time.sleep(wait * 2 ** attempt)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return r.content
    return None


def _month_by_days(symbol: str, period: str, cache_dir, get) -> list[pd.DataFrame]:
    first = date.fromisoformat(period + "-01")
    parts = []
    for kind, day in daily_periods(first, month_end(first)):
        content = fetch(symbol, kind, day, cache_dir, get)
        if content is None:
            raise MissingData(f"Thiếu dữ liệu {symbol} {day}")
        parts.append(parse_zip(content))
    return parts


def load_minutes(symbol: str, start: date, end: date, cache_dir="data/1m", today: date | None = None,
                 get=requests.get) -> pd.DataFrame:
    today = today or datetime.now(timezone.utc).date()
    parts = []
    for kind, period in periods(start, end, today):
        by_days = (kind == "monthly" and not cache_path(cache_dir, symbol, period).exists()
                   and cache_path(cache_dir, symbol, period + "-01").exists())
        content = None if by_days else fetch(symbol, kind, period, cache_dir, get)
        if content is not None:
            parts.append(parse_zip(content))
        elif kind == "monthly":
            parts += _month_by_days(symbol, period, cache_dir, get)
        else:
            raise MissingData(f"Thiếu dữ liệu {symbol} {period}")
    df = pd.concat(parts, ignore_index=True).drop_duplicates("open_time").sort_values("open_time")
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("open_time"), unit="ms", utc=True), name="time")
    lo = pd.Timestamp(start.isoformat(), tz="UTC")
    hi = pd.Timestamp(end.isoformat(), tz="UTC") + pd.Timedelta(days=1)
    return df[(df.index >= lo) & (df.index < hi)]


def gaps(df: pd.DataFrame, limit_minutes: int = 5) -> pd.DataFrame:
    missing = df.index.to_series().diff() / pd.Timedelta(minutes=1) - 1
    big = missing[missing > limit_minutes]
    return pd.DataFrame({"after": big.index, "missing_minutes": big.astype(int).to_numpy()})
