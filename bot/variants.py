from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .exits import ExitRule, apply_exit
from .exits import barrier as B
from .exits import trail as T
from .metrics import net_return
from .strategy import add_indicators, generate_signals


def pullback_signals(df: pd.DataFrame, cfg: Config) -> pd.Series:
    return generate_signals(df, cfg)


def donchian_signals(df: pd.DataFrame, n: int) -> pd.Series:
    prior_high = df["high"].shift(1).rolling(n).max()
    sig = (df["close"] > prior_high) & (df["close"] > df["ema_trend"]) & df["atr"].notna()
    return sig.fillna(False)


@dataclass(frozen=True)
class Variant:
    name: str
    entry: str
    exit: ExitRule
    btc_filter: bool = False

    def signals(self, df: pd.DataFrame, cfg: Config, btc_ok: pd.Series | None = None) -> pd.Series:
        if self.entry == "pullback":
            sig = pullback_signals(df, cfg)
        elif self.entry.startswith("donchian"):
            sig = donchian_signals(df, int(self.entry[len("donchian"):]))
        else:
            raise ValueError(self.entry)
        if self.btc_filter:
            if btc_ok is None:
                raise ValueError("biến thể có bộ lọc BTC cần btc_ok")
            sig = sig & btc_ok.reindex(df.index).fillna(False).astype(bool)
        return sig


def backtest_variant(df: pd.DataFrame, cfg: Config, v: Variant) -> pd.DataFrame:
    df = add_indicators(df, cfg)
    sig = v.signals(df, cfg).to_numpy()
    o, h, l, c, a = (df[k].to_numpy() for k in ["open", "high", "low", "close", "atr"])
    times = df.index
    trades, busy_until = [], -1
    for i in np.flatnonzero(sig):
        if i <= busy_until:
            continue
        entry_idx = i + 1
        if entry_idx >= len(df):
            break
        entry = o[entry_idx]
        res = apply_exit(v.exit, o, h, l, c, entry_idx, entry, a[i])
        if res is None:
            break
        ret = net_return(entry, res.exit_price, cfg.fee)
        trades.append({
            "signal_time": times[i], "entry_time": times[entry_idx], "exit_time": times[res.exit_idx],
            "entry_price": entry, "exit_price": res.exit_price, "barrier": res.barrier,
            "bars_held": res.exit_idx - entry_idx + 1, "return_pct": ret * 100, "win": ret > 0,
        })
        busy_until = res.exit_idx
    return pd.DataFrame(trades)


VARIANTS = [
    Variant("P0 Pullback (gốc)", "pullback", B(2, 1, 24)),
    Variant("P1 Pullback, giữ lâu hơn", "pullback", B(2, 1, 72)),
    Variant("P2 Pullback, TP xa", "pullback", B(3, 1, 72)),
    Variant("P3 Pullback, trailing chặt", "pullback", T(1.5, 2, 120)),
    Variant("P4 Pullback, trailing rộng", "pullback", T(2, 3, 240)),
    Variant("D1 Donchian20, trailing rộng", "donchian20", T(2, 3, 240)),
    Variant("D2 Donchian55, trailing rộng", "donchian55", T(2, 3, 240)),
    Variant("D3 Donchian20, TP/SL", "donchian20", B(3, 1.5, 72)),
    Variant("D4 Donchian55, TP/SL", "donchian55", B(3, 1.5, 72)),
    Variant("D5 Donchian20, trailing chặt", "donchian20", T(1.5, 2, 120)),
    Variant("D6 Donchian55, trailing chặt", "donchian55", T(1.5, 2, 120)),
]
D1 = next(v for v in VARIANTS if v.name.startswith("D1"))
