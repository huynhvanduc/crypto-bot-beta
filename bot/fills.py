from __future__ import annotations

from datetime import datetime, timezone


def iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def classify(client_id: str | None, order_id: int, bot_order_ids: set[int]) -> str:
    cid = client_id or ""
    if cid.startswith("d1-") or order_id in bot_order_ids:
        return "d1"
    if cid.startswith("scalp-"):
        return "scalp"
    return "tay"


def _fill(symbol, trade_id, order_id, client_id, side, order_type, qty, price, quote, fee, fee_asset, ms,
          bot_order_ids) -> dict:
    return {"trade_id": int(trade_id), "order_id": int(order_id), "client_id": client_id or "",
            "symbol": symbol, "side": side, "type": order_type, "qty": float(qty), "price": float(price),
            "quote": float(quote), "fee": float(fee), "fee_asset": fee_asset or "", "time": iso_ms(int(ms)),
            "ms": int(ms), "source": classify(client_id, int(order_id), bot_order_ids)}


def fill_from_event(ev: dict, bot_order_ids: set[int] = frozenset()) -> dict | None:
    if ev.get("e") != "executionReport" or ev.get("x") != "TRADE":
        return None
    return _fill(ev["s"], ev["t"], ev["i"], ev.get("c"), ev["S"], ev["o"], ev["l"], ev["L"], ev["Y"],
                 ev["n"], ev.get("N"), ev["T"], bot_order_ids)


def fill_from_rest(t: dict, client_id: str | None, order_type: str,
                   bot_order_ids: set[int] = frozenset()) -> dict:
    return _fill(t["symbol"], t["id"], t["orderId"], client_id, "BUY" if t["isBuyer"] else "SELL", order_type,
                 t["qty"], t["price"], t["quoteQty"], t["commission"], t["commissionAsset"], t["time"],
                 bot_order_ids)


def key(f: dict) -> tuple[str, int]:
    return f["symbol"], f["trade_id"]


def _chrono(f: dict) -> tuple[int, int]:
    return f["ms"], f["trade_id"]


def merge(fills: list[dict], new: list[dict]) -> list[dict]:
    seen = {key(f) for f in fills}
    out = list(fills)
    for f in new:
        if key(f) not in seen:
            seen.add(key(f))
            out.append(f)
    return sorted(out, key=_chrono)


def _base(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _orders(fills: list[dict]) -> list[dict]:
    out: dict[tuple[str, int], dict] = {}
    for f in sorted(fills, key=_chrono):
        if f["source"] == "d1":
            continue
        o = out.setdefault((f["symbol"], f["order_id"]), {
            "symbol": f["symbol"], "source": f["source"], "side": f["side"], "time": f["time"], "ms": f["ms"],
            "qty": 0.0, "quote": 0.0, "fee_base": 0.0, "fee_usdt": 0.0})
        o["qty"] += f["qty"]
        o["quote"] += f["quote"]
        if f["fee_asset"] == _base(f["symbol"]):
            o["fee_base"] += f["fee"]
        elif f["fee_asset"] == "USDT":
            o["fee_usdt"] += f["fee"]
    return sorted(out.values(), key=lambda o: o["ms"])


def round_trips(fills: list[dict]) -> dict:
    lots: dict[str, list[dict]] = {}
    trades: list[dict] = []
    for o in _orders(fills):
        sym, price = o["symbol"], o["quote"] / o["qty"]
        if o["side"] == "BUY":
            lots.setdefault(sym, []).append({"qty": o["qty"] - o["fee_base"], "cost": o["quote"] + o["fee_usdt"],
                                             "price": price, "time": o["time"], "source": o["source"]})
            continue
        eps = o["qty"] * 1e-9
        net_per_coin = (o["quote"] - o["fee_usdt"] - o["fee_base"] * price) / o["qty"]
        left, mq, mcost, mgross, first = o["qty"], 0.0, 0.0, 0.0, None
        queue = lots.get(sym, [])
        while left > eps and queue:
            lot = queue[0]
            take = min(left, lot["qty"])
            unit = lot["cost"] / lot["qty"]
            mq, mcost, mgross = mq + take, mcost + take * unit, mgross + take * lot["price"]
            first = first or lot["time"]
            lot["qty"] -= take
            lot["cost"] -= take * unit
            left -= take
            if lot["qty"] <= eps:
                queue.pop(0)
        base = {"symbol": sym, "source": o["source"], "exit_time": o["time"], "exit_price": price}
        if mq > eps:
            pnl = mq * net_per_coin - mcost
            trades.append({**base, "entry_time": first, "qty": mq, "entry_price": mgross / mq,
                           "pnl_usdt": pnl, "return_pct": pnl / mcost * 100})
        if left > eps:
            trades.append({**base, "entry_time": None, "qty": left, "entry_price": None,
                           "pnl_usdt": None, "return_pct": None})
    open_ = [{"symbol": s, "source": lot["source"], "qty": lot["qty"], "entry_price": lot["price"],
              "cost": lot["cost"], "entry_time": lot["time"]} for s, q in lots.items() for lot in q]
    done = [t["pnl_usdt"] for t in trades if t["pnl_usdt"] is not None]
    return {"trades": trades[::-1], "open": open_, "pnl_usdt": sum(done), "count": len(done)}
