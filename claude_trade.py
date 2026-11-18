"""Claude giao dịch tay trên testnet (đóng vai người chơi). Trạng thái/nhật ký riêng, tag 'ai'.

  scan                                   — quét bối cảnh 29 coin
  buy SYM USDT TP% SL% "lý do"           — mua, ghi kế hoạch thoát
  watch                                  — vòng theo dõi: thoát khi chạm TP/SL (giá thị trường thật) hoặc 30 phút
  status | sell SYM
Chạy: .venv/Scripts/python claude_trade.py <lệnh>  (từ thư mục gốc dự án).
"""
import json
import sys
import time
from pathlib import Path

import requests

import bot.manual as manual
from bot.data import PUBLIC_API
from bot.exchange import BinanceSpot
from bot.filelock import file_lock
from bot.gitops import git
from bot.gitops import push as git_push
from bot.journal import REAL_FEE_RT_PCT, SYMBOLS, export_docs, market_excursion, snapshot
from bot.live import now_iso

sys.stdout.reconfigure(encoding="utf-8")
manual.TAG = "ai"
STATE, JOURNAL = Path("live/claude.json"), Path("live/claude_journal.csv")
PLANS = Path("live/claude_plans.json")
MAX_MIN = 30
SYMS = [s for s in SYMBOLS if s != "EOSUSDT"]


def trader():
    ex = BinanceSpot()
    ex.sync_time()
    return manual.ManualTrader(ex, STATE, journal=JOURNAL, context_fn=snapshot, excursion_fn=market_excursion)


def publish(t) -> None:
    """Xuất docs/claude.json và đẩy GitHub để dashboard hiển thị."""
    try:
        export_docs(t, "docs/claude.json")
        with file_lock():
            git("add", "docs/claude.json")
            if git("diff", "--cached", "--quiet", "--", "docs/claude.json").returncode:
                git("commit", "-m", f"Claude giao dịch {now_iso()}", "--", "docs/claude.json")
                r = git_push()
                print("  → dashboard: " + ("đã đẩy" if r.returncode == 0 else f"lỗi {r.stderr.strip()}"), flush=True)
    except Exception as e:
        print(f"  → dashboard lỗi: {type(e).__name__}: {e}", flush=True)


def plans() -> dict:
    return json.loads(PLANS.read_text(encoding="utf-8")) if PLANS.exists() else {}


def mprice(sym: str) -> float:
    return float(requests.get(f"{PUBLIC_API}/ticker/price", params={"symbol": sym}, timeout=15).json()["price"])


def scan():
    rows = []
    for s in SYMS:
        try:
            f = snapshot(s)
        except Exception as e:
            print(s, "lỗi", e)
            continue
        rows.append((s, f))
        time.sleep(0.15)
    rows.sort(key=lambda r: r[1]["ret_1h_pct"], reverse=True)
    b = rows[0][1]
    print(f"BTC 1h {b['btc_ret_1h_pct']:+.2f}% | BTC trên EMA200 1h: {b['btc_above_ema200_1h']}  ({now_iso()})")
    print(f"{'coin':<6}{'giá':>10}{'15m%':>7}{'1h%':>7}{'4h%':>7}{'24h%':>7}{'rsi5':>6}{'rsi15':>6}{'rsi1h':>6}"
          f"{'ema20_5m%':>10}{'ema200h%':>9}{'atr5%':>6}{'vol5x':>6}{'pos24':>6} trend1h")
    for s, f in rows:
        print(f"{s[:-4]:<6}{f['price']:>10.4g}{f['ret_15m_pct']:>7.2f}{f['ret_1h_pct']:>7.2f}{f['ret_4h_pct']:>7.2f}"
              f"{f['ret_24h_pct']:>7.2f}{f['rsi_5m']:>6.0f}{f['rsi_15m']:>6.0f}{f['rsi_1h']:>6.0f}"
              f"{f['dist_ema20_5m_pct']:>10.2f}{f['dist_ema200_1h_pct']:>9.1f}{f['atr_pct_5m']:>6.2f}"
              f"{f['vol_ratio_5m']:>6.1f}{f['range_pos_24h']:>6.2f} "
              f"{'↑' if f['ema20_gt_ema50_1h'] else '↓'}{'>200' if f['above_ema200_1h'] else ''}")


def buy(sym, usdt, tp, sl, reason):
    sym = sym.upper() + ("" if sym.upper().endswith("USDT") else "USDT")
    t = trader()
    print(t.buy(sym, float(usdt), f"[Claude] {reason} | kế hoạch: TP +{tp}% / SL -{sl}% / tối đa {MAX_MIN}′"))
    if sym in t.pos:
        p = plans()
        e = t.pos[sym]["ctx"].get("price") or t.pos[sym]["entry"]
        p[sym] = {"tp": e * (1 + float(tp) / 100), "sl": e * (1 - float(sl) / 100), "ts": t.pos[sym]["ts"]}
        PLANS.write_text(json.dumps(p, indent=1), encoding="utf-8")
    publish(t)


def sell(sym, why="tay"):
    sym = sym.upper() + ("" if sym.upper().endswith("USDT") else "USDT")
    t = trader()
    print(f"{now_iso()} [{why}] " + t.sell(sym), flush=True)
    p = plans()
    p.pop(sym, None)
    PLANS.write_text(json.dumps(p, indent=1), encoding="utf-8")
    publish(t)


def status():
    t, p = trader(), plans()
    for s, pos in t.pos.items():
        px, pl = mprice(s), p.get(s, {})
        e = pos["ctx"].get("price") or pos["entry"]
        print(f"{s}: giữ {(time.time() - pos['ts']) / 60:.1f}′ | thị trường {px:.6g} ({(px / e - 1) * 100:+.2f}%, "
              f"sau phí {(px / e - 1) * 100 - REAL_FEE_RT_PCT:+.2f}%) | TP {pl.get('tp', 0):.6g} SL {pl.get('sl', 0):.6g}")
    if not t.pos:
        print("Không có lệnh mở.")


def watch():
    print(f"{now_iso()} bắt đầu theo dõi", flush=True)
    while True:
        p = plans()
        if not p:
            print(f"{now_iso()} hết lệnh mở — dừng theo dõi", flush=True)
            return
        for s, pl in list(p.items()):
            try:
                px = mprice(s)
            except Exception:
                continue
            held = (time.time() - pl["ts"]) / 60
            why = "TP" if px >= pl["tp"] else "SL" if px <= pl["sl"] else "hết 30′" if held >= MAX_MIN else None
            if why:
                sell(s, why)
            elif 15 <= held < 15.25:
                print(f"{now_iso()} {s} mốc 15′: giá {px:.6g}", flush=True)
        time.sleep(15)


if __name__ == "__main__":
    cmd, *a = sys.argv[1:]
    {"scan": scan, "buy": lambda: buy(*a), "sell": lambda: sell(*a), "status": status, "watch": watch}[cmd]()
