import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bot.config import Config
from bot.data import load_bars
from bot.metrics import check_thresholds, compute_metrics
from bot.paper import run_paper
from bot.variants import D1 as VARIANT

sys.stdout.reconfigure(encoding="utf-8")

PAPER_DIR = Path("paper")
INITIAL_CAPITAL = 10_000.0


def load_paper_config() -> dict:
    PAPER_DIR.mkdir(exist_ok=True)
    path = PAPER_DIR / "config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    today = pd.Timestamp.now(tz="UTC").normalize()
    conf = {"start": today.isoformat(), "variant": VARIANT.name, "timeframe": "1d",
            "initial_capital": INITIAL_CAPITAL, "created": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(conf, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Bắt đầu paper trading mới từ {today:%Y-%m-%d} (UTC)\n")
    return conf


def append_journal(events: list[dict]) -> int:
    path = PAPER_DIR / "journal.csv"
    old = pd.read_csv(path, encoding="utf-8") if path.exists() else pd.DataFrame(columns=["key"])
    seen = set(old["key"])
    new = [e for e in events if e["key"] not in seen]
    if new:
        run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        df = pd.DataFrame(new).assign(logged_at=run_at)
        pd.concat([old, df], ignore_index=True).to_csv(path, index=False, encoding="utf-8")
    return len(new)


def main() -> None:
    cfg = Config()
    conf = load_paper_config()
    start = pd.Timestamp(conf["start"])
    capital = conf["initial_capital"]
    slot = capital / len(cfg.symbols)

    all_trades, opens, pendings, events = [], [], [], []
    last_day = None
    for sym in cfg.symbols:
        daily = load_bars(sym, cfg, "1d")
        if daily.empty:
            continue
        res = run_paper(daily, cfg, VARIANT, start)
        last_day = res.last_bar if last_day is None else max(last_day, res.last_bar)
        if not res.trades.empty:
            t = res.trades.assign(symbol=sym)
            all_trades.append(t)
            for _, r in t.iterrows():
                events.append({"key": f"ENTRY|{sym}|{r.entry_time}", "event": "VÀO", "symbol": sym,
                               "time": r.entry_time, "price": r.entry_price, "return_pct": None})
                events.append({"key": f"EXIT|{sym}|{r.entry_time}", "event": "THOÁT", "symbol": sym,
                               "time": r.exit_time, "price": r.exit_price, "return_pct": r.return_pct})
        if res.position:
            p = res.position
            opens.append((sym, p))
            events.append({"key": f"ENTRY|{sym}|{p.entry_time}", "event": "VÀO", "symbol": sym,
                           "time": p.entry_time, "price": p.entry_price, "return_pct": None})
        if res.pending_signal is not None:
            pendings.append((sym, res.pending_signal))
            events.append({"key": f"SIGNAL|{sym}|{res.pending_signal}", "event": "TÍN HIỆU", "symbol": sym,
                           "time": res.pending_signal, "price": None, "return_pct": None})

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    n_new = append_journal(events)

    realized = 0.0
    if not trades.empty:
        for _, g in trades.groupby("symbol"):
            realized += slot * ((1 + g["return_pct"] / 100).prod() - 1)
    unrealized = 0.0
    for sym, p in opens:
        base = slot
        if not trades.empty and sym in set(trades["symbol"]):
            base = slot * (1 + trades.loc[trades["symbol"] == sym, "return_pct"] / 100).prod()
        unrealized += base * p.unrealized_pct / 100
    equity = capital + realized + unrealized

    print(f"Chiến lược: {VARIANT.name} — {VARIANT.exit.label()}")
    print(f"Bắt đầu: {start:%Y-%m-%d} | Nến ngày mới nhất đã đóng: {last_day:%Y-%m-%d} (UTC)")
    print(f"Vốn ảo: {equity:,.2f} USDT ({(equity / capital - 1) * 100:+.2f} %) "
          f"= {capital:,.0f} + đã chốt {realized:+,.2f} + đang mở {unrealized:+,.2f}\n")

    print(f"Lệnh đang mở ({len(opens)}):")
    for sym, p in opens:
        print(f"  {sym:<10} vào {p.entry_time:%Y-%m-%d} giá {p.entry_price:.6g}, hiện {p.last_close:.6g} "
              f"({p.unrealized_pct:+.2f} %), stop {p.stop:.6g}, đã giữ {p.bars_held} ngày")
    if not opens:
        print("  (không có)")

    print(f"\nTín hiệu mới — sẽ VÀO ở giá mở cửa nến ngày tiếp theo ({len(pendings)}):")
    for sym, t in pendings:
        print(f"  {sym:<10} tín hiệu nến {t:%Y-%m-%d}")
    if not pendings:
        print("  (không có)")

    if not trades.empty:
        m = compute_metrics(trades)
        print(f"\nĐã đóng {m['trades']} lệnh: thắng {m['win_rate_pct']:.1f} %, "
              f"expectancy {m['expectancy_pct']:+.2f} %, PF {m['profit_factor']:.2f}, "
              f"max DD {m['max_drawdown_pct']:.1f} %")
        checks = check_thresholds(m, 1.0)
        checks.pop("OOS/IS >= 70 %")
        print("Ngưỡng tài liệu: " + ", ".join(f"{k} {'✓' if ok else '✗'}" for k, ok in checks.items()))
    else:
        print("\nChưa có lệnh nào đóng.")
    print(f"\nNhật ký: {PAPER_DIR / 'journal.csv'} (+{n_new} sự kiện mới)")


if __name__ == "__main__":
    main()
