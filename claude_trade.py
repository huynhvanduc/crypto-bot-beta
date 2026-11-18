import csv
import sys
import time
from pathlib import Path

import requests

import bot.manual as manual
from bot.ai_limits import Limits, check, day_loss, today_vn
from bot.common import PUBLIC_API, SYMBOLS, UNSUPPORTED, now_iso
from bot.exchange import BinanceSpot
from bot.gitops import git
from bot.gitops import push as git_push
from bot.journal import REAL_FEE_RT_PCT, export_docs, market_excursion, snapshot

sys.stdout.reconfigure(encoding="utf-8")
STATE, JOURNAL = Path("ai/claude.json"), Path("ai/claude_journal.csv")
LIMITS = Limits(max_usdt=200, max_open=5, max_day_loss=150)
SYMS = [s for s in SYMBOLS if s not in UNSUPPORTED]


def trader():
    manual.TAG = "ai"
    ex = BinanceSpot()
    ex.sync_time()
    return manual.ManualTrader(ex, STATE, journal=JOURNAL, context_fn=snapshot, excursion_fn=market_excursion)


def publish(t) -> None:
    try:
        export_docs(t, "docs/claude.json")
        files = ["docs/claude.json", str(STATE), str(JOURNAL)]
        git("add", "--", *[f for f in files if Path(f).exists()])
        if git("diff", "--cached", "--quiet").returncode:
            git("commit", "-m", f"Claude giao dịch {now_iso()}")
            r = git_push()
            print("  → GitHub: " + ("đã đẩy" if r.returncode == 0 else f"lỗi {r.stderr.strip()}"), flush=True)
    except Exception as e:
        print(f"  → GitHub lỗi: {type(e).__name__}: {e}", flush=True)


def sym_of(s: str) -> str:
    return s.upper() + ("" if s.upper().endswith("USDT") else "USDT")


def sync(t) -> list[str]:
    out = []
    for s, p in list(t.pos.items()):
        ids = [o["orderId"] for o in t.ex.order_list(p["oco"])["orders"]] if p.get("oco") else [p.get("stop_order_id")]
        orders = [t.ex.get_order(s, i) for i in ids if i]
        done = next((o for o in orders if o["status"] == "FILLED"), None)
        if done:
            tp = done["type"] == "LIMIT_MAKER"
            out.append(t._result(s, done, f"{'Chốt lời' if tp else 'Cắt lỗ'} {s}:", exit_how="tp" if tp else "stop"))
    return out


def scan():
    rows = []
    for s in SYMS:
        try:
            rows.append((s, snapshot(s)))
        except Exception as e:
            print(s, "lỗi", e)
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
    sym, usdt, tp, sl = sym_of(sym), float(usdt), float(tp), float(sl)
    t = trader()
    refuse = check(LIMITS, len(t.pos), usdt, day_loss(JOURNAL, REAL_FEE_RT_PCT, today_vn()))
    if refuse:
        print(refuse)
        return
    print(t.buy(sym, usdt, f"[Claude] {reason} | TP +{tp:g}% / SL -{sl:g}%"))
    p = t.pos.get(sym)
    if p:
        if p["stop_order_id"]:
            t.ex.cancel_order(sym, p["stop_order_id"])
        e = p["entry"]
        try:
            o = t.ex.oco_sell(sym, p["qty"], e * (1 + tp / 100), e * (1 - sl / 100), tag="ai")
            p["oco"] = o["orderListId"]
            p["stop_order_id"] = next(r["orderId"] for r in o["orderReports"] if r["type"] == "STOP_LOSS")
            print(f"OCO trên sàn: chốt lời {e * (1 + tp / 100):.6g}, cắt lỗ {e * (1 - sl / 100):.6g}")
        except Exception as err:
            p["stop_order_id"] = t.ex.stop_loss_sell(sym, p["qty"], e * (1 - sl / 100), tag="ai")["orderId"]
            print(f"Không đặt được OCO ({err}); chỉ có cắt lỗ {e * (1 - sl / 100):.6g}")
        t.save()
    publish(t)


def sell(sym, why="Claude bán sớm"):
    t = trader()
    print(f"{now_iso()} [{why}] " + t.sell(sym_of(sym)), flush=True)
    publish(t)


def status():
    t = trader()
    closed = sync(t)
    for m in closed:
        print(m)
    for s, p in t.pos.items():
        px = float(requests.get(f"{PUBLIC_API}/ticker/price", params={"symbol": s}, timeout=15).json()["price"])
        print(f"{s}: giữ {(time.time() - p['ts']) / 60:.0f}′ | vào {p['entry']:.6g} | giá {px:.6g} "
              f"({(px / p['entry'] - 1) * 100:+.2f}%, sau phí {(px / p['entry'] - 1) * 100 - REAL_FEE_RT_PCT:+.2f}%) | {p.get('reason', '')}")
    if not t.pos:
        print("Không có lệnh mở.")
    loss = day_loss(JOURNAL, REAL_FEE_RT_PCT, today_vn())
    print(f"Giới hạn: tối đa {LIMITS.max_usdt:g} USDT/lệnh · {len(t.pos)}/{LIMITS.max_open} lệnh mở · "
          f"lỗ đã chốt hôm nay {loss:.2f}/{LIMITS.max_day_loss:g} USDT (chạm mức thì không mua được nữa)")
    if closed:
        publish(t)


def journal(n="20"):
    if not JOURNAL.exists():
        print("Chưa có lệnh nào đóng.")
        return
    with JOURNAL.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))[-int(n):]
    for r in rows:
        net = float(r["ret_market_pct"]) - REAL_FEE_RT_PCT
        print(f"{r['exit_time']} {r['symbol']:<9} {float(r['usdt']):>6.0f} USDT giữ {float(r['minutes']):>5.1f}′ "
              f"sau phí {net:+.2f}% ({r['exit_how']}) cao/thấp {r.get('mfe_pct') or '?'}/{r.get('mae_pct') or '?'} | {r['reason']}")


if __name__ == "__main__":
    cmd, *a = sys.argv[1:]
    {"scan": scan, "buy": lambda: buy(*a), "sell": lambda: sell(*a), "status": status, "journal": lambda: journal(*a)}[cmd]()
