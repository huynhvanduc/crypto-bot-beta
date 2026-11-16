from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

from .data import PUBLIC_API
from .exchange import BinanceError, fill_summary
from .indicators import atr, ema
from .live import now_iso

TAG = "tg"
STOP_ATR = 2.0


def _closed(symbol: str, interval: str, limit: int, get=requests.get) -> pd.DataFrame:
    r = get(f"{PUBLIC_API}/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    rows = [[float(x[2]), float(x[3]), float(x[4])] for x in r.json()]
    return pd.DataFrame(rows, columns=["high", "low", "close"]).iloc[:-1]


def hourly_atr(symbol: str) -> float:
    return float(atr(_closed(symbol, "1h", 100), 14).iloc[-1])


def recovery() -> tuple[bool, str]:
    h, d = _closed("BTCUSDT", "1h", 400), _closed("BTCUSDT", "1d", 30)
    e = ema(h["close"], 200).iloc[-1]
    above = h["close"].iloc[-1] > e
    prior_low = d["low"].iloc[-7:-1].min()
    holds = d["low"].iloc[-1] > prior_low
    info = (f"BTC 1h đóng {h['close'].iloc[-1]:,.0f} {'>' if above else '≤'} EMA200 {e:,.0f}; "
            f"đáy ngày qua {d['low'].iloc[-1]:,.0f} {'giữ trên' if holds else 'thủng'} đáy 6 ngày trước {prior_low:,.0f}")
    return bool(above and holds), info


class ManualTrader:
    def __init__(self, ex, path=Path("live/manual.json"), atr_fn=hourly_atr):
        if not ex.is_testnet:
            raise RuntimeError("Chỉ giao dịch trên testnet")
        self.ex, self.path, self.atr_fn = ex, Path(path), atr_fn
        self.pos = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.pos, ensure_ascii=False, indent=1), encoding="utf-8")

    def buy(self, symbol: str, usdt: float) -> str:
        if symbol in self.pos:
            return f"Đã có lệnh {symbol} đang mở — không mua thêm."
        base = self.ex.filters(symbol)["base"]
        order = self.ex.market_buy_quote(symbol, usdt, tag=TAG)
        qty, avg, _ = fill_summary(order, base)
        stop = avg - STOP_ATR * self.atr_fn(symbol)
        p = {"qty": qty, "entry": avg, "cost": float(order["cummulativeQuoteQty"]), "stop": stop,
             "stop_order_id": None, "time": now_iso()}
        note = ""
        try:
            p["stop_order_id"] = self.ex.stop_loss_sell(symbol, qty, stop, tag=TAG)["orderId"]
        except BinanceError as e:
            note = f"\nKHÔNG đặt được stop ({e.payload}) — cần bán tay nếu giá giảm."
        self.pos[symbol] = p
        self.save()
        return (f"Đã MUA {qty:g} {base} giá {avg:,.4f} ({p['cost']:,.2f} USDT). "
                f"Stop {stop:,.4f} ({(stop / avg - 1) * 100:+.1f}%) nằm sẵn trên sàn." + note)

    def _result(self, symbol: str, order: dict, how: str) -> str:
        p = self.pos.pop(symbol)
        self.save()
        qty, avg, fee = fill_summary(order, self.ex.filters(symbol)["base"])
        pnl = qty * avg - fee - p["cost"]
        return f"{how} {qty:g} {symbol} giá {avg:,.4f}: lãi/lỗ {pnl:+.2f} USDT ({pnl / p['cost'] * 100:+.2f}%)."

    def sell(self, symbol: str) -> str:
        p = self.pos.get(symbol)
        if not p:
            return f"Không có lệnh {symbol} đang mở."
        if p["stop_order_id"] is not None:
            try:
                self.ex.cancel_order(symbol, p["stop_order_id"])
            except BinanceError:
                pass
        return self._result(symbol, self.ex.market_sell(symbol, p["qty"], tag=TAG), "Đã BÁN")

    def check_stops(self) -> list[str]:
        out = []
        for symbol, p in list(self.pos.items()):
            if p["stop_order_id"] is None:
                continue
            o = self.ex.get_order(symbol, p["stop_order_id"])
            if o.get("status") == "FILLED":
                out.append(self._result(symbol, o, f"Stop {symbol} đã khớp:"))
        return out

    def status(self) -> str:
        if not self.pos:
            return "Không có lệnh nào đang mở."
        return "\n".join(f"{s}: {p['qty']:g} giá vào {p['entry']:,.4f}, stop {p['stop']:,.4f}, mua lúc {p['time']}"
                         for s, p in self.pos.items())
