"""Nghiên cứu luật thay thế cho bot D1 (khung ngày) — chỉ backtest, không đặt lệnh.

Câu hỏi: có luật nào vẫn có lệnh khi thị trường giảm (đa số coin dưới EMA200) mà vẫn có lãi sau phí?

Luật chốt TRƯỚC khi xem kết quả (19/11/2026):
- Dữ liệu: 30 coin trong Config, nến ngày gộp từ nến 1h đã đóng (đủ 24 nến). Chỉ xét từ khi EMA200 ngày có giá trị
  (mọi biến thể cùng thời gian khởi động).
- Tín hiệu lúc nến ngày đóng, vào ở giá mở nến kế tiếp. Mỗi coin 1 lệnh một lúc. Chỉ mua (spot).
- Chi phí: phí 0,1 %/chiều + trượt giá 5 bps/chiều (kể cả biến thể gốc, nên số liệu gốc thấp hơn dashboard).
- Biến thể theo xu hướng (thoát: trailing 3×ATR, SL đầu 2×ATR, tối đa 240 nến — như bot hiện tại):
  D1  Donchian20, close > EMA200 (bot hiện tại, làm mốc)
  A1  Donchian20, close > EMA100
  A2  Donchian20, close > EMA50
  A3  Donchian20, không lọc xu hướng
  A4  Donchian10, close > EMA200
  A5  Donchian10, không lọc xu hướng
- Biến thể bắt đáy khung ngày (không lọc xu hướng):
  M1  RSI(2) < 10. Thoát khi close > SMA5 (bán ở giá mở hôm sau), stop 2×ATR, tối đa 10 nến.
  M2  close < SMA20 − 2σ, nến trước chưa dưới dải. Thoát khi close > SMA20 (bán ở giá mở hôm sau),
      stop 2×ATR, tối đa 20 nến.
  Giá mở ≤ stop → bán ở giá mở; low ≤ stop → bán ở stop; hết hạn → bán ở close nến cuối.
- In-sample = 70 % đầu (như run_explore). Chọn 1 biến thể có expectancy in-sample cao nhất (≥ 100 lệnh),
  kiểm tra out-of-sample 1 lần. Đạt khi OOS: expectancy > 0, PF > 1,3, sụt vốn < 20 %, OOS/IS ≥ 70 %,
  ≥ 100 lệnh, t-stat ≥ 2.
- Tần suất (không phải hiệu quả, in cho mọi biến thể): số lệnh vào từ 01/10/2026, số tín hiệu ở nến ngày mới nhất.
"""
import sys
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from bot.config import Config
from bot.data import load_all, resample_ohlc
from bot.exits import trail, trailing_stop
from bot.indicators import atr, ema, rsi
from bot.labeling import BarrierResult
from bot.metrics import check_thresholds, compute_metrics, net_return, oos_ratio, print_checks, tstat
from run_explore import line

sys.stdout.reconfigure(encoding="utf-8")

SLIPPAGE = 0.0005
MIN_IS_TRADES = 100
RECENT_FROM = pd.Timestamp("2026-10-01", tz="UTC")
TRAIL = trail(2, 3, 240)
HEAD = f"{'Biến thể':<32}{'Lệnh':>6}{'Thắng':>9}{'Lời TB':>9}{'Lỗ TB':>9}{'Expect.':>11}{'PF':>7}{'MaxDD':>9}"


@dataclass(frozen=True)
class V:
    name: str
    kind: str            # "donchian" | "rsi2" | "boll"
    n: int = 20          # Donchian
    ema_len: int = 0     # 0 = không lọc


VARIANTS = [
    V("D1 Donchian20 > EMA200 (gốc)", "donchian", 20, 200),
    V("A1 Donchian20 > EMA100", "donchian", 20, 100),
    V("A2 Donchian20 > EMA50", "donchian", 20, 50),
    V("A3 Donchian20, không lọc", "donchian", 20, 0),
    V("A4 Donchian10 > EMA200", "donchian", 10, 200),
    V("A5 Donchian10, không lọc", "donchian", 10, 0),
    V("M1 RSI(2)<10 · về SMA5", "rsi2"),
    V("M2 Bollinger 2σ · về SMA20", "boll"),
]


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    df["atr"] = atr(df, 14)
    df["ema200"] = ema(c, 200)
    for n in (50, 100):
        df[f"ema{n}"] = ema(c, n)
    df["rsi2"] = rsi(c, 2)
    df["sma5"] = c.rolling(5).mean()
    df["sma20"] = c.rolling(20).mean()
    df["low_band"] = df["sma20"] - 2 * c.rolling(20).std()
    return df


def signals(df: pd.DataFrame, v: V) -> pd.Series:
    c = df["close"]
    if v.kind == "donchian":
        sig = c > df["high"].shift(1).rolling(v.n).max()
        if v.ema_len:
            sig &= c > df[f"ema{v.ema_len}"]
    elif v.kind == "rsi2":
        sig = df["rsi2"] < 10
    elif v.kind == "boll":
        below = c < df["low_band"]
        sig = below & ~below.shift(1, fill_value=False)
    else:
        raise ValueError(v.kind)
    warm = df[["ema200", "atr"]].notna().all(axis=1)
    return (sig & warm).fillna(False)


