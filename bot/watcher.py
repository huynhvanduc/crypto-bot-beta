from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from .fills import fill_from_event, fill_from_rest, iso_ms, key, merge, round_trips

BALANCE_WAIT = 0.5
KEEP = 200


def ntfy_publisher(topic: str, on_error: Callable[[str], None] = print) -> Callable[[dict], None]:
    def publish(payload: dict) -> None:
        try:
            requests.post(f"https://ntfy.sh/{topic}", timeout=5,
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8")).raise_for_status()
        except requests.RequestException as e:
            on_error(f"Gửi ntfy lỗi: {e}")
    return publish


class FillWatcher:
    def __init__(self, ex, publish: Callable[[dict], None], symbols: list[str], topic: str = "",
                 fills_path: Path = Path("live/fills.json"), docs_path: Path = Path("docs/fills.json"),
                 state_path: Path = Path("live/state.json"), clock: Callable[[], float] = time.time):
        self.ex, self.publish, self.symbols, self.topic = ex, publish, list(symbols), topic
        self.fills_path, self.docs_path, self.state_path, self.clock = fills_path, docs_path, state_path, clock
        self.fills: list[dict] = []
        self.usdt: float | None = None
        self.pending: list[tuple[float, dict]] = []
        self.dirty = False
        self.bot_stop_filled = False
        self._order_info: dict[tuple[str, int], tuple[str, str]] = {}

    def load(self) -> None:
        if self.fills_path.exists():
            d = json.loads(self.fills_path.read_text(encoding="utf-8"))
            self.fills, self.usdt = d.get("fills", []), d.get("usdt")

    def save(self) -> None:
        self.fills_path.parent.mkdir(parents=True, exist_ok=True)
        self.fills_path.write_text(json.dumps({"fills": self.fills, "usdt": self.usdt}, ensure_ascii=False),
                                   encoding="utf-8")

    def export(self) -> dict:
        data = {"updated": iso_ms(int(time.time() * 1000)), "topic": self.topic, "usdt": self.usdt,
                "fills": self.fills[-KEEP:][::-1], "round_trips": round_trips(self.fills)}
        self.docs_path.parent.mkdir(parents=True, exist_ok=True)
        self.docs_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.dirty = False
        return data

    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def bot_order_ids(self) -> set[int]:
        return {int(p["stop_order_id"]) for p in self._state().get("positions", {}).values()
                if p.get("stop_order_id") is not None}

    def _start_ms(self) -> int:
        s = self._state().get("start")
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000) if s else 0

    def backfill(self) -> int:
        bot_ids, start = self.bot_order_ids(), self._start_ms()
        new = []
        for sym in sorted(set(self.symbols) | {f["symbol"] for f in self.fills}):
            known = [f["trade_id"] for f in self.fills if f["symbol"] == sym]
            for t in self.ex.my_trades(sym, from_id=max(known) + 1 if known else None):
                if not known and t["time"] < start:
                    continue
                k = (sym, int(t["orderId"]))
                if k not in self._order_info:
                    o = self.ex.get_order(sym, int(t["orderId"]))
                    self._order_info[k] = (o.get("clientOrderId", ""), o.get("type", ""))
                new.append(fill_from_rest(t, *self._order_info[k], bot_ids))
        self.usdt = self.ex.free("USDT")
        before = len(self.fills)
        self.fills = merge(self.fills, new)
        added = len(self.fills) - before
        if added:
            self.dirty = True
            self.save()
        return added

    def poll(self) -> list[dict]:
        known = {key(f) for f in self.fills}
        self.backfill()
        new = [f for f in self.fills if key(f) not in known]
        for f in new:
            self.publish({"v": 1, "kind": "fill", "fill": f, "usdt": self.usdt})
            if f["source"] == "d1" and f["type"] == "STOP_LOSS":
                self.bot_stop_filled = True
        return new

    def handle(self, frame: dict) -> list[dict]:
        ev = frame.get("event")
        if not isinstance(ev, dict):
            return []
        kind = ev.get("e")
        if kind == "eventStreamTerminated":
            raise ConnectionError("Sàn đã ngắt luồng sự kiện")
        if kind == "executionReport":
            f = fill_from_event(ev, self.bot_order_ids())
            if f:
                self.pending.append((self.clock() + BALANCE_WAIT, f))
                if f["source"] == "d1" and ev.get("o") == "STOP_LOSS" and ev.get("X") == "FILLED":
                    self.bot_stop_filled = True
            return []
        if kind == "outboundAccountPosition":
            for b in ev.get("B", []):
                if b.get("a") == "USDT":
                    self.usdt = float(b["f"]) + float(b["l"])
            return self._flush(everything=True)
        return []

    def tick(self) -> list[dict]:
        return self._flush(everything=False)

    def _flush(self, everything: bool) -> list[dict]:
        now = self.clock()
        due = [f for t, f in self.pending if everything or t <= now]
        self.pending = [(t, f) for t, f in self.pending if not (everything or t <= now)]
        known = {key(f) for f in self.fills}
        out = list({key(f): f for f in due if key(f) not in known}.values())
        if not out:
            return []
        self.fills = merge(self.fills, out)
        for f in out:
            self.publish({"v": 1, "kind": "fill", "fill": f, "usdt": self.usdt})
        self.dirty = True
        self.save()
        return out
