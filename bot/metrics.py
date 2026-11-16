import math

import numpy as np
import pandas as pd

from .config import THRESHOLDS


def net_return(entry_price: float, exit_price: float, fee: float) -> float:
    return (exit_price * (1 - fee)) / (entry_price * (1 + fee)) - 1


def tstat(returns: pd.Series) -> float:
    r = returns
    return r.mean() / (r.std() / len(r) ** 0.5) if len(r) > 1 else 0.0


def portfolio_equity(trades: pd.DataFrame) -> pd.Series:
    t = trades.copy()
    if "symbol" not in t:
        t["symbol"] = "_"
    if "exit_time" not in t:
        t["exit_time"] = np.arange(len(t))
    curves = []
    for sym, g in t.sort_values("exit_time").groupby("symbol", sort=False):
        eq = (1 + g["return_pct"].to_numpy() / 100).cumprod()
        curves.append(pd.Series(eq, index=g["exit_time"].to_numpy(), name=sym))
    combined = pd.concat(curves, axis=1).sort_index().ffill().fillna(1.0)
    combined = combined.groupby(level=0).last()
    return combined.mean(axis=1)


def max_drawdown(equity: pd.Series) -> float:
    eq = np.concatenate([[1.0], equity.to_numpy()])
    peak = np.maximum.accumulate(eq)
    return float((1 - eq / peak).max())


def compute_metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "win_rate_pct": 0.0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
                "expectancy_pct": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 0.0,
                "total_return_pct": 0.0}
    r = trades["return_pct"].to_numpy() / 100
    wins, losses = r[r > 0], r[r <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    equity = portfolio_equity(trades)
    return {
        "trades": len(r),
        "win_rate_pct": len(wins) / len(r) * 100,
        "avg_win_pct": wins.mean() * 100 if len(wins) else 0.0,
        "avg_loss_pct": losses.mean() * 100 if len(losses) else 0.0,
        "expectancy_pct": r.mean() * 100,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else math.inf,
        "max_drawdown_pct": max_drawdown(equity) * 100,
        "total_return_pct": (equity.iloc[-1] - 1) * 100,
    }


def oos_ratio(is_m: dict, oos_m: dict) -> float:
    if is_m["expectancy_pct"] <= 0:
        return 0.0
    return oos_m["expectancy_pct"] / is_m["expectancy_pct"]


def print_checks(checks: dict[str, bool]) -> None:
    for name, ok in checks.items():
        print(f"  [{'ĐẠT' if ok else 'TRƯỢT'}] {name}")


def check_thresholds(m: dict, ratio: float) -> dict[str, bool]:
    t = THRESHOLDS
    return {
        "Expectancy sau phí > 0": m["expectancy_pct"] > t["expectancy_pct"],
        "Profit factor > 1,3": m["profit_factor"] > t["profit_factor"],
        "Max drawdown < 20 %": m["max_drawdown_pct"] < t["max_drawdown_pct"],
        "OOS/IS >= 70 %": ratio >= t["oos_ratio"],
        "Số lệnh >= 100": m["trades"] >= t["min_trades"],
    }