def mean_exit(o, l, c, target, entry_idx, entry, atr_value, max_bars) -> BarrierResult | None:
    stop = entry - 2 * atr_value
    last = entry_idx + max_bars - 1
    for j in range(entry_idx, min(last, len(c) - 1) + 1):
        if o[j] <= stop:
            return BarrierResult(j, float(o[j]), "stop")
        if l[j] <= stop:
            return BarrierResult(j, stop, "stop")
        if c[j] > target[j] and j < last:
            if j + 1 >= len(c):
                return None
            return BarrierResult(j + 1, float(o[j + 1]), "target")
    if last >= len(c):
        return None
    return BarrierResult(last, float(c[last]), "time")


def backtest(df: pd.DataFrame, v: V, fee: float) -> pd.DataFrame:
    sig = signals(df, v).to_numpy()
    o, h, l, c, a = (df[k].to_numpy() for k in ("open", "high", "low", "close", "atr"))
    times = df.index
    rows, busy = [], -1
    for i in np.flatnonzero(sig):
        if i <= busy:
            continue
        e = i + 1
        if e >= len(df):
            break
        entry = o[e]
        if v.kind == "donchian":
            res = trailing_stop(o, h, l, c, e, entry, a[i], TRAIL.sl_atr, TRAIL.trail_atr, TRAIL.max_bars)
        elif v.kind == "rsi2":
            res = mean_exit(o, l, c, df["sma5"].to_numpy(), e, entry, a[i], 10)
        else:
            res = mean_exit(o, l, c, df["sma20"].to_numpy(), e, entry, a[i], 20)
        if res is None:
            break
        ret = net_return(entry, res.exit_price, fee)
        rows.append({"signal_time": times[i], "entry_time": times[e], "exit_time": times[res.exit_idx],
                     "entry_price": entry, "exit_price": res.exit_price, "barrier": res.barrier,
                     "bars_held": res.exit_idx - e + 1, "return_pct": ret * 100, "win": ret > 0})
        busy = res.exit_idx
    return pd.DataFrame(rows)


def main() -> None:
    cfg = Config()
    fee = cfg.fee + SLIPPAGE
    hourly, end_time = load_all(cfg)
    data = {s: prepare(resample_ohlc(df, "1d")) for s, df in hourly.items()}
    split = cfg.split_time(end_time)
    last_day = max(df.index[-1] for df in data.values())
    print(f"Khung 1d, {len(data)} coin, in-sample tới {split:%Y-%m-%d}, nến ngày mới nhất {last_day:%Y-%m-%d}")
    print(f"Chi phí: phí {cfg.fee:.1%} + trượt giá {SLIPPAGE:.2%} mỗi chiều\n")

    results = {}
    for v in VARIANTS:
        parts = []
        for sym, df in data.items():
            t = backtest(df, v, fee)
            if not t.empty:
                t.insert(0, "symbol", sym)
                parts.append(t)
        results[v.name] = pd.concat(parts, ignore_index=True)

    print("IN-SAMPLE (dùng để chọn):")
    print(HEAD)
    is_m = {}
    for v in VARIANTS:
        t = results[v.name]
        is_m[v.name] = compute_metrics(t[t["entry_time"] < split])
        print(line(v.name, is_m[v.name]))

    print("\nTần suất (không phải hiệu quả):")
    for v in VARIANTS:
        t = results[v.name]
        recent = int((t["entry_time"] >= RECENT_FROM).sum())
        now = sum(bool(signals(df, v).iloc[-1]) for df in data.values())
        print(f"  {v.name:<32} lệnh vào từ {RECENT_FROM:%d/%m}: {recent:>4} | tín hiệu nến {last_day:%d/%m}: {now}")

    ok = {k: m for k, m in is_m.items() if m["trades"] >= MIN_IS_TRADES}
    best = max(ok, key=lambda k: ok[k]["expectancy_pct"])
    print(f"\n=> Chọn theo expectancy in-sample (≥ {MIN_IS_TRADES} lệnh): {best}")

    t = results[best]
    oos_t = t[t["entry_time"] >= split]
    oos_m = compute_metrics(oos_t)
    print("\nOUT-OF-SAMPLE (chỉ biến thể đã chọn):")
    print(HEAD)
    print(line(best[:25] + " — IS", is_m[best]))
    print(line(best[:25] + " — OOS", oos_m))

    print("\nTheo năm (toàn bộ thời gian):")
    for y, g in t.groupby(t["entry_time"].dt.year):
        m = compute_metrics(g)
        print(f"  {y}: {m['trades']:>5} lệnh, thắng {m['win_rate_pct']:5.1f}%, "
              f"expectancy {m['expectancy_pct']:+.3f}%, PF {m['profit_factor']:.2f}")

    ts = tstat(oos_t["return_pct"])
    ratio = oos_ratio(is_m[best], oos_m)
    print(f"\nt-stat out-of-sample: {ts:.2f}  |  OOS/IS: {ratio:.0%}")
    print("\nKiểm tra ngưỡng (out-of-sample):")
    checks = check_thresholds(oos_m, ratio)
    checks["t-stat >= 2"] = ts >= 2
    print_checks(checks)
    print("\n=> " + ("ĐẠT — có thể cân nhắc đưa lên bot." if all(checks.values()) else "KHÔNG ĐẠT — giữ luật hiện tại."))

    t.to_csv(f"{cfg.data_dir}/trades_d1_explore_best.csv", index=False)


if __name__ == "__main__":
    main()
