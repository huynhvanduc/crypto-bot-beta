from __future__ import annotations

import hashlib
import hmac
import itertools
import os
import time
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from urllib.parse import urlencode

import requests

TESTNET_URL = "https://testnet.binance.vision"
_SEQ = itertools.count()


def client_id(tag: str | None) -> str | None:
    if not tag:
        return None
    return f"{tag}-{int(time.time() * 1000)}-{next(_SEQ) % 1000}"


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def round_step(value: float, step: str) -> str:
    d_step = Decimal(step).normalize()
    q = (Decimal(str(value)) / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
    return format(q.quantize(d_step) if d_step.as_tuple().exponent < 0 else q, "f")


def parse_filters(info: dict) -> dict:
    f = {x["filterType"]: x for x in info["filters"]}
    notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
    return {
        "base": info["baseAsset"], "quote": info["quoteAsset"],
        "step": f["LOT_SIZE"]["stepSize"], "min_qty": float(f["LOT_SIZE"]["minQty"]),
        "tick": f["PRICE_FILTER"]["tickSize"],
        "min_notional": float(notional.get("minNotional", 0)),
        "order_types": info["orderTypes"],
    }


class BinanceError(RuntimeError):
    def __init__(self, status: int, payload):
        self.status, self.payload = status, payload
        super().__init__(f"HTTP {status}: {payload}")

    @property
    def code(self):
        return self.payload.get("code") if isinstance(self.payload, dict) else None


class BinanceSpot:
    def __init__(self, key: str | None = None, secret: str | None = None, base_url: str | None = None):
        load_env()
        self.key = key or os.environ.get("BINANCE_API_KEY", "")
        self.secret = secret or os.environ.get("BINANCE_API_SECRET", "")
        self.base = (base_url or os.environ.get("BINANCE_BASE_URL") or TESTNET_URL).rstrip("/")
        self.s = requests.Session()
        self._offset = 0
        self._filters: dict = {}

    @property
    def is_testnet(self) -> bool:
        return "testnet" in self.base

    @property
    def has_keys(self) -> bool:
        return bool(self.key and self.secret)

    def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {}
        if signed:
            if not self.has_keys:
                raise RuntimeError("Thiếu BINANCE_API_KEY / BINANCE_API_SECRET trong .env")
            params["timestamp"] = int(time.time() * 1000) + self._offset
            params["recvWindow"] = 10000
            q = urlencode(params)
            params_str = f"{q}&signature={sign(self.secret, q)}"
            headers["X-MBX-APIKEY"] = self.key
        else:
            params_str = urlencode(params)
        url = f"{self.base}{path}" + (f"?{params_str}" if params_str else "")
        r = self.s.request(method, url, headers=headers, timeout=30)
        try:
            data = r.json()
        except ValueError:
            data = r.text
        if r.status_code >= 400:
            raise BinanceError(r.status_code, data)
        return data

    def sync_time(self) -> None:
        server = self._request("GET", "/api/v3/time")["serverTime"]
        self._offset = server - int(time.time() * 1000)

    def filters(self, symbol: str) -> dict:
        if symbol not in self._filters:
            info = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})["symbols"][0]
            self._filters[symbol] = parse_filters(info)
        return self._filters[symbol]

    def price(self, symbol: str) -> float:
        return float(self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})["price"])

    def _balances(self) -> list[dict]:
        return self._request("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)["balances"]

    def balances(self) -> dict[str, float]:
        return {b["asset"]: float(b["free"]) + float(b["locked"]) for b in self._balances()}

    def free(self, asset: str) -> float:
        for b in self._balances():
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    def _order(self, tag: str | None, **params) -> dict:
        return self._request("POST", "/api/v3/order", {**params, "newClientOrderId": client_id(tag)}, signed=True)

    def market_buy_quote(self, symbol: str, quote_amount: float, tag: str | None = None) -> dict:
        return self._order(tag, symbol=symbol, side="BUY", type="MARKET",
                           quoteOrderQty=round_step(quote_amount, "0.01"), newOrderRespType="FULL")

    def market_sell(self, symbol: str, qty: float, tag: str | None = None) -> dict:
        return self._order(tag, symbol=symbol, side="SELL", type="MARKET",
                           quantity=round_step(qty, self.filters(symbol)["step"]), newOrderRespType="FULL")

    def stop_loss_sell(self, symbol: str, qty: float, stop_price: float, tag: str | None = None) -> dict:
        f = self.filters(symbol)
        return self._order(tag, symbol=symbol, side="SELL", type="STOP_LOSS",
                           quantity=round_step(qty, f["step"]), stopPrice=round_step(stop_price, f["tick"]))

    def my_trades(self, symbol: str, from_id: int | None = None, limit: int = 1000) -> list[dict]:
        return self._request("GET", "/api/v3/myTrades",
                             {"symbol": symbol, "fromId": from_id, "limit": limit}, signed=True)

    def get_order(self, symbol: str, order_id: int) -> dict:
        return self._request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        return self._request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)


def fill_summary(order: dict, base_asset: str) -> tuple[float, float, float]:
    qty = float(order.get("executedQty", 0))
    quote = float(order.get("cummulativeQuoteQty", 0))
    avg = quote / qty if qty else 0.0
    fee = lambda asset: sum(float(f["commission"]) for f in order.get("fills", []) if f["commissionAsset"] == asset)
    fee_base, fee_quote = fee(base_asset), fee("USDT")
    return qty - fee_base, avg, fee_quote + fee_base * avg
