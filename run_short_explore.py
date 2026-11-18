"""Nghiên cứu bán khống (futures USDT-M, đòn bẩy 1×) khung ngày — chỉ backtest, không đặt lệnh.

Câu hỏi: khi thị trường giảm (bot D1 mua không có lệnh), bán khống có lãi sau phí không?

Luật chốt TRƯỚC khi xem kết quả (19/11/2026):
- Dữ liệu: giá spot của 30 coin trong Config làm đại diện cho giá futures, nến ngày gộp từ nến 1h đã đóng.
  Chỉ xét từ khi EMA200 ngày có giá trị.
- Tín hiệu lúc nến ngày đóng, vào ở giá mở nến kế tiếp. Mỗi coin 1 lệnh short một lúc. Đòn bẩy 1× (không cháy).
- Chi phí (thận trọng): phí taker futures 0,05 %/chiều + trượt giá 0,05 %/chiều, và coi funding là CHI PHÍ
  0,03 %/ngày giữ lệnh (thực tế funding dương thường làm short được nhận; ở đây tính ngược để không đánh giá cao).
- Lãi lệnh short = (giá vào·(1 − c) − giá ra·(1 + c)) / giá vào − 0,03 %·số ngày giữ, c = 0,1 %.
- Biến thể (thoát theo kiểu trailing ngược: stop đầu = giá vào + 2×ATR, kéo xuống theo đáy thấp nhất + 3×ATR,
  tối đa 240 nến; giá mở ≥ stop → mua lại ở giá mở; high ≥ stop → mua lại ở stop; hết hạn → close nến cuối):
  S1  Thủng đáy 20 ngày, close < EMA200 (đối xứng bot D1)
  S2  Thủng đáy 55 ngày, close < EMA200
  S3  Thủng đáy 20 ngày, không lọc xu hướng
  S4  Thủng đáy 10 ngày, close < EMA200
  S5  Bán khi hồi: RSI(2) > 90 và close < EMA200. Thoát khi close < SMA5 (mua lại ở giá mở hôm sau),
      stop = giá vào + 2×ATR, tối đa 10 nến.
- In-sample = 70 % đầu. Chọn 1 biến thể có expectancy in-sample cao nhất (≥ 100 lệnh), kiểm tra out-of-sample 1 lần.
  Đạt khi OOS: expectancy > 0, PF > 1,3, sụt vốn < 20 %, OOS/IS ≥ 70 %, ≥ 100 lệnh, t-stat ≥ 2.
- Thông tin thêm (không dùng để chọn): danh mục gộp D1 mua (luật hiện tại, phí spot) + biến thể short đã chọn,
  mỗi coin một ô vốn mua và một ô vốn bán riêng; tần suất lệnh gần đây và tín hiệu ở nến mới nhất.
"""
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot.config import Config
from bot.data import load_all, resample_ohlc
from bot.labeling import BarrierResult
from bot.metrics import check_thresholds, compute_metrics, oos_ratio, print_checks, tstat
from run_d1_explore import SLIPPAGE, VARIANTS as LONG_VARIANTS, backtest as long_backtest, prepare
from run_explore import line

sys.stdout.reconfigure(encoding="utf-8")

COST = 0.0005 + 0.0005
FUNDING_PER_DAY = 0.0003
MIN_IS_TRADES = 100
RECENT_FROM = pd.Timestamp("2026-10-01", tz="UTC")
HEAD = f"{'Biến thể':<32}{'Lệnh':>6}{'Thắng':>9}{'Lời TB':>9}{'Lỗ TB':>9}{'Expect.':>11}{'PF':>7}{'MaxDD':>9}"


@dataclass(frozen=True)
class S:
    name: str
    kind: str          # "breakdown" | "rally"
    n: int = 20
    ema_filter: bool = True


VARIANTS = [
    S("S1 Thủng đáy 20 < EMA200", "breakdown", 20, True),
    S("S2 Thủng đáy 55 < EMA200", "breakdown", 55, True),
    S("S3 Thủng đáy 20, không lọc", "breakdown", 20, False),
    S("S4 Thủng đáy 10 < EMA200", "breakdown", 10, True),
    S("S5 Bán khi hồi RSI(2)>90", "rally"),
]


def signals(df: pd.DataFrame, v: S) -> pd.Series:
    c = df["close"]
    if v.kind == "breakdown":
        sig = c < df["low"].shift(1).rolling(v.n).min()
        if v.ema_filter:
            sig &= c < df["ema200"]
    else:
        sig = (df["rsi2"] > 90) & (c < df["ema200"])
    warm = df[["ema200", "atr"]].notna().all(axis=1)
    return (sig & warm).fillna(False)


def short_trail(o, h, l, c, e, entry, atr_value, sl_atr=2.0, trail_atr=3.0, max_bars=240) -> BarrierResult | None:
    stop = entry + sl_atr * atr_value
    ll = np.inf
    last = e + max_bars - 1
    for j in range(e, min(last, len(c) - 1) + 1):
        if o[j] >= stop:
            return BarrierResult(j, float(o[j]), "stop")
        if h[j] >= stop:
            return BarrierResult(j, stop, "stop")
        ll = min(ll, l[j])
        stop = min(stop, ll + trail_atr * atr_value)
    if last >= len(c):
        return None
    return BarrierResult(last, float(c[last]), "time")


