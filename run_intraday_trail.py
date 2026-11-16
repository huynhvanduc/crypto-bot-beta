import sys

import numpy as np
import pandas as pd

from bot.config import Config
from bot.data import load_all, resample_ohlc
from bot.metrics import compute_metrics, net_return, tstat
from bot.strategy import add_indicators
from bot.variants import D1

sys.stdout.reconfigure(encoding="utf-8")

RULE = D1.exit
MODES = {"Gốc (nâng 1 lần/ngày)": 24, "Nâng mỗi 4h": 4, "Nâng mỗi 1h": 1}


def simulate(h1: pd.DataFrame, entry_t: pd.Timestamp, atr: float, every_h: int):
    end_t = entry_t + pd.Timedelta(days=RULE.max_bars)
    seg = h1.loc[entry_t:end_t - pd.Timedelta(hours=1)]
    if seg.empty:
        return None
    o, h, l, c = (seg[k].to_numpy() for k in ["open", "high", "low", "close"])
    entry = o[0]
    stop = entry - RULE.sl_atr * atr
    hh = -np.inf
    hours = ((seg.index - entry_t) / pd.Timedelta(hours=1)).astype(int).to_numpy()
    for j in range(len(seg)):
        if o[j] <= stop:
            return seg.index[j], float(o[j]), "stop"
        if l[j] <= stop:
            return seg.index[j], stop, "stop"
        hh = max(hh, h[j])
        if (hours[j] + 1) % every_h == 0:
            stop = max(stop, hh - RULE.trail_atr * atr)
    if seg.index[-1] < end_t - pd.Timedelta(hours=1):
        return None
    return seg.index[-1], float(c[-1]), "time"


def backtest(h1: pd.DataFrame, cfg: Config, every_h: int) -> pd.DataFrame:
    d = add_indicators(resample_ohlc(h1, "1d"), cfg)
    sig = D1.signals(d, cfg).to_numpy()
    times, atr = d.index, d["atr"].to_numpy()
    trades, free_after = [], None
    for i in np.flatnonzero(sig):
        if i + 1 >= len(d):
            break
        if free_after is not None and times[i] <= free_after:
            continue
        entry_t = times[i + 1]
        res = simulate(h1, entry_t, atr[i], every_h)
        if res is None:
            break
        exit_t, exit_px, why = res
        entry = float(h1.loc[entry_t, "open"])
        ret = net_return(entry, exit_px, cfg.fee)
        trades.append({"entry_time": entry_t, "exit_time": exit_t, "entry_price": entry, "exit_price": exit_px,
                       "barrier": why, "days_held": (exit_t - entry_t) / pd.Timedelta(days=1),
                       "return_pct": ret * 100, "win": ret > 0})
        free_after = exit_t.floor("1D")
    return pd.DataFrame(trades)


def main() -> None:
    cfg = Config()
    data, end_time = load_all(cfg)
    split = cfg.split_time(end_time)
    print(f"{len(data)} coin, in-sample tới {split:%Y-%m-%d}, out-of-sample tới {end_time:%Y-%m-%d}\n")

    head = f"{'':<26}{'Lệnh':>6}{'Thắng':>8}{'Lời TB':>9}{'Lỗ TB':>8}{'Expect.':>10}{'PF':>6}{'MaxDD':>8}{'Ngày giữ':>10}{'t':>7}"
    rows = {}
    for name, every in MODES.items():
        parts = []
        for sym, h1 in data.items():
            t = backtest(h1, cfg, every)
            if not t.empty:
                t.insert(0, "symbol", sym)
                parts.append(t)
        rows[name] = pd.concat(parts, ignore_index=True)

    for label, sel in [("IN-SAMPLE", lambda t: t["entry_time"] < split), ("OUT-OF-SAMPLE", lambda t: t["entry_time"] >= split)]:
        print(label)
        print(head)
        for name, t in rows.items():
            s = t[sel(t)]
            m = compute_metrics(s)
            ts = tstat(s["return_pct"])
            print(f"{name:<26}{m['trades']:>6}{m['win_rate_pct']:>7.1f}%{m['avg_win_pct']:>+8.2f}%{m['avg_loss_pct']:>+7.2f}%"
                  f"{m['expectancy_pct']:>+9.3f}%{m['profit_factor']:>6.2f}{m['max_drawdown_pct']:>7.1f}%"
                  f"{s['days_held'].mean():>10.1f}{ts:>7.2f}")
        print()

    base = rows["Gốc (nâng 1 lần/ngày)"]
    print("Theo năm — expectancy %/lệnh (số lệnh):")
    print(f"{'Năm':<6}" + "".join(f"{n:>26}" for n in rows))
    for y in sorted(base["entry_time"].dt.year.unique()):
        cells = []
        for t in rows.values():
            g = t[t["entry_time"].dt.year == y]
            cells.append(f"{g['return_pct'].mean():+.2f}% ({len(g)})" if len(g) else "—")
        print(f"{y:<6}" + "".join(f"{c:>26}" for c in cells))

    for name in list(MODES)[1:]:
        m = base.merge(rows[name], on=["symbol", "entry_time"], suffixes=("_g", "_n"))
        diff = m["return_pct_n"] - m["return_pct_g"]
        print(f"\n{name} vs gốc, {len(m)} lệnh cùng điểm vào: tốt hơn {(diff > 0.01).mean():.0%}, "
              f"kém hơn {(diff < -0.01).mean():.0%}, chênh TB {diff.mean():+.2f}%/lệnh; "
              f"lệnh lời >20% ở bản gốc: chênh TB {diff[m['return_pct_g'] > 20].mean():+.2f}%")


if __name__ == "__main__":
    main()
