import json
import sys
from pathlib import Path

import joblib
import pandas as pd

from bot.backtest import build_candidates, signal_features
from bot.config import Config
from bot.data import load_all
from bot.features import FEATURES
from bot.meta import fit_final, importance, recent_window

sys.stdout.reconfigure(encoding="utf-8")

RECENT_DAYS = 30


def main() -> None:
    cfg = Config()
    meta_cfg = json.loads(Path("models/meta_config.json").read_text())
    kind, months, thr = meta_cfg["kind"], meta_cfg["train_months"], meta_cfg["threshold"]

    data, _ = load_all(cfg)
    btc = data["BTCUSDT"]
    now = btc.index[-1] + pd.Timedelta(hours=1)
    cands, signals = [], []
    for sym, df in data.items():
        c = build_candidates(df, cfg, btc)
        c.insert(0, "symbol", sym)
        cands.append(c)
        s = signal_features(df, cfg, btc)
        s.insert(0, "symbol", sym)
        signals.append(s)
    cands = pd.concat(cands, ignore_index=True)
    signals = pd.concat(signals, ignore_index=True)

    train = recent_window(cands[cands["exit_time"] < now].dropna(subset=FEATURES), now, months)
    model = fit_final(train, kind)
    win = "toàn bộ lịch sử" if months is None else f"{months} tháng gần nhất"
    print(f"Mô hình {kind}, học từ {win}: {len(train)} lệnh, "
          f"{train['signal_time'].min():%Y-%m-%d} → {train['exit_time'].max():%Y-%m-%d}")
    print(f"Tỷ lệ thắng gốc trong giai đoạn học: {train['win'].mean():.1%}")

    Path("models").mkdir(exist_ok=True)
    out = Path("models") / "meta_live.joblib"
    joblib.dump({"model": model, "kind": kind, "features": FEATURES, "threshold": thr,
                 "train_months": months, "trained_until": now}, out)
    print(f"Đã lưu: {out}\n")

    imp = importance(model, kind)
    label = "hệ số chuẩn hóa" if kind == "logreg" else "tỷ trọng gain"
    print(f"Feature quan trọng nhất trong giai đoạn gần đây ({label}):")
    for k, v in imp.head(8).items():
        print(f"  {k:<18}{v:+.3f}")

    recent = signals[signals["signal_time"] >= now - pd.Timedelta(days=RECENT_DAYS)].dropna(subset=FEATURES)
    print(f"\nTín hiệu tầng 1 trong {RECENT_DAYS} ngày qua (ngưỡng vào lệnh {thr:.2f}):")
    if recent.empty:
        print("  (không có)")
    else:
        recent = recent.assign(proba=model.predict_proba(recent[FEATURES])[:, 1]).sort_values("signal_time")
        res = cands.set_index(["symbol", "signal_time"])["return_pct"]
        print(f"  {'Thời điểm (UTC)':<18}{'Coin':<10}{'Giá':>12}{'P thắng':>9}  {'Hành động':<10}{'Kết quả':>9}")
        for _, r in recent.iterrows():
            act = "VÀO" if r["proba"] >= thr else "bỏ qua"
            k = (r["symbol"], r["signal_time"])
            outcome = f"{res[k]:+.2f}%" if k in res.index else "đang chạy"
            print(f"  {r['signal_time']:%Y-%m-%d %H:%M}  {r['symbol']:<10}{r['close']:>12.4g}"
                  f"{r['proba']:>8.1%}  {act:<10}{outcome:>9}")

    last_bar = btc.index[-1]
    live = signals[signals["signal_time"] == last_bar]
    print(f"\nNến vừa đóng ({last_bar:%Y-%m-%d %H:%M} UTC): "
          + ("không coin nào có tín hiệu." if live.empty else f"{len(live)} tín hiệu, xem bảng trên."))


if __name__ == "__main__":
    main()
