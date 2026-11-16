import sys
from dataclasses import replace
from datetime import date

import pandas as pd

from bot.config import Config
from bot.intraday import TRADE_COLUMNS, VARIANTS, backtest, prepare
from bot.metrics import check_thresholds, compute_metrics, oos_ratio, print_checks, tstat
from bot.minute_data import gaps, load_minutes
from run_explore import line

sys.stdout.reconfigure(encoding="utf-8")

SYMBOLS = ["ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "BTCUSDT"]
START, END = date(2024, 11, 14), date(2026, 11, 13)
MIN_IS_TRADES = 100
HEAD = f"{'Biến thể':<32}{'Lệnh':>6}{'Thắng':>9}{'Lời TB':>9}{'Lỗ TB':>9}{'Expect.':>11}{'PF':>7}{'MaxDD':>9}"


def run(v, minutes: dict, prepared: dict, use_regime: bool = True) -> pd.DataFrame:
    parts = []
    for s in SYMBOLS:
        t = backtest(minutes[s], prepared[s], v, use_regime)
        if not t.empty:
            parts.append(t.assign(symbol=s))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["symbol", *TRADE_COLUMNS])


def main() -> None:
    cfg = replace(Config(), start=START.isoformat())
    minutes = {}
    for s in SYMBOLS:
        m = load_minutes(s, START, END, f"{cfg.data_dir}/1m")
        g = gaps(m)
        minutes[s] = m
        print(f"{s:<9}{len(m):>9} nến 1m  {m.index[0]:%Y-%m-%d} → {m.index[-1]:%Y-%m-%d}  "
              f"chỗ trống > 5 phút: {len(g)}" + (f" (lớn nhất {g['missing_minutes'].max()} phút)" if len(g) else ""))
    prepared = {s: prepare(m, minutes["BTCUSDT"]) for s, m in minutes.items()}
    split = cfg.split_time(max(m.index[-1] for m in minutes.values()))
    print(f"\nIn-sample tới {split:%Y-%m-%d}, out-of-sample sau đó. Phí 0,1 %/chiều + trượt giá 5 bps/chiều.\n")

    results = {v.name: run(v, minutes, prepared) for v in VARIANTS}
    print("IN-SAMPLE (dùng để chọn):")
    print(HEAD)
    is_m = {}
    for name, t in results.items():
        is_m[name] = compute_metrics(t[t["entry_time"] < split])
        print(line(name, is_m[name]))
    ok = {k: m for k, m in is_m.items() if m["trades"] >= MIN_IS_TRADES}
    if not ok:
        print(f"\n=> Không biến thể nào có ≥ {MIN_IS_TRADES} lệnh in-sample → KHÔNG ĐẠT. Không chạy lướt sóng.")
        return
    best = max(ok, key=lambda k: ok[k]["expectancy_pct"])
    v = next(x for x in VARIANTS if x.name == best)
    print(f"\n=> Chọn theo lãi TB in-sample: {best}")

    t = results[best]
    oos_t = t[t["entry_time"] >= split]
    oos_m = compute_metrics(oos_t)
    print("\nOUT-OF-SAMPLE (chỉ biến thể đã chọn):")
    print(HEAD)
    print(line(best + " — IS", is_m[best]))
    print(line(best + " — OOS", oos_m))

    raw = run(v, minutes, prepared, use_regime=False)
    print(line("(không lọc thị trường) — OOS", compute_metrics(raw[raw["entry_time"] >= split])))

    print("\nTheo tháng (cả giai đoạn):")
    for month, g in t.groupby(t["entry_time"].dt.strftime("%Y-%m")):
        print(f"  {month}{' OOS' if g['entry_time'].iloc[0] >= split else '    '} {len(g):>5} lệnh  "
              f"lãi TB {g['return_pct'].mean():+.3f}%  tổng {g['return_pct'].sum():+.2f}%")
    print("\nTheo coin (out-of-sample):")
    for s, g in oos_t.groupby("symbol"):
        m = compute_metrics(g)
        print(f"  {s:<9}{m['trades']:>5} lệnh  thắng {m['win_rate_pct']:5.1f}%  lãi TB {m['expectancy_pct']:+.3f}%"
              f"  PF {m['profit_factor']:.2f}")

    ts = tstat(oos_t["return_pct"])
    ratio = oos_ratio(is_m[best], oos_m)
    print(f"\nt-stat out-of-sample: {ts:.2f}  |  OOS/IS: {ratio:.0%}")
    checks = check_thresholds(oos_m, ratio)
    checks["t-stat >= 2"] = ts >= 2
    print("\nKiểm tra ngưỡng (out-of-sample):")
    print_checks(checks)
    passed = all(checks.values())
    print("\n=> " + ("ĐẠT — được làm giai đoạn 2 (chạy trên giấy rồi testnet)." if passed
                     else "KHÔNG ĐẠT — không chạy lướt sóng."))
    t.to_csv(f"{cfg.data_dir}/trades_intraday_{v.entry}_{v.exit}.csv", index=False)


if __name__ == "__main__":
    main()
