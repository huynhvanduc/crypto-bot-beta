from dataclasses import dataclass

import numpy as np


@dataclass
class BarrierResult:
    exit_idx: int
    exit_price: float
    barrier: str


def triple_barrier(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    entry_idx: int,
    entry_price: float,
    atr_value: float,
    tp_atr: float = 2.0,
    sl_atr: float = 1.0,
    max_bars: int = 24,
) -> BarrierResult | None:
    tp = entry_price + tp_atr * atr_value
    sl = entry_price - sl_atr * atr_value
    last = entry_idx + max_bars - 1
    incomplete = last >= len(close)
    last = min(last, len(close) - 1)

    for j in range(entry_idx, last + 1):
        if low[j] <= sl:
            return BarrierResult(j, sl, "sl")
        if high[j] >= tp:
            return BarrierResult(j, tp, "tp")

    if incomplete:
        return None
    return BarrierResult(last, float(close[last]), "time")
