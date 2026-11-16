from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Config:
    symbols: tuple[str, ...] = (
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT",
        "DOTUSDT", "TRXUSDT", "ATOMUSDT", "UNIUSDT", "ETCUSDT",
        "BCHUSDT", "XLMUSDT", "FILUSDT", "NEARUSDT", "ALGOUSDT",
        "VETUSDT", "ICPUSDT", "AAVEUSDT", "SANDUSDT", "MANAUSDT",
        "AXSUSDT", "HBARUSDT", "INJUSDT", "GRTUSDT", "EOSUSDT",
    )
    interval: str = "1h"
    start: str = "2020-01-01"
    data_dir: str = "data"

    ema_trend: int = 200
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_trigger: float = 40.0

    atr_period: int = 14
    tp_atr: float = 2.0
    sl_atr: float = 1.0
    max_bars: int = 24

    fee: float = 0.001

    in_sample_frac: float = 0.7

    def split_time(self, end_time: pd.Timestamp) -> pd.Timestamp:
        start = pd.Timestamp(self.start, tz="UTC")
        return start + (end_time - start) * self.in_sample_frac


THRESHOLDS = {
    "expectancy_pct": 0.0,
    "profit_factor": 1.3,
    "max_drawdown_pct": 20.0,
    "oos_ratio": 0.70,
    "min_trades": 100,
}
