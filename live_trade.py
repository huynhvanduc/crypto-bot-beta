import json
import sys
import traceback
from pathlib import Path

import pandas as pd

from bot.config import Config
from bot.exchange import BinanceSpot
from bot.filelock import file_lock
from bot.gitops import git
from bot.gitops import push as git_push
from bot.live import STATE_PATH, UNSUPPORTED, VARIANT, LiveTrader, load_state, now_iso, save_state
from bot.metrics import compute_metrics
from bot.shadow import MIN_TRADES, run_shadow
from bot.sim_exchange import SimExchange

sys.stdout.reconfigure(encoding="utf-8")

CAPITAL = 10_000.0
DOCS = Path("docs")
BACKTEST_REF = {"trades": 251, "win_rate_pct": 39.4, "expectancy_pct": 1.814, "profit_factor": 1.32,
                "max_drawdown_pct": 15.5, "period": "22/10/2024 – 14/11/2026"}


def export(state: dict, snap: dict, error: str | None) -> None:
    trades = pd.DataFrame(state["trades"])
    m = compute_metrics(trades) if not trades.empty else None
    cap = state["initial_capital"]
    realized = sum(t["pnl_usdt"] for t in state["trades"])
    data = {
        "updated": now_iso(), "mode": state["mode"], "start": state["start"], "variant": VARIANT.name,
        "rule": VARIANT.exit.label(), "initial_capital": cap,
        "equity": snap.get("equity", cap), "realized": realized, "unrealized": snap.get("unrealized", 0.0),
        "last_bar": snap.get("last_bar"), "signals": snap.get("signals", []),
        "positions": snap.get("positions", []),
        "trades": sorted(state["trades"], key=lambda t: t["exit_time"], reverse=True),
        "equity_curve": state["equity_curve"][-2000:],
        "metrics": m, "backtest": BACKTEST_REF, "symbols": len(state["slots"]),
        "log": state["log"][-40:][::-1], "error": error,
        "radar": snap.get("radar", []), "account": snap.get("account", {}),
        "shadow": snap.get("shadow", []), "shadow_min_trades": MIN_TRADES,
        "next_run_note": "07:05 hằng ngày (giờ VN)", "paused": bool(state.get("paused")),
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(data, ensure_ascii=False, default=str, allow_nan=False),
                                    encoding="utf-8")


def push() -> None:
    git("add", "docs/data.json", "docs/index.html")
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("Không có gì mới để đẩy lên.")
        return
    git("commit", "-m", f"Cập nhật dashboard {now_iso()}")
    r = git_push()
    print("Đã đẩy lên GitHub." if r.returncode == 0 else f"Đẩy lên GitHub lỗi: {r.stderr.strip()}")


def main() -> None:
    args = set(sys.argv[1:])
    cfg = Config()
    symbols = [s for s in cfg.symbols if s not in UNSUPPORTED]

    real = BinanceSpot()
    use_real = real.has_keys and "--sim" not in args
    mode = ("testnet" if real.is_testnet else "LIVE") if use_real else "mô phỏng"
    state = load_state(CAPITAL, symbols, mode)
    if state["mode"] != mode:
        sys.exit(f"Trạng thái hiện tại thuộc chế độ '{state['mode']}', lần này là '{mode}'. "
                 f"Xóa {STATE_PATH} để bắt đầu lại ở chế độ mới.")
    ex = real if use_real else SimExchange(state["sim_orders"])
    print(f"Chế độ: {mode} | {VARIANT.name} | {len(symbols)} coin\n")

    trader = LiveTrader(ex, state, cfg)
    snap, error = {}, None
    try:
        if "--close-all" in args:
            trader.close_all()
        elif "--pause" in args:
            trader.set_paused(True)
        elif "--resume" in args:
            trader.set_paused(False)
        snap = trader.run()
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        trader.log(f"LỖI: {error}")
        traceback.print_exc()
    finally:
        save_state(state)
        if snap:
            try:
                start = pd.Timestamp(state["start"]).normalize()
                snap["shadow"] = run_shadow(cfg, symbols, start)
            except Exception as e:
                trader.log(f"Thí nghiệm song song lỗi: {type(e).__name__}: {e}")
        export(state, snap, error)

    if snap:
        print(f"\nVốn: {snap['equity']:,.2f} USDT ({(snap['equity'] / CAPITAL - 1) * 100:+.2f} %) | "
              f"{len(snap['positions'])} lệnh mở | tín hiệu hôm nay: {', '.join(snap['signals']) or 'không'}")
    if "--push" in args:
        push()
    if error:
        sys.exit(1)


if __name__ == "__main__":
    with file_lock(wait=600):
        main()