def short_rally_exit(o, h, c, sma5, e, entry, atr_value, max_bars=10) -> BarrierResult | None:
    stop = entry + 2 * atr_value
    last = e + max_bars - 1
    for j in range(e, min(last, len(c) - 1) + 1):
        if o[j] >= stop:
            return BarrierResult(j, float(o[j]), "stop")
        if h[j] >= stop:
            return BarrierResult(j, stop, "stop")
        if c[j] < sma5[j] and j < last:
            if j + 1 >= len(c):
                return None
            return BarrierResult(j + 1, float(o[j + 1]), "target")
    if last >= len(c):
        return None
    return BarrierResult(last, float(c[last]), "time")


def short_return(entry: float, exit_price: float, days: int) -> float:
    return (entry * (1 - COST) - exit_price * (1 + COST)) / entry - FUNDING_PER_DAY * days


def backtest(df: pd.DataFrame, v: S) -> pd.DataFrame:
    sig = signals(df, v).to_numpy()
    o, h, l, c, a = (df[k].to_numpy() for k in ("open", "high", "low", "close", "atr"))
    sma5 = df["sma5"].to_numpy()
    times = df.index
    rows, busy = [], -1
    for i in np.flatnonzero(sig):
        if i <= busy:
            continue
        e = i + 1
        if e >= len(df):
            break
        entry = o[e]
        if v.kind == "breakdown":
            res = short_trail(o, h, l, c, e, entry, a[i])
        else:
            res = short_rally_exit(o, h, c, sma5, e, entry, a[i])
        if res is None:
            break
        days = res.exit_idx - e + 1
        ret = short_return(entry, res.exit_price, days)
        rows.append({"signal_time": times[i], "entry_time": times[e], "exit_time": times[res.exit_idx],
                     "entry_price": entry, "exit_price": res.exit_price, "barrier": res.barrier,
                     "bars_held": days, "return_pct": ret * 100, "win": ret > 0})
        busy = res.exit_idx
    return pd.DataFrame(rows)


def run_all(data: dict, fn, v) -> pd.DataFrame:
    parts = []
    for sym, df in data.items():
        t = fn(df, v)
        if not t.empty:
            t.insert(0, "symbol", sym)
            parts.append(t)
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    cfg = Config()
    hourly, end_time = load_all(cfg)
    data = {s: prepare(resample_ohlc(df, "1d")) for s, df in hourly.items()}
    split = cfg.split_time(end_time)
    last_day = max(df.index[-1] for df in data.values())
    print(f"BÁN KHỐNG khung 1d, {len(data)} coin, in-sample tới {split:%Y-%m-%d}, nến mới nhất {last_day:%Y-%m-%d}")
    print(f"Chi phí: phí+trượt {COST:.2%}/chiều, funding tính là chi phí {FUNDING_PER_DAY:.2%}/ngày, đòn bẩy 1×\n")

    results = {v.name: run_all(data, backtest, v) for v in VARIANTS}

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
        now = [s for s, df in data.items() if bool(signals(df, v).iloc[-1])]
        print(f"  {v.name:<32} lệnh vào từ {RECENT_FROM:%d/%m}: {recent:>4} | tín hiệu nến {last_day:%d/%m}: "
              f"{len(now)} {' '.join(x.replace('USDT', '') for x in now)}")

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
    print(f"Thoát lệnh OOS: {oos_t['barrier'].value_counts().to_dict()} | giữ TB {oos_t['bars_held'].mean():.1f} ngày")

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
    passed = all(checks.values())
    print("\n=> " + ("ĐẠT — có thể chạy thử trên testnet futures." if passed else "KHÔNG ĐẠT — không chạy bán khống."))

    d1 = LONG_VARIANTS[0]
    long_t = run_all(data, lambda df, v: long_backtest(df, v, cfg.fee + SLIPPAGE), d1)
    short_t = t.assign(symbol=t["symbol"] + "_S")
    combo = pd.concat([long_t, short_t], ignore_index=True)
    print(f"\nTHÔNG TIN THÊM — gộp {d1.name} (mua) + {best} (bán khống):")
    print(HEAD)
    for label, part in (("Chỉ mua — OOS", long_t), ("Gộp mua + bán — OOS", combo)):
        print(line(label, compute_metrics(part[part["entry_time"] >= split])))
    for y, g in combo.groupby(combo["entry_time"].dt.year):
        m = compute_metrics(g)
        lm = compute_metrics(long_t[long_t["entry_time"].dt.year == y])
        print(f"  {y}: gộp {m['trades']:>4} lệnh, expectancy {m['expectancy_pct']:+.3f}%, lãi danh mục "
              f"{m['total_return_pct']:+7.1f}% | chỉ mua {lm['total_return_pct']:+7.1f}%")

    t.to_csv(f"{cfg.data_dir}/trades_short_explore_best.csv", index=False)


if __name__ == "__main__":
    main()
