"""Hằng số và tiện ích dùng chung cho Claude tự giao dịch, lệnh tay Telegram và watcher lệnh khớp."""
from __future__ import annotations

from datetime import datetime, timezone

PUBLIC_API = "https://data-api.binance.vision/api/v3"

SYMBOLS: tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT",
    "DOTUSDT", "TRXUSDT", "ATOMUSDT", "UNIUSDT", "ETCUSDT",
    "BCHUSDT", "XLMUSDT", "FILUSDT", "NEARUSDT", "ALGOUSDT",
    "VETUSDT", "ICPUSDT", "AAVEUSDT", "SANDUSDT", "MANAUSDT",
    "AXSUSDT", "HBARUSDT", "INJUSDT", "GRTUSDT", "EOSUSDT",
)
UNSUPPORTED = {"EOSUSDT"}  # không giao dịch được trên testnet


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
