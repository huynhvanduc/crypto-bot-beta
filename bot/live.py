from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .config import Config
from .data import PUBLIC_API, load_bars
from .exchange import BinanceError, fill_summary
from .strategy import add_indicators
from .variants import D1 as VARIANT

RULE = VARIANT.exit
STATE_PATH = Path("live/state.json")
UNSUPPORTED = {"EOSUSDT"}
ORDER_TAG = "d1"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(capital: float, symbols: list[str], mode: str) -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    slot = capital / len(symbols)
    return {"mode": mode, "start": now_iso(), "initial_capital": capital, "variant": VARIANT.name,
            "slots": {s: slot for s in symbols}, "positions": {}, "trades": [], "last_exit_bar": {},
            "last_bar": None, "equity_curve": [], "log": [], "sim_orders": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


class LiveTrader:
    def __init__(self, exchange, state: dict, cfg: Config | None = None):
        self.ex, self.st, self.cfg = exchange, state, cfg or Config()
        self.symbols = list(state["slots"])

    def log(self, msg: str) -> None:
        line = f"{now_iso()} {msg}"
        print(line)
        self.st["log"] = (self.st["log"] + [line])[-200:]

    def daily(self, sym: str) -> pd.DataFrame:
        return add_indicators(load_bars(sym, self.cfg, "1d"), self.cfg)

    def _close(self, sym: str, order: dict, reason: str) -> None:
        pos = self.st["positions"].pop(sym)
        base = self.ex.filters(sym)["base"]
        qty, avg, fee = fill_summary(order, base)
        proceeds = qty * avg - fee
        self.st["slots"][sym] = self.st["slots"][sym] - pos["cost"] + proceeds
        ret = proceeds / pos["cost"] - 1
        self.st["trades"].append({
            "symbol": sym, "entry_time": pos["entry_time"], "exit_time": now_iso(),
            "entry_price": pos["entry_price"], "exit_price": avg, "qty": pos["qty"],
            "return_pct": ret * 100, "pnl_usdt": proceeds - pos["cost"], "reason": reason,
            "days": pos["bars_held"],
        })
        self.st["last_exit_bar"][sym] = pos.get("last_bar_done")
        self.log(f"THOÁT {sym} @ {avg:.6g} ({reason}) {ret * 100:+.2f}%")

    def _sell(self, sym: str, reason: str) -> None:
        self._close(sym, self.ex.market_sell(sym, self.st["positions"][sym]["qty"], tag=ORDER_TAG), reason)

    def _place_stop(self, sym: str, pos: dict) -> None:
        try:
            o = self.ex.stop_loss_sell(sym, pos["qty"], pos["stop"], tag=ORDER_TAG)
            pos["stop_order_id"] = o["orderId"]
        except BinanceError as e:
            self.log(f"Không đặt được stop {sym} ({e.payload}); bán market")
            self._sell(sym, "stop")

    def reconcile(self) -> None:
        for sym in list(self.st["positions"]):
            pos = self.st["positions"][sym]
            oid = pos.get("stop_order_id")
            if oid is None:
                self._place_stop(sym, pos)
                continue
            try:
                o = self.ex.get_order(sym, oid)
            except BinanceError as e:
                o = {"status": "NOT_FOUND", "error": str(e.payload)}
            status = o.get("status")
            if status == "FILLED":
                self._close(sym, o, "stop")
            elif status in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                base = self.ex.filters(sym)["base"]
                if self.ex.free(base) < pos["qty"] * 0.5:
                    px = self.ex.price(sym)
                    self._close(sym, {"executedQty": pos["qty"], "cummulativeQuoteQty": pos["qty"] * px,
                                      "fills": []}, "mất (sàn reset)")
                else:
                    self.log(f"Lệnh stop {sym} ở trạng thái {status}; đặt lại")
                    self._place_stop(sym, pos)

    def update_stops(self, bars: dict[str, pd.DataFrame]) -> None:
        for sym in list(self.st["positions"]):
            pos, df = self.st["positions"][sym], bars[sym]
            new = df[df.index > pd.Timestamp(pos["last_bar_done"])]
            if new.empty:
                continue
            old_stop = pos["stop"]
            for t, r in new.iterrows():
                pos["bars_held"] += 1
                pos["hh"] = max(pos["hh"], float(r["high"]))
                pos["stop"] = max(pos["stop"], pos["hh"] - RULE.trail_atr * pos["atr"])
                pos["last_bar_done"] = t.isoformat()
            if pos["bars_held"] >= RULE.max_bars:
                self.ex.cancel_order(sym, pos["stop_order_id"])
                self._sell(sym, "hết 240 ngày")
            elif pos["stop"] > old_stop:
                self.ex.cancel_order(sym, pos["stop_order_id"])
                self.log(f"Nâng stop {sym}: {old_stop:.6g} → {pos['stop']:.6g}")
                self._place_stop(sym, pos)

    def close_all(self, reason: str = "bán tay") -> int:
        self.ex.sync_time()
        self.reconcile()
        n = 0
        for sym in list(self.st["positions"]):
            pos = self.st["positions"][sym]
            if pos.get("stop_order_id") is not None:
                try:
                    self.ex.cancel_order(sym, pos["stop_order_id"])
                except BinanceError as e:
                    self.log(f"Hủy stop {sym} lỗi ({e.payload}); vẫn bán")
            self._sell(sym, reason)
            n += 1
        self.st["paused"] = True
        self.log(f"ĐÃ BÁN HẾT {n} lệnh và TẠM DỪNG bot (chạy tiep_tuc.cmd để bật lại)")
        return n

    def set_paused(self, paused: bool) -> None:
        self.st["paused"] = paused
        self.log("TẠM DỪNG bot: không mua mới, lệnh đang mở vẫn giữ stop" if paused else "BẬT LẠI bot")

    def enter(self, bars: dict[str, pd.DataFrame], last_bar: pd.Timestamp) -> list[str]:
        entered = []
        if self.st.get("paused"):
            self.log("Bot đang tạm dừng: bỏ qua mọi tín hiệu mua")
            return entered
        for sym in self.symbols:
            if sym in self.st["positions"] or sym in UNSUPPORTED:
                continue
            df = bars[sym]
            if df.empty or df.index[-1] != last_bar:
                continue
            sig = VARIANT.signals(df, self.cfg)
            if not bool(sig.iloc[-1]):
                continue
            last_exit = self.st["last_exit_bar"].get(sym)
            if last_exit and pd.Timestamp(last_exit) >= last_bar:
                continue
            atr = float(df["atr"].iloc[-1])
            quote = self.st["slots"][sym]
            f = self.ex.filters(sym)
            if quote < max(f["min_notional"], 5) * 1.5:
                self.log(f"Bỏ qua {sym}: vốn phần này quá nhỏ ({quote:.2f} USDT)")
                continue
            order = self.ex.market_buy_quote(sym, quote * 0.995, tag=ORDER_TAG)
            qty, avg, fee = fill_summary(order, f["base"])
            cost = float(order["cummulativeQuoteQty"]) + (fee if order["fills"] and
                                                           order["fills"][0]["commissionAsset"] == "USDT" else 0)
            pos = {"entry_time": now_iso(), "signal_bar": last_bar.isoformat(), "entry_price": avg,
                   "qty": qty, "cost": cost, "atr": atr, "hh": float("-inf"),
                   "stop": avg - RULE.sl_atr * atr, "bars_held": 0, "last_bar_done": last_bar.isoformat(),
                   "stop_order_id": None}
            self.st["positions"][sym] = pos
            self.log(f"VÀO {sym} @ {avg:.6g}, {qty:g} coin ({cost:.2f} USDT), stop {pos['stop']:.6g}")
            self._place_stop(sym, pos)
            entered.append(sym)
        return entered

    def snapshot(self, bars: dict[str, pd.DataFrame]) -> dict:
        positions, unreal, equity = [], 0.0, 0.0
        for sym in self.symbols:
            slot = self.st["slots"][sym]
            pos = self.st["positions"].get(sym)
            if not pos:
                equity += slot
                continue
            try:
                px = self.ex.price(sym)
            except Exception:
                px = float(bars[sym]["close"].iloc[-1])
            value = pos["qty"] * px * (1 - self.cfg.fee)
            equity += slot - pos["cost"] + value
            unreal += value - pos["cost"]
            positions.append({"symbol": sym, "entry_time": pos["entry_time"], "entry_price": pos["entry_price"],
                              "price": px, "qty": pos["qty"], "stop": pos["stop"], "days": pos["bars_held"],
                              "pnl_pct": (value / pos["cost"] - 1) * 100, "pnl_usdt": value - pos["cost"],
                              "risk_pct": (pos["stop"] / px - 1) * 100})
        return {"equity": equity, "unrealized": unreal, "positions": positions}

    def radar(self, bars: dict[str, pd.DataFrame]) -> list[dict]:
        n = int(VARIANT.entry[len("donchian"):])
        try:
            prices = {x["symbol"]: float(x["price"]) for x in requests.get(
                f"{PUBLIC_API}/ticker/price", timeout=30).json()}
        except Exception:
            prices = {}
        rows = []
        for sym in self.symbols:
            df = bars[sym]
            if len(df) < n or sym in UNSUPPORTED:
                continue
            level = float(df["high"].iloc[-n:].max())
            ema = float(df["ema_trend"].iloc[-1])
            px = prices.get(sym, float(df["close"].iloc[-1]))
            need = max(level, ema)
            if sym in self.st["positions"]:
                status = "Đang giữ"
            elif px > need:
                status = "Đủ điều kiện nếu đóng cửa trên mức này"
            elif px <= ema:
                status = "Dưới EMA200 (xu hướng giảm)"
            else:
                status = "Chờ breakout"
            rows.append({"symbol": sym, "price": px, "breakout": level, "ema200": ema,
                         "gap_pct": (need / px - 1) * 100, "above_ema": px > ema, "status": status})
        return sorted(rows, key=lambda r: (r["status"] == "Đang giữ", r["gap_pct"]))

    def run(self) -> dict:
        self.ex.sync_time()
        self.reconcile()
        bars = {s: self.daily(s) for s in self.symbols}
        last_bar = max(df.index[-1] for df in bars.values() if not df.empty)
        new_day = self.st["last_bar"] is None or pd.Timestamp(self.st["last_bar"]) < last_bar
        entered, signals = [], []
        if new_day:
            self.update_stops(bars)
            entered = self.enter(bars, last_bar)
            self.st["last_bar"] = last_bar.isoformat()
            self.log(f"Đã xử lý nến ngày {last_bar:%Y-%m-%d}: {len(entered)} lệnh mới")
        else:
            self.log(f"Nến ngày {last_bar:%Y-%m-%d} đã xử lý trước đó; chỉ đối chiếu lệnh và cập nhật giá")
        for s in self.symbols:
            df = bars[s]
            if not df.empty and df.index[-1] == last_bar and bool(VARIANT.signals(df, self.cfg).iloc[-1]):
                signals.append(s)
        snap = self.snapshot(bars)
        self.st["equity_curve"].append({"t": now_iso(), "equity": round(snap["equity"], 2)})
        self.st["last_run"] = now_iso()
        account = {}
        try:
            account["usdt"] = self.ex.free("USDT") if self.ex.is_testnet else None
            account["ok"] = True
        except Exception as e:
            account = {"ok": False, "error": str(e)[:200]}
        return {**snap, "last_bar": last_bar.isoformat(), "signals": signals, "entered": entered,
                "radar": self.radar(bars), "account": account}
