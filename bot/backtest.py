import numpy as np
import pandas as pd

from .config import Config
from .features import FEATURES, compute_features
from .labeling import triple_barrier
from .metrics import net_return
from .strategy import add_indicators, generate_signals


def build_candidates(df: pd.DataFrame, cfg: Config, btc: pd.DataFrame | None = None) -> pd.DataFrame:
    df = add_indicators(df, cfg)
    feats = compute_features(df, btc)
    signals = generate_signals(df, cfg).to_numpy()

    o, h, l, c, a = (df[k].to_numpy() for k in ["open", "high", "low", "close", "atr"])
    times = df.index
    fvals = feats[FEATURES].to_numpy()

    rows = []
    for i in np.flatnonzero(signals):
        entry_idx = i + 1
        if entry_idx >= len(df):
            break
        entry = o[entry_idx]
        res = triple_barrier(h, l, c, entry_idx, entry, a[i], cfg.tp_atr, cfg.sl_atr, cfg.max_bars)
        if res is None:
            break
        ret = net_return(entry, res.exit_price, cfg.fee)
        row = {
            "signal_time": times[i],
            "entry_time": times[entry_idx],
            "exit_time": times[res.exit_idx],
            "entry_price": entry,
            "exit_price": res.exit_price,
            "atr": a[i],
            "barrier": res.barrier,
            "bars_held": res.exit_idx - entry_idx + 1,
            "return_pct": ret * 100,
            "win": ret > 0,
        }
        row.update(zip(FEATURES, fvals[i]))
        rows.append(row)
    return pd.DataFrame(rows)


def signal_features(df: pd.DataFrame, cfg: Config, btc: pd.DataFrame | None = None) -> pd.DataFrame:
    df = add_indicators(df, cfg)
    feats = compute_features(df, btc)
    sig = generate_signals(df, cfg)
    out = feats[sig].copy()
    out.insert(0, "close", df.loc[sig, "close"])
    out.insert(1, "atr", df.loc[sig, "atr"])
    out.index.name = "signal_time"
    return out.reset_index()


def simulate(cands: pd.DataFrame, take: np.ndarray | None = None) -> pd.DataFrame:
    if cands.empty:
        return cands
    c = cands.copy()
    c["_take"] = True if take is None else np.asarray(take, bool)
    c["_sym"] = c["symbol"] if "symbol" in c else "_"
    c = c.sort_values("signal_time", kind="stable")

    keep = []
    last_exit: dict = {}
    for idx, sym, st, et, tk in zip(c.index, c["_sym"], c["signal_time"], c["exit_time"], c["_take"]):
        if not tk:
            continue
        if sym in last_exit and st <= last_exit[sym]:
            continue
        keep.append(idx)
        last_exit[sym] = et
    return c.loc[keep].drop(columns=["_take", "_sym"]).reset_index(drop=True)


def run_backtest(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    return simulate(build_candidates(df, cfg))
