"""Nghiên cứu "bắt đáy hồi ngắn" (mean reversion) — chỉ backtest, không đặt lệnh.

Luật chốt TRƯỚC khi xem kết quả (16/11/2026):
- Dữ liệu: nến 1 phút 15/11/2024 → 13/11/2026, BTC ETH BNB SOL XRP (data/1m). Nến 15 phút gộp từ 1 phút, chỉ dùng khi đủ 15 nến.
- Chỉ báo 15 phút: RSI(14), SMA20, độ lệch chuẩn 20, ATR(14). Xét lúc nến 15 phút đóng, vào ở giá mở phút kế tiếp.
- Vào lệnh:
  R  RSI quá bán: RSI cắt xuống dưới 25 (nến trước >= 25, nến này < 25).
  B  Bollinger 2,5σ: close < SMA20 − 2,5σ, nến trước chưa dưới dải.
  F  Rơi nhanh: close giảm > 2,5 % so với 4 nến trước (1 giờ) và RSI < 35, nến trước chưa thỏa.
- Thoát lệnh (duyệt từng phút, tối đa 4 giờ rồi bán ở close):
  mean  chốt lời ở SMA20 của nến tín hiệu, stop = giá vào − 2×ATR.
  atr   chốt lời = giá vào + 1,5×ATR, stop = giá vào − 1,5×ATR.
  Giá mở ≤ stop → bán ở giá mở; low ≤ stop → bán ở stop; cùng phút chạm cả hai → tính stop.
- Bỏ tín hiệu nếu khoảng tới mức chốt lời < 0,6 % giá vào. Mỗi coin 1 lệnh một lúc. Không lọc xu hướng.
- Chi phí: phí 0,1 %/chiều + trượt giá 5 bps/chiều.
- Chọn 1 biến thể có lãi TB in-sample cao nhất (>= 100 lệnh), kiểm tra out-of-sample 1 lần.
  Đạt khi OOS: lãi TB > 0, PF > 1,3, sụt vốn < 20 %, OOS/IS >= 70 %, >= 100 lệnh, t-stat >= 2.
"""
import sys
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from bot.config import Config
from bot.indicators import atr, rsi
from bot.intraday import bars, trade_return
from bot.metrics import check_thresholds, compute_metrics, oos_ratio, print_checks, tstat
from bot.minute_data import load_minutes
from run_explore import line

sys.stdout.reconfigure(encoding="utf-8")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
START, END = date(2024, 11, 14), date(2026, 11, 13)
HOLD_MIN, MIN_GAIN, MIN_IS_TRADES = 240, 0.006, 100
ENTRIES = {"R": "RSI quá bán", "B": "Bollinger 2,5σ", "F": "Rơi nhanh"}
EXITS = {"mean": "về SMA20", "atr": "TP/SL 1,5 ATR"}
VARIANTS = [(e, x) for e in ENTRIES for x in EXITS]
HEAD = f"{'Biến thể':<32}{'Lệnh':>6}{'Thắng':>9}{'Lời TB':>9}{'Lỗ TB':>9}{'Expect.':>11}{'PF':>7}{'MaxDD':>9}"


def name(v) -> str:
    return f"{v[0]} {ENTRIES[v[0]]} · {EXITS[v[1]]}"


def prepare(m: pd.DataFrame) -> pd.DataFrame:
    f = bars(m, 15)
    c = f["close"]
    r = rsi(c, 14)
    sma, sd = c.rolling(20).mean(), c.rolling(20).std()
    low = sma - 2.5 * sd
    fast = (c / c.shift(4) - 1 < -0.025) & (r < 35)
    out = pd.DataFrame(index=pd.DatetimeIndex(f["ready"], name="ready"))
    out["R"] = ((r.shift(1) >= 25) & (r < 25)).to_numpy()
    out["B"] = ((c < low) & ~(c.shift(1) < low.shift(1))).to_numpy()
    out["F"] = (fast & ~fast.shift(1, fill_value=False)).to_numpy()
    out["sma"] = sma.to_numpy()
    out["atr"] = atr(f, 14).to_numpy()
    out["contiguous"] = (f.index.to_series().diff() == pd.Timedelta(minutes=15)).to_numpy()
    return out


