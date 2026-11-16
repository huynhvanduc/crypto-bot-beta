from __future__ import annotations

import math

import pandas as pd

from .config import Config
from .data import load_bars
from .exits import trail as T
from .indicators import ema
from .metrics import compute_metrics
from .paper import run_paper
from .variants import Variant

CHAMPION = "★ Donchian20 · trail 3"
SHADOW_VARIANTS = [
    Variant(CHAMPION, "donchian20", T(2, 3, 240)),
    Variant("A · Donchian55 · trail 3", "donchian55", T(2, 3, 240)),
    Variant("B · Donchian20 · trail 2", "donchian20", T(1.5, 2, 120)),
    Variant("C · Donchian55 · trail 2", "donchian55", T(1.5, 2, 120)),
    Variant("D · Donchian20 · trail 3 · lọc BTC", "donchian20", T(2, 3, 240), btc_filter=True),
]
MIN_TRADES = 30
REFERENCE_START = pd.Timestamp("2024-10-22", tz="UTC")


def btc_regime(btc_daily: pd.DataFrame) -> pd.Series:
    return btc_daily["close"] > ema(btc_daily["close"], 200)


def _run(v: Variant, bars: dict[str, pd.DataFrame], cfg: Config, start: pd.Timestamp, btc_ok: pd.Series) -> dict:
    trades, opens = [], []
    slot = 1.0 / len(bars)
    equity = 0.0
    for sym, df in bars.items():
        res = run_paper(df, cfg, v, start, btc_ok)
        coin_eq = 1.0
        if not res.trades.empty:
            trades.append(res.trades.assign(symbol=sym))
            coin_eq = float((1 + res.trades["return_pct"] / 100).prod())
        if res.position:
            opens.append(sym)
            coin_eq *= res.position.last_close / res.position.entry_price * (1 - cfg.fee)
        equity += slot * coin_eq
    t = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    m = compute_metrics(t) if not t.empty else None
    return {"trades": t, "metrics": m, "open": opens, "return_pct": (equity - 1) * 100}


def _tstat_diff(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else 0.0


def run_shadow(cfg: Config, symbols: list[str], start: pd.Timestamp) -> list[dict]:
    bars = {s: load_bars(s, cfg, "1d") for s in symbols}
    btc_ok = btc_regime(bars["BTCUSDT"] if "BTCUSDT" in bars else load_bars("BTCUSDT", cfg, "1d"))

    out, champ_ret = [], None
    for v in SHADOW_VARIANTS:
        fwd = _run(v, bars, cfg, start, btc_ok)
        ref = _run(v, bars, cfg, REFERENCE_START, btc_ok)
        fm, rm = fwd["metrics"] or {}, ref["metrics"] or {}
        row = {
            "name": v.name, "champion": v.name == CHAMPION,
            "trades": fm.get("trades", 0), "win_rate_pct": fm.get("win_rate_pct"),
            "expectancy_pct": fm.get("expectancy_pct"),
            "return_pct": fwd["return_pct"], "open": len(fwd["open"]),
            "ref_expectancy_pct": rm.get("expectancy_pct"),
            "ref_return_pct": ref["return_pct"],
        }
        rets = fwd["trades"]["return_pct"] if not fwd["trades"].empty else pd.Series(dtype=float)
        if v.name == CHAMPION:
            champ_ret = rets
            row["verdict"] = "đang chạy thật"
        else:
            n, nc = len(rets), len(champ_ret)
            t = _tstat_diff(rets, champ_ret)
            if n < MIN_TRADES or nc < MIN_TRADES:
                row["verdict"] = f"chưa đủ lệnh ({min(n, nc)}/{MIN_TRADES})"
            elif t >= 2:
                row["verdict"] = f"TỐT HƠN rõ rệt (t={t:.1f}) — cân nhắc thay"
            elif t <= -2:
                row["verdict"] = f"kém hơn rõ rệt (t={t:.1f})"
            else:
                row["verdict"] = f"chưa khác biệt (t={t:.1f})"
        out.append(row)
    return out
