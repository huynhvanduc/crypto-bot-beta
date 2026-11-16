import sys
from pathlib import Path

import pandas as pd

from bot.backtest import run_backtest
from bot.config import Config
from bot.data import load_all
from bot.metrics import check_thresholds, compute_metrics, oos_ratio, print_checks

sys.stdout.reconfigure(encoding="utf-8")


def fmt(m: dict) -> list[str]:
    return [
        f"{m['trades']}",
        f"{m['win_rate_pct']:.1f} %",
        f"{m['avg_win_pct']:+.2f} %",
        f"{m['avg_loss_pct']:+.2f} %",
        f"{m['expectancy_pct']:+.3f} %",
        f"{m['profit_factor']:.2f}",
        f"{m['max_drawdown_pct']:.1f} %",
        f"{m['total_return_pct']:+.1f} %",
    ]


def main() -> None:
    cfg = Config()
    data, end_time = load_all(cfg)
    all_trades = []
    for sym, df in data.items():
        print(f"{sym:<10} {len(df):>6} nến  {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}")
        tr = run_backtest(df, cfg)
        if not tr.empty:
            tr.insert(0, "symbol", sym)
            all_trades.append(tr)
    trades = pd.concat(all_trades, ignore_index=True).sort_values("entry_time", ignore_index=True)

    split_time = cfg.split_time(end_time)
    is_tr = trades[trades["entry_time"] < split_time]
    oos_tr = trades[trades["entry_time"] >= split_time]

    is_m, oos_m, all_m = compute_metrics(is_tr), compute_metrics(oos_tr), compute_metrics(trades)
    ratio = oos_ratio(is_m, oos_m)

    labels = ["Số lệnh", "Tỷ lệ thắng", "Lời TB", "Lỗ TB", "Expectancy/lệnh",
              "Profit factor", "Max drawdown", "Tổng lợi nhuận"]
    print(f"\nChia dữ liệu tại {split_time:%Y-%m-%d} (in-sample {cfg.in_sample_frac:.0%} thời gian)")
    print("Drawdown/lợi nhuận tính trên danh mục chia đều vốn cho từng coin.\n")
    print(f"{'Chỉ số':<18}{'In-sample':>14}{'Out-of-sample':>16}{'Toàn bộ':>14}")
    for row in zip(labels, fmt(is_m), fmt(oos_m), fmt(all_m)):
        print(f"{row[0]:<18}{row[1]:>14}{row[2]:>16}{row[3]:>14}")
    print(f"\nOOS/IS expectancy: {ratio:.0%}")

    print("\nTheo từng coin (toàn bộ thời gian):")
    print(f"  {'Coin':<10}{'Lệnh':>6}{'Thắng':>9}{'Expectancy':>13}{'PF':>7}")
    for sym, g in trades.groupby("symbol"):
        m = compute_metrics(g)
        print(f"  {sym:<10}{m['trades']:>6}{m['win_rate_pct']:>8.1f}%"
              f"{m['expectancy_pct']:>+12.3f}%{m['profit_factor']:>7.2f}")

    print("\nKiểm tra ngưỡng (trên out-of-sample):")
    checks = check_thresholds(oos_m, ratio)
    print_checks(checks)
    print("\n=> " + ("Đủ điều kiện sang bước tiếp theo." if all(checks.values())
                     else "Chưa đủ điều kiện — cần tầng 2/3 hoặc chỉnh giả thuyết."))

    out = Path(cfg.data_dir) / "trades_phase1.csv"
    trades.to_csv(out, index=False)
    print(f"\nNhật ký lệnh: {out} ({len(trades)} lệnh)")


if __name__ == "__main__":
    main()
