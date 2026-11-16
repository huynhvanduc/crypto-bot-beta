import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from bot.backtest import build_candidates, simulate
from bot.config import Config
from bot.data import load_all
from bot.meta import MODELS, fit_final, importance, recent_window, walk_forward_proba
from bot.metrics import check_thresholds, compute_metrics, oos_ratio, print_checks

sys.stdout.reconfigure(encoding="utf-8")

FIRST_TEST = pd.Timestamp("2021-07-01", tz="UTC")
THRESHOLDS = np.round(np.arange(0.30, 0.701, 0.01), 2)
MIN_IS_TRADES = 200
WINDOWS = (None, 24, 18, 12)


def row(name: str, m: dict) -> str:
    return (f"{name:<30}{m['trades']:>6}{m['win_rate_pct']:>8.1f}%{m['expectancy_pct']:>+10.3f}%"
            f"{m['profit_factor']:>7.2f}{m['max_drawdown_pct']:>8.1f}%{m['total_return_pct']:>+9.1f}%")


def auc(df: pd.DataFrame, col: str) -> float:
    d = df.dropna(subset=[col])
    return roc_auc_score(d["win"], d[col])


def pick_threshold(is_c: pd.DataFrame, col: str):
    scan = [(t, compute_metrics(simulate(is_c, (is_c[col] >= t).to_numpy()))) for t in THRESHOLDS]
    ok = [(t, m) for t, m in scan if m["trades"] >= MIN_IS_TRADES]
    return max(ok, key=lambda x: x[1]["expectancy_pct"])[0], scan


def main() -> None:
    cfg = Config()
    data, end_time = load_all(cfg)
    btc = data["BTCUSDT"]
    parts = []
    for sym, df in data.items():
        c = build_candidates(df, cfg, btc)
        c.insert(0, "symbol", sym)
        parts.append(c)
    cands = pd.concat(parts, ignore_index=True).sort_values("signal_time", ignore_index=True)

    split_time = cfg.split_time(end_time)
    is_mask = (cands["signal_time"] >= FIRST_TEST) & (cands["signal_time"] < split_time)
    oos_mask = cands["signal_time"] >= split_time
    print(f"{len(cands)} tín hiệu ứng viên, tỷ lệ thắng gốc {cands['win'].mean():.1%}")
    print(f"Walk-forward từ {FIRST_TEST:%Y-%m-%d}, in-sample tới {split_time:%Y-%m-%d}, sau đó là out-of-sample\n")

    print(f"{'Mô hình':<10}{'Cửa sổ học':<14}{'AUC in-sample':>15}{'AUC out-of-sample':>20}")
    is_auc = {}
    for kind in MODELS:
        for months in WINDOWS:
            col = f"p_{kind}_{months or 'all'}"
            cands[col] = walk_forward_proba(cands, FIRST_TEST, kind, months)
            is_auc[(kind, months)] = auc(cands[is_mask], col)
            win = "toàn bộ" if months is None else f"{months} tháng"
            print(f"{kind:<10}{win:<14}{is_auc[(kind, months)]:>15.3f}{auc(cands[oos_mask], col):>20.3f}")
    kind, months = max(is_auc, key=is_auc.get)
    col = f"p_{kind}_{months or 'all'}"
    win = "toàn bộ lịch sử" if months is None else f"{months} tháng gần nhất"
    print(f"=> Chọn {kind}, học từ {win} (AUC in-sample cao nhất). 0,5 = đoán mò.\n")

    is_c, oos_c = cands[is_mask], cands[oos_mask]

    thr, scan = pick_threshold(is_c, col)
    print(f"Dò ngưỡng xác suất ({kind}) trên in-sample:")
    print(f"  {'Ngưỡng':<8}{'Lệnh':>6}{'Thắng':>9}{'Expectancy':>11}{'PF':>7}")
    for t, m in scan:
        if m["trades"] == 0 or (round(t * 100) % 3 and t != thr):
            continue
        mark = "  <= chọn" if t == thr else ""
        print(f"  {t:<8.2f}{m['trades']:>6}{m['win_rate_pct']:>8.1f}%{m['expectancy_pct']:>+10.3f}%"
              f"{m['profit_factor']:>7.2f}{mark}")

    base_is, base_oos = compute_metrics(simulate(is_c)), compute_metrics(simulate(oos_c))
    meta_is = compute_metrics(simulate(is_c, (is_c[col] >= thr).to_numpy()))
    meta_oos_tr = simulate(oos_c, (oos_c[col] >= thr).to_numpy())
    meta_oos = compute_metrics(meta_oos_tr)

    print(f"\nNgưỡng chọn: {thr:.2f}\n")
    print(f"{'':<30}{'Lệnh':>6}{'Thắng':>9}{'Expectancy':>11}{'PF':>7}{'MaxDD':>9}{'Tổng':>10}")
    print(row("Gốc — in-sample", base_is))
    print(row(f"Meta {kind} — in-sample", meta_is))
    print(row("Gốc — out-of-sample", base_oos))
    print(row(f"Meta {kind} — out-of-sample", meta_oos))

    d = oos_c.dropna(subset=[col]).copy()
    d["nhom"] = pd.qcut(d[col], 5, labels=["1 (thấp)", "2", "3", "4", "5 (cao)"])
    print("\nOut-of-sample theo 5 nhóm xác suất (mọi ứng viên, chưa khớp lệnh):")
    print(f"  {'Nhóm':<10}{'Số':>6}{'P dự đoán':>11}{'Thắng thực':>12}{'Lợi TB':>10}")
    for g, x in d.groupby("nhom", observed=True):
        print(f"  {g:<10}{len(x):>6}{x[col].mean():>10.1%}{x['win'].mean():>11.1%}{x['return_pct'].mean():>+9.3f}%")

    ratio = oos_ratio(meta_is, meta_oos)
    print(f"\nOOS/IS expectancy: {ratio:.0%}")
    print("\nKiểm tra ngưỡng (meta, out-of-sample):")
    checks = check_thresholds(meta_oos, ratio)
    print_checks(checks)
    print("\n=> " + ("Đủ điều kiện sang paper trading." if all(checks.values()) else "Chưa đủ điều kiện."))

    Path("models").mkdir(exist_ok=True)
    Path("models/meta_config.json").write_text(json.dumps(
        {"kind": kind, "train_months": months, "threshold": float(thr),
         "is_auc": is_auc[(kind, months)], "oos_auc": auc(oos_c, col)}, indent=2))
    print("\nĐã lưu cấu hình: models/meta_config.json (dùng cho train_live.py)")

    train = cands[cands["exit_time"] < split_time]
    imp = importance(fit_final(recent_window(train, split_time, months), kind), kind)
    label = "hệ số chuẩn hóa" if kind == "logreg" else "tỷ trọng gain"
    print(f"\nFeature quan trọng nhất ({label}):")
    for k, v in imp.head(10).items():
        print(f"  {k:<18}{v:+.3f}")

    out = Path(cfg.data_dir) / "candidates_meta.csv"
    cands.to_csv(out, index=False)
    print(f"\nỨng viên + xác suất: {out}")


if __name__ == "__main__":
    main()