def backtest(m: pd.DataFrame, p: pd.DataFrame, v) -> pd.DataFrame:
    t = m.index.as_unit("ns").asi8
    o, h, l, c = (m[k].to_numpy() for k in ("open", "high", "low", "close"))
    ok = p[v[0]].to_numpy(dtype=bool) & p["contiguous"].to_numpy(dtype=bool) & ~np.isnan(p["atr"].to_numpy())
    ready, a, sma = p.index.as_unit("ns").asi8, p["atr"].to_numpy(), p["sma"].to_numpy()
    hold = HOLD_MIN * 60_000_000_000
    rows, busy = [], -1
    for i in np.flatnonzero(ok):
        if ready[i] <= busy:
            continue
        j0 = int(np.searchsorted(t, ready[i]))
        if j0 >= len(t) or t[j0] != ready[i]:
            continue
        entry = o[j0]
        if v[1] == "mean":
            target, stop = sma[i], entry - 2 * a[i]
        else:
            target, stop = entry + 1.5 * a[i], entry - 1.5 * a[i]
        if not target / entry - 1 >= MIN_GAIN:
            continue
        end = t[j0] + hold
        if t[-1] < end - 60_000_000_000:
            break
        last = int(np.searchsorted(t, end)) - 1
        res = None
        for j in range(j0, last + 1):
            if o[j] <= stop:
                res = (j, o[j], "stop"); break
            if l[j] <= stop:
                res = (j, stop, "stop"); break
            if h[j] >= target:
                res = (j, target, "target"); break
        if res is None:
            res = (last, c[last], "time")
        j, px, why = res
        ret = trade_return(entry, px)
        rows.append([m.index[j0], m.index[j], entry, px, why, int((t[j] - t[j0]) // 60_000_000_000) + 1, ret * 100])
        busy = t[j]
    return pd.DataFrame(rows, columns=["entry_time", "exit_time", "entry_price", "exit_price", "barrier", "minutes", "return_pct"])


def run(v, minutes, prepared) -> pd.DataFrame:
    parts = [backtest(minutes[s], prepared[s], v).assign(symbol=s) for s in SYMBOLS]
    return pd.concat([x for x in parts if not x.empty], ignore_index=True)


def main() -> None:
    cfg = replace(Config(), start=START.isoformat())
    minutes = {s: load_minutes(s, START, END, f"{cfg.data_dir}/1m") for s in SYMBOLS}
    prepared = {s: prepare(m) for s, m in minutes.items()}
    split = cfg.split_time(max(m.index[-1] for m in minutes.values()))
    print(f"In-sample tới {split:%Y-%m-%d}, out-of-sample sau đó. Phí 0,1 %/chiều + trượt giá 5 bps/chiều. Giữ tối đa 4 giờ.\n")
    results = {v: run(v, minutes, prepared) for v in VARIANTS}
    print("IN-SAMPLE (dùng để chọn):")
    print(HEAD)
    is_m = {}
    for v, t in results.items():
        is_m[v] = compute_metrics(t[t["entry_time"] < split])
        print(line(name(v), is_m[v]))
    ok = {v: m for v, m in is_m.items() if m["trades"] >= MIN_IS_TRADES}
    if not ok:
        print(f"\n=> Không biến thể nào có ≥ {MIN_IS_TRADES} lệnh in-sample → KHÔNG ĐẠT.")
        return
    best = max(ok, key=lambda v: ok[v]["expectancy_pct"])
    print(f"\n=> Chọn theo lãi TB in-sample: {name(best)}")
    t = results[best]
    oos_t = t[t["entry_time"] >= split]
    oos_m = compute_metrics(oos_t)
    print("\nOUT-OF-SAMPLE (chỉ biến thể đã chọn):")
    print(HEAD)
    print(line(name(best) + " — IS", is_m[best]))
    print(line(name(best) + " — OOS", oos_m))
    days = (t["entry_time"].max() - t["entry_time"].min()).days or 1
    print(f"\nTần suất: {len(t) / days:.1f} lệnh/ngày (5 coin) · giữ TB {t['minutes'].mean():.0f} phút · "
          f"thoát: " + ", ".join(f"{k} {n}" for k, n in t["barrier"].value_counts().items()))
    print("\nTheo coin (out-of-sample):")
    for s, g in oos_t.groupby("symbol"):
        mm = compute_metrics(g)
        print(f"  {s:<9}{mm['trades']:>5} lệnh  thắng {mm['win_rate_pct']:5.1f}%  lãi TB {mm['expectancy_pct']:+.3f}%  PF {mm['profit_factor']:.2f}")
    ts = tstat(oos_t["return_pct"])
    ratio = oos_ratio(is_m[best], oos_m)
    print(f"\nt-stat out-of-sample: {ts:.2f}  |  OOS/IS: {ratio:.0%}")
    checks = check_thresholds(oos_m, ratio)
    checks["t-stat >= 2"] = ts >= 2
    print("\nKiểm tra ngưỡng (out-of-sample):")
    print_checks(checks)
    print("\n=> " + ("ĐẠT — được chạy thử trên testnet." if all(checks.values()) else "KHÔNG ĐẠT — không chạy bắt đáy."))
    t.to_csv(f"{cfg.data_dir}/trades_meanrev_{best[0]}_{best[1]}.csv", index=False)


if __name__ == "__main__":
    main()
