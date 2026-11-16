from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Config
from .metrics import net_return
from .strategy import add_indicators
from .variants import Variant


@dataclass
class OpenPosition:
    entry_time: pd.Timestamp
    entry_price: float
    atr: float
    stop: float
    bars_held: int
    last_close: float

    @property
    def unrealized_pct(self) -> float:
        return (self.last_close / self.entry_price - 1) * 100


@dataclass
class PaperResult:
    trades: pd.DataFrame
    position: OpenPosition | None
    pending_signal: pd.Timestamp | None
    last_bar: pd.Timestamp | None = None
    extra: dict = field(default_factory=dict)


def run_paper(df: pd.DataFrame, cfg: Config, v: Variant, start: pd.Timestamp,
              btc_ok: pd.Series | None = None) -> PaperResult:
    rule = v.exit
    assert rule.kind == "trail", "paper trading chỉ hỗ trợ trailing stop"
    df = add_indicators(df, cfg)
    sig = v.signals(df, cfg, btc_ok).to_numpy()
    o, h, l, c, a = (df[k].to_numpy() for k in ["open", "high", "low", "close", "atr"])
    times = df.index
    eligible = times >= start

    trades = []
    pos = None
    last_exit = -1
    for j in range(len(df)):
        if pos is None and j >= 1 and sig[j - 1] and eligible[j - 1] and j - 1 > last_exit:
            atr0 = a[j - 1]
            pos = {"entry_idx": j, "entry": o[j], "atr": atr0, "hh": -np.inf,
                   "stop": o[j] - rule.sl_atr * atr0, "signal_idx": j - 1}
        if pos is None:
            continue

        exit_price, kind = None, None
        if o[j] <= pos["stop"]:
            exit_price, kind = o[j], "stop"
        elif l[j] <= pos["stop"]:
            exit_price, kind = pos["stop"], "stop"
        else:
            pos["hh"] = max(pos["hh"], h[j])
            pos["stop"] = max(pos["stop"], pos["hh"] - rule.trail_atr * pos["atr"])
            if j - pos["entry_idx"] + 1 >= rule.max_bars:
                exit_price, kind = c[j], "time"

        if exit_price is not None:
            ret = net_return(pos["entry"], exit_price, cfg.fee)
            trades.append({
                "signal_time": times[pos["signal_idx"]], "entry_time": times[pos["entry_idx"]],
                "exit_time": times[j], "entry_price": pos["entry"], "exit_price": float(exit_price),
                "barrier": kind, "bars_held": j - pos["entry_idx"] + 1,
                "return_pct": ret * 100, "win": ret > 0,
            })
            last_exit = j
            pos = None

    open_pos = None
    if pos is not None:
        open_pos = OpenPosition(times[pos["entry_idx"]], float(pos["entry"]), float(pos["atr"]),
                                float(pos["stop"]), len(df) - pos["entry_idx"], float(c[-1]))
    n = len(df) - 1
    pending = None
    if n >= 0 and pos is None and sig[n] and eligible[n] and n > last_exit:
        pending = times[n]
    return PaperResult(pd.DataFrame(trades), open_pos, pending, times[-1] if len(df) else None)
