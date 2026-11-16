from dataclasses import dataclass

import numpy as np

from .labeling import BarrierResult, triple_barrier


@dataclass(frozen=True)
class ExitRule:
    kind: str
    sl_atr: float
    max_bars: int
    tp_atr: float = 0.0
    trail_atr: float = 0.0

    def label(self) -> str:
        if self.kind == "barrier":
            return f"TP {self.tp_atr:g}×ATR / SL {self.sl_atr:g}×ATR / {self.max_bars} nến"
        return f"Trailing {self.trail_atr:g}×ATR, SL đầu {self.sl_atr:g}×ATR, tối đa {self.max_bars} nến"


def barrier(tp_atr: float, sl_atr: float, max_bars: int) -> ExitRule:
    return ExitRule("barrier", sl_atr=sl_atr, max_bars=max_bars, tp_atr=tp_atr)


def trail(sl_atr: float, trail_atr: float, max_bars: int) -> ExitRule:
    return ExitRule("trail", sl_atr=sl_atr, max_bars=max_bars, trail_atr=trail_atr)


def trailing_stop(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    entry_idx: int, entry_price: float, atr_value: float,
    sl_atr: float, trail_atr: float, max_bars: int,
) -> BarrierResult | None:
    stop = entry_price - sl_atr * atr_value
    hh = -np.inf
    last = entry_idx + max_bars - 1
    incomplete = last >= len(c)
    for j in range(entry_idx, min(last, len(c) - 1) + 1):
        if o[j] <= stop:
            return BarrierResult(j, float(o[j]), "stop")
        if l[j] <= stop:
            return BarrierResult(j, stop, "stop")
        hh = max(hh, h[j])
        stop = max(stop, hh - trail_atr * atr_value)
    if incomplete:
        return None
    return BarrierResult(last, float(c[last]), "time")


def apply_exit(rule: ExitRule, o, h, l, c, entry_idx, entry_price, atr_value) -> BarrierResult | None:
    if rule.kind == "barrier":
        return triple_barrier(h, l, c, entry_idx, entry_price, atr_value,
                              rule.tp_atr, rule.sl_atr, rule.max_bars)
    if rule.kind == "trail":
        return trailing_stop(o, h, l, c, entry_idx, entry_price, atr_value,
                             rule.sl_atr, rule.trail_atr, rule.max_bars)
    raise ValueError(rule.kind)
