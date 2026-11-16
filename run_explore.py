import sys

import pandas as pd

from bot.config import Config
from bot.data import load_all, resample_ohlc
from bot.metrics import check_thresholds, compute_metrics, oos_ratio, print_checks, tstat
from bot.variants import VARIANTS, backtest_variant

sys.stdout.reconfigure(encoding="utf-8")

MIN_IS_TRADES = 100


def line(name: str, m: dict) -> str:
    return (f"{name:<32}{m['trades']:>6}{m['win_rate_pct']:>8.1f}%{m['avg_win_pct']:>+8.2f}%"
            f"{m['avg_loss_pct']:>+8.2f}%{m['expectancy_pct']:>+10.3f}%{m['profit_factor']:>7.2f}"
            f"{m['max_drawdown_pct']:>8.1f}%")


def main() -> None:
    tf = sys.argv[1] if len(sys.argv) > 1 else "1h"
    cfg = Config()
    hourly, end_time = load_all(cfg)
    data = {sym: resample_ohlc(df, tf) for sym, df in hourly.items()}
    split_time = cfg.split_time(end_time)
    print(f"Khung {tf}, {len(data)} coin, in-sample tới {split_time:%Y-%m-%d}\n")

    results = {}
    for v in VARIANTS:
        parts = []
        for sym, df in data.items():
            t = backtest_variant(df, cfg, v)
            if not t.empty:
                t.insert(0, "symbol", sym)
                parts.append(t)
        results[v.name] = pd.concat(parts, ignore_index=True)

    head = f"{'Biến thể':<32}{'Lệnh':>6}{'Thắng':>9}{'Lời TB':>9}{'Lỗ TB':>9}{'Expect.':>11}{'PF':>7}{'MaxDD':>9}"
    print("IN-SAMPLE (dùng để chọn):")
    print(head)
    is_m = {}
    for v in VARIANTS:
        t = results[v.name]
        is_m[v.name] = compute_metrics(t[t["entry_time"] < split_time])
        print(line(v.name, is_m[v.name]))
    for v in VARIANTS:
        print(f"  {v.name[:2]}: {v.exit.label()}")

    ok = {k: m for k, m in is_m.items() if m["trades"] >= MIN_IS_TRADES}
    best = max(ok, key=lambda k: ok[k]["expectancy_pct"])
    print(f"\n=> Chọn theo expectancy in-sample (≥ {MIN_IS_TRADES} lệnh): {best}")

    t = results[best]
    oos_t = t[t["entry_time"] >= split_time]
    oos_m = compute_metrics(oos_t)
    print("\nOUT-OF-SAMPLE (chỉ biến thể đã chọn):")
    print(head)
    print(line(best + " — IS", is_m[best]))
    print(line(best + " — OOS", oos_m))

    print("\nTheo năm (toàn bộ thời gian):")
    yearly = t.groupby(t["entry_time"].dt.year)
    for y, g in yearly:
        m = compute_metrics(g)
        print(f"  {y}: {m['trades']:>5} lệnh, thắng {m['win_rate_pct']:5.1f}%, "
              f"expectancy {m['expectancy_pct']:+.3f}%, PF {m['profit_factor']:.2f}")

    print(f"\nt-stat expectancy out-of-sample: {tstat(oos_t['return_pct']):.2f}  (≥ 2 mới đáng tin)")

    ratio = oos_ratio(is_m[best], oos_m)
    print(f"OOS/IS expectancy: {ratio:.0%}")
    print("\nKiểm tra ngưỡng (out-of-sample):")
    checks = check_thresholds(oos_m, ratio)
    print_checks(checks)
    print("\n=> " + ("Đủ điều kiện sang bước tiếp theo." if all(checks.values()) else "Chưa đủ điều kiện."))

    t.to_csv(f"{cfg.data_dir}/trades_explore_best_{tf}.csv", index=False)


if __name__ == "__main__":
    main()
