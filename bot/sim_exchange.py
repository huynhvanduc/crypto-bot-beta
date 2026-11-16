from __future__ import annotations

import time

import requests

from .data import PUBLIC_API as DATA_URL
from .exchange import parse_filters, round_step

FEE = 0.001


class SimExchange:
    is_testnet = False
    has_keys = True

    def __init__(self, orders: dict):
        self.orders = orders
        self._filters: dict = {}

    def sync_time(self) -> None:
        pass

    def filters(self, symbol: str) -> dict:
        if symbol not in self._filters:
            info = requests.get(f"{DATA_URL}/exchangeInfo", params={"symbol": symbol}, timeout=30).json()["symbols"][0]
            self._filters[symbol] = parse_filters(info)
        return self._filters[symbol]

    def price(self, symbol: str) -> float:
        return float(requests.get(f"{DATA_URL}/ticker/price", params={"symbol": symbol}, timeout=30).json()["price"])

    def free(self, asset: str) -> float:
        return 1e12

    def _fill(self, symbol: str, side: str, qty: float, price: float) -> dict:
        base = self.filters(symbol)["base"]
        quote = qty * price
        fee_asset, fee = (base, qty * FEE) if side == "BUY" else ("USDT", quote * FEE)
        oid = int(time.time() * 1000)
        return {"orderId": oid, "status": "FILLED", "executedQty": str(qty), "cummulativeQuoteQty": str(quote),
                "fills": [{"commission": str(fee), "commissionAsset": fee_asset}]}

    def market_buy_quote(self, symbol: str, quote_amount: float, tag: str | None = None) -> dict:
        p = self.price(symbol)
        qty = float(round_step(quote_amount / p, self.filters(symbol)["step"]))
        return self._fill(symbol, "BUY", qty, p)

    def market_sell(self, symbol: str, qty: float, tag: str | None = None) -> dict:
        qty = float(round_step(qty, self.filters(symbol)["step"]))
        return self._fill(symbol, "SELL", qty, self.price(symbol))

    def stop_loss_sell(self, symbol: str, qty: float, stop_price: float, tag: str | None = None) -> dict:
        f = self.filters(symbol)
        oid = int(time.time() * 1000)
        self.orders[str(oid)] = {"symbol": symbol, "qty": float(round_step(qty, f["step"])),
                                 "stop": float(round_step(stop_price, f["tick"])),
                                 "placed_ms": oid, "status": "NEW"}
        time.sleep(0.002)
        return {"orderId": oid, "status": "NEW"}

    def get_order(self, symbol: str, order_id: int) -> dict:
        o = self.orders.get(str(order_id))
        if o is None:
            return {"status": "NOT_FOUND"}
        if o["status"] == "NEW":
            bars = requests.get(f"{DATA_URL}/klines", params={
                "symbol": symbol, "interval": "1h", "startTime": o["placed_ms"], "limit": 1000}, timeout=30).json()
            for k in bars:
                op, low = float(k[1]), float(k[3])
                if low <= o["stop"]:
                    px = op if op < o["stop"] else o["stop"]
                    o.update(status="FILLED", fill=self._fill(symbol, "SELL", o["qty"], px))
                    break
        if o["status"] == "FILLED":
            return {**o["fill"], "status": "FILLED"}
        return {"orderId": order_id, "status": o["status"]}

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        o = self.orders.get(str(order_id))
        if o and o["status"] == "NEW":
            o["status"] = "CANCELED"
        return {"orderId": order_id, "status": "CANCELED"}
