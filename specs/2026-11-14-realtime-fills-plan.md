# Cập nhật lệnh mua bán real time — Kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mọi lệnh khớp trên tài khoản Binance Spot Testnet hiện trên dashboard GitHub Pages trong 1–3 giây (cả điện thoại); lệnh tay/lướt sóng có mục lãi/lỗ riêng.

**Architecture:** `watch.py` chạy nền trên máy, nghe `executionReport` qua WebSocket API testnet (`userDataStream.subscribe.signature`), phát từng lệnh khớp lên ntfy.sh và gom đẩy `docs/fills.json` lên GitHub. Logic thuần (chuẩn hóa, phân loại, FIFO) nằm ở `bot/fills.py`; trạng thái và I/O tệp ở `bot/watcher.py` (mạng được truyền vào để test); `docs/index.html` nghe ntfy bằng `EventSource` và đọc `fills.json`.

**Tech Stack:** Python 3.13, `requests`, `websocket-client` 1.9, pytest; HTML/JS thuần (không build); ntfy.sh; GitHub Pages.

**Spec:** `specs/2026-11-14-realtime-fills-design.md`

## Global Constraints

- Chạy mọi lệnh từ `D:\LearnCode\bot` (Git Bash: `cd /d/LearnCode/bot`); Python là `.venv/Scripts/python`.
- Test: `.venv/Scripts/python -m pytest` (pyproject đã đặt `pythonpath = ["."]`, `testpaths = ["tests"]`).
- Mặc định **testnet**; không bao giờ in `BINANCE_API_KEY`/`BINANCE_API_SECRET`.
- `docs/` được đăng công khai lên GitHub Pages — không đặt spec/kế hoạch/bí mật trong đó.
- Chữ hiển thị và log bằng tiếng Việt, giống code hiện có.
- `newClientOrderId` tối đa 36 ký tự, chỉ `[.A-Za-z0-9:/_-]`; tiền tố `d1-` (bot), `scalp-` (lướt sóng).
- Dashboard chỉ tin tin ntfy có `fill.ms` > `fills.updated − 5 giây` và `fill.ms` < bây giờ + 60 giây.
- Gom đẩy GitHub tối đa 1 lần/60 giây; chạy lại bot khi stop khớp tối đa 1 lần/60 giây.
- Commit chỉ đúng file của task (`git add <file cụ thể>`); không đụng `.env.example` (người dùng đã xóa, chưa commit).

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `ban_het.cmd`, `tam_dung.cmd`, `tiep_tuc.cmd` | Sửa dòng `cd` hỏng |
| `bot/exchange.py` | `client_id(tag)`, tham số `tag` cho lệnh, `my_trades()` |
| `bot/sim_exchange.py` | Nhận `tag` (bỏ qua) để giữ interface |
| `bot/live.py` | Gắn `tag="d1"` cho mọi lệnh của bot |
| `bot/fills.py` (mới) | Chuẩn hóa lệnh khớp (WS/REST), phân loại nguồn, gộp, ghép cặp FIFO — thuần, không mạng |
| `bot/filelock.py` (mới) | Khóa liên tiến trình `live/git.lock` |
| `bot/watcher.py` (mới) | `FillWatcher`: lấy bù REST, xử lý khung WS, chờ số dư, phát tin, ghi `live/fills.json` + `docs/fills.json` |
| `watch.py` (mới) | Vòng lặp WebSocket, nối lại, đẩy GitHub nền, chạy bot khi stop khớp |
| `theo_doi.cmd` (mới) | Chạy `watch.py`, tự chạy lại |
| `live_trade.py` | Giữ khóa suốt lần chạy |
| `docs/index.html` | Thẻ "Khớp lệnh trực tiếp", "Lệnh khác", số dư testnet, `EventSource` ntfy |
| `scalp60.py` (mới, chép từ scratchpad) | Phiên lướt sóng 60 giây, lệnh gắn `scalp` |
| `tests/test_exchange_tags.py`, `tests/test_fills.py`, `tests/test_filelock.py`, `tests/test_watcher.py` (mới) | Test |
| `requirements.txt`, `README.md` | `websocket-client`, hướng dẫn |

---

### Task 1: Sửa 3 file .cmd bị hỏng dòng `cd`

**Files:**
- Modify: `ban_het.cmd:3`, `tam_dung.cmd:3`, `tiep_tuc.cmd:3`

**Interfaces:** không.

Dòng 3 của cả ba file hiện là `cd /d D:\LearnCode` + byte `0x08` + `ot` (chuỗi `\b` từng bị hiểu là backspace). Thay bằng `cd /d "%~dp0"` (thư mục chứa file .cmd) — đúng dù repo ở đâu.

- [ ] **Step 1: Xác nhận lỗi**

Run: `grep -c $'\x08' ban_het.cmd tam_dung.cmd tiep_tuc.cmd`
Expected: `ban_het.cmd:1`, `tam_dung.cmd:1`, `tiep_tuc.cmd:1`

- [ ] **Step 2: Sửa bằng thay byte (giữ CRLF)**

```bash
.venv/Scripts/python -c '
from pathlib import Path
for n in ["ban_het.cmd", "tam_dung.cmd", "tiep_tuc.cmd"]:
    p = Path(n); b = p.read_bytes()
    new = b.replace(b"cd /d D:\\LearnCode\x08ot", b"cd /d \"%~dp0\"")
    assert new != b, n
    p.write_bytes(new); print(n, "ok")
'
```
Expected: ba dòng `... ok`

- [ ] **Step 3: Kiểm tra**

Run: `grep -c $'\x08' ban_het.cmd tam_dung.cmd tiep_tuc.cmd; cat -A ban_het.cmd | sed -n 3p`
Expected: ba file `:0`, và `cd /d "%~dp0"^M$`
(Không chạy thử các file này — `ban_het.cmd` bán hết coin.)

- [ ] **Step 4: Commit**

```bash
git add ban_het.cmd tam_dung.cmd tiep_tuc.cmd
git commit -m "Sửa dòng cd hỏng (ký tự backspace) trong ban_het/tam_dung/tiep_tuc.cmd"
```

---

### Task 2: Gắn nhãn lệnh và hàm `my_trades`

**Files:**
- Modify: `bot/exchange.py` (đầu file + các hàm lệnh ở dòng 132–151)
- Modify: `bot/sim_exchange.py:57-75`
- Modify: `bot/live.py` (hằng `ORDER_TAG`, 5 lời gọi lệnh ở dòng 85, 90, 132, 150, 183)
- Test: `tests/test_exchange_tags.py`

**Interfaces:**
- Produces: `bot.exchange.client_id(tag: str | None) -> str | None`;
  `BinanceSpot.market_buy_quote(symbol, quote_amount, tag=None)`, `market_sell(symbol, qty, tag=None)`,
  `stop_loss_sell(symbol, qty, stop_price, tag=None)`;
  `BinanceSpot.my_trades(symbol: str, from_id: int | None = None, limit: int = 1000) -> list[dict]`;
  `bot.live.ORDER_TAG = "d1"`.

- [ ] **Step 1: Viết test hỏng**

`tests/test_exchange_tags.py`:
```python
import inspect

from bot.exchange import BinanceSpot, client_id
from bot.live import LiveTrader
from bot.sim_exchange import SimExchange


class Rec(BinanceSpot):
    """BinanceSpot không gọi mạng: ghi lại mọi request."""

    def __init__(self):
        super().__init__(key="k", secret="s", base_url="https://testnet.binance.vision")
        self.calls = []
        self._filters = {"BTCUSDT": {"base": "BTC", "quote": "USDT", "step": "0.00001", "min_qty": 0.00001,
                                     "tick": "0.01", "min_notional": 5.0, "order_types": []}}

    def _request(self, method, path, params=None, signed=False):
        self.calls.append((method, path, params))
        return {"orderId": 1}


def test_client_id_format():
    a, b = client_id("d1"), client_id("d1")
    assert a.startswith("d1-") and len(a) <= 36 and a != b
    assert client_id(None) is None and client_id("") is None


def test_orders_carry_tag():
    ex = Rec()
    ex.market_buy_quote("BTCUSDT", 100, tag="scalp")
    ex.market_sell("BTCUSDT", 0.001, tag="d1")
    ex.stop_loss_sell("BTCUSDT", 0.001, 60000, tag="d1")
    ids = [p["newClientOrderId"] for _, _, p in ex.calls]
    assert ids[0].startswith("scalp-") and ids[1].startswith("d1-") and ids[2].startswith("d1-")


def test_no_tag_sends_no_client_id():
    ex = Rec()
    ex.market_sell("BTCUSDT", 0.001)
    assert ex.calls[0][2].get("newClientOrderId") is None  # _request thật bỏ tham số None


def test_my_trades_request():
    ex = Rec()
    ex.my_trades("BTCUSDT", from_id=5)
    assert ex.calls[0] == ("GET", "/api/v3/myTrades", {"symbol": "BTCUSDT", "fromId": 5, "limit": 1000})


def test_sim_exchange_accepts_tag():
    for name in ("market_buy_quote", "market_sell", "stop_loss_sell"):
        assert "tag" in inspect.signature(getattr(SimExchange, name)).parameters


class StopEx:
    def __init__(self):
        self.calls = []

    def stop_loss_sell(self, sym, qty, stop, tag=None):
        self.calls.append(tag)
        return {"orderId": 1}


def test_bot_tags_its_orders():
    ex = StopEx()
    LiveTrader(ex, {"slots": {"BTCUSDT": 100.0}, "log": [], "positions": {}})._place_stop(
        "BTCUSDT", {"qty": 0.001, "stop": 60000.0})
    assert ex.calls == ["d1"]
```

- [ ] **Step 2: Chạy để thấy hỏng**

Run: `.venv/Scripts/python -m pytest tests/test_exchange_tags.py -v`
Expected: FAIL — `ImportError: cannot import name 'client_id' from 'bot.exchange'`

- [ ] **Step 3: Sửa `bot/exchange.py`**

Thêm `import itertools` vào khối import (sau `import hmac`). Sau dòng `TESTNET_URL = "https://testnet.binance.vision"` thêm:
```python
_SEQ = itertools.count()


def client_id(tag: str | None) -> str | None:
    """newClientOrderId '<tag>-<ms>-<n>' để biết lệnh do ai đặt (Binance cho tối đa 36 ký tự)."""
    if not tag:
        return None
    return f"{tag}-{int(time.time() * 1000)}-{next(_SEQ) % 1000}"
```
Thay toàn bộ 3 hàm lệnh (`market_buy_quote`, `market_sell`, `stop_loss_sell`) bằng:
```python
    def market_buy_quote(self, symbol: str, quote_amount: float, tag: str | None = None) -> dict:
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": round_step(quote_amount, "0.01"), "newOrderRespType": "FULL",
            "newClientOrderId": client_id(tag),
        }, signed=True)

    def market_sell(self, symbol: str, qty: float, tag: str | None = None) -> dict:
        f = self.filters(symbol)
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": round_step(qty, f["step"]), "newOrderRespType": "FULL",
            "newClientOrderId": client_id(tag),
        }, signed=True)

    def stop_loss_sell(self, symbol: str, qty: float, stop_price: float, tag: str | None = None) -> dict:
        """Lệnh STOP_LOSS nằm trên sàn: giá chạm stop_price thì bán market, kể cả khi bot đang tắt."""
        f = self.filters(symbol)
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "STOP_LOSS",
            "quantity": round_step(qty, f["step"]), "stopPrice": round_step(stop_price, f["tick"]),
            "newClientOrderId": client_id(tag),
        }, signed=True)

    def my_trades(self, symbol: str, from_id: int | None = None, limit: int = 1000) -> list[dict]:
        """Lệnh khớp của tài khoản; from_id=None → các lệnh gần nhất."""
        return self._request("GET", "/api/v3/myTrades",
                             {"symbol": symbol, "fromId": from_id, "limit": limit}, signed=True)
```

- [ ] **Step 4: Sửa `bot/sim_exchange.py`**

Đổi chữ ký 3 hàm (thân giữ nguyên):
```python
    def market_buy_quote(self, symbol: str, quote_amount: float, tag: str | None = None) -> dict:
    def market_sell(self, symbol: str, qty: float, tag: str | None = None) -> dict:
    def stop_loss_sell(self, symbol: str, qty: float, stop_price: float, tag: str | None = None) -> dict:
```

- [ ] **Step 5: Sửa `bot/live.py`**

Sau dòng `UNSUPPORTED = {"EOSUSDT"}  # không có trên testnet / đã bị gỡ` thêm:
```python
ORDER_TAG = "d1"  # tiền tố clientOrderId để watch.py nhận ra lệnh của bot
```
Thay các lời gọi:
- `o = self.ex.stop_loss_sell(sym, pos["qty"], pos["stop"])` → `o = self.ex.stop_loss_sell(sym, pos["qty"], pos["stop"], tag=ORDER_TAG)`
- cả 3 chỗ `self.ex.market_sell(sym, pos["qty"])` → `self.ex.market_sell(sym, pos["qty"], tag=ORDER_TAG)`
  (Edit với `replace_all: true`)
- `order = self.ex.market_buy_quote(sym, quote * 0.995)  # chừa chỗ cho làm tròn` → `order = self.ex.market_buy_quote(sym, quote * 0.995, tag=ORDER_TAG)  # chừa chỗ cho làm tròn`

Run: `grep -n "market_sell\|market_buy_quote\|stop_loss_sell" bot/live.py`
Expected: 5 dòng, dòng nào cũng có `tag=ORDER_TAG`.

- [ ] **Step 6: Chạy test**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `29 passed`

- [ ] **Step 7: Commit**

```bash
git add bot/exchange.py bot/sim_exchange.py bot/live.py tests/test_exchange_tags.py
git commit -m "Gắn nhãn clientOrderId cho lệnh (d1-/scalp-) và thêm my_trades"
```

---

### Task 3: `bot/fills.py` — chuẩn hóa, phân loại, gộp lệnh khớp

**Files:**
- Create: `bot/fills.py`
- Test: `tests/test_fills.py`

**Interfaces:**
- Produces (bản ghi lệnh khớp — dùng ở mọi task sau, kể cả JSON cho trang web):
  `{"trade_id": int, "order_id": int, "client_id": str, "symbol": str, "side": "BUY"|"SELL", "type": str, "qty": float, "price": float, "quote": float, "fee": float, "fee_asset": str, "time": str ISO-UTC mili giây "…Z", "ms": int, "source": "d1"|"scalp"|"tay"}`
- `classify(client_id: str | None, order_id: int, bot_order_ids: set[int]) -> str`
- `fill_from_event(ev: dict, bot_order_ids: set[int] = frozenset()) -> dict | None`
- `fill_from_rest(t: dict, client_id: str | None, order_type: str, bot_order_ids: set[int] = frozenset()) -> dict`
- `merge(fills: list[dict], new: list[dict]) -> list[dict]` (bỏ trùng theo `(symbol, trade_id)`, sắp theo `(ms, trade_id)`)

- [ ] **Step 1: Viết test hỏng**

`tests/test_fills.py`:
```python
import pytest

from bot.fills import classify, fill_from_event, fill_from_rest, merge

EV = {"e": "executionReport", "E": 1794669000100, "s": "BTCUSDT", "c": "scalp-1794669000000-1", "S": "BUY",
      "o": "MARKET", "f": "GTC", "q": "0.14421000", "p": "0.00000000", "x": "TRADE", "X": "FILLED",
      "i": 123, "l": "0.14421000", "z": "0.14421000", "L": "65871.90000000", "n": "0.00000000", "N": "BTC",
      "T": 1794669000000, "t": 555, "Z": "9499.39000000", "Y": "9499.39000000"}


def test_fill_from_trade_event():
    assert fill_from_event(EV) == {
        "trade_id": 555, "order_id": 123, "client_id": "scalp-1794669000000-1", "symbol": "BTCUSDT",
        "side": "BUY", "type": "MARKET", "qty": 0.14421, "price": 65871.9, "quote": 9499.39,
        "fee": 0.0, "fee_asset": "BTC", "time": "2026-11-14T15:10:00.000Z", "ms": 1794669000000,
        "source": "scalp"}


def test_non_trade_events_ignored():
    assert fill_from_event({**EV, "x": "NEW"}) is None
    assert fill_from_event({"e": "outboundAccountPosition"}) is None


def test_classify():
    assert classify("d1-1-0", 1, set()) == "d1"
    assert classify("scalp-1-0", 1, set()) == "scalp"
    assert classify("web_abc", 7, {7}) == "d1"  # lệnh stop cũ của bot (trước khi có nhãn)
    assert classify("", 1, set()) == "tay"
    assert classify(None, 1, set()) == "tay"


def test_fill_from_rest_matches_event_shape():
    t = {"symbol": "BTCUSDT", "id": 555, "orderId": 123, "price": "65871.9", "qty": "0.14421",
         "quoteQty": "9499.39", "commission": "0", "commissionAsset": "BTC", "time": 1794669000000,
         "isBuyer": True, "isMaker": False}
    assert fill_from_rest(t, "scalp-1794669000000-1", "MARKET") == fill_from_event(EV)


def test_merge_dedupes_and_sorts():
    a = fill_from_event(EV)
    b = fill_from_event({**EV, "t": 556, "T": 1794668000000})
    assert [f["trade_id"] for f in merge([a], [b, a])] == [556, 555]
```

- [ ] **Step 2: Chạy để thấy hỏng**

Run: `.venv/Scripts/python -m pytest tests/test_fills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.fills'`

- [ ] **Step 3: Viết `bot/fills.py`**

```python
"""Lệnh khớp trên tài khoản: chuẩn hóa từ WebSocket/REST, phân loại nguồn, gộp, ghép cặp FIFO.

Không gọi mạng. Bản ghi một lệnh khớp:
    {trade_id, order_id, client_id, symbol, side, type, qty, price, quote, fee, fee_asset, time, ms, source}
source: "d1" (bot D1), "scalp" (lướt sóng), "tay" (còn lại).
"""
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
    """executionReport loại TRADE → bản ghi; sự kiện khác → None."""
    if ev.get("e") != "executionReport" or ev.get("x") != "TRADE":
        return None
    return _fill(ev["s"], ev["t"], ev["i"], ev.get("c"), ev["S"], ev["o"], ev["l"], ev["L"], ev["Y"],
                 ev["n"], ev.get("N"), ev["T"], bot_order_ids)


def fill_from_rest(t: dict, client_id: str | None, order_type: str,
                   bot_order_ids: set[int] = frozenset()) -> dict:
    """Một phần tử của GET /api/v3/myTrades → bản ghi (clientOrderId/type lấy từ GET /api/v3/order)."""
    return _fill(t["symbol"], t["id"], t["orderId"], client_id, "BUY" if t["isBuyer"] else "SELL", order_type,
                 t["qty"], t["price"], t["quoteQty"], t["commission"], t["commissionAsset"], t["time"],
                 bot_order_ids)


def key(f: dict) -> tuple[str, int]:
    return f["symbol"], f["trade_id"]


def merge(fills: list[dict], new: list[dict]) -> list[dict]:
    seen = {key(f) for f in fills}
    out = list(fills)
    for f in new:
        if key(f) not in seen:
            seen.add(key(f))
            out.append(f)
    return sorted(out, key=lambda f: (f["ms"], f["trade_id"]))
```

- [ ] **Step 4: Chạy test**

Run: `.venv/Scripts/python -m pytest tests/test_fills.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add bot/fills.py tests/test_fills.py
git commit -m "bot/fills.py: chuẩn hóa lệnh khớp WebSocket/REST, phân loại nguồn, gộp"
```

---

### Task 4: `round_trips` — ghép cặp FIFO cho lệnh tay/lướt sóng

**Files:**
- Modify: `bot/fills.py` (thêm cuối file)
- Test: `tests/test_fills.py` (thêm cuối file)

**Interfaces:**
- Consumes: bản ghi lệnh khớp (Task 3).
- Produces: `round_trips(fills: list[dict]) -> dict` =
  `{"trades": [ {symbol, source, entry_time: str|None, exit_time: str, qty, entry_price: float|None, exit_price, pnl_usdt: float|None, return_pct: float|None} … mới nhất trước ],
    "open": [ {symbol, source, qty, entry_price, cost, entry_time} ],
    "pnl_usdt": float, "count": int}`
  Bỏ qua lệnh `source == "d1"`. Các lệnh khớp cùng `(symbol, order_id)` gộp thành một lệnh. Phí mua bằng coin làm giảm số coin của lô; phí bằng USDT cộng vào giá vốn/trừ vào tiền bán; phí bằng coin khác (BNB) bỏ qua. Phần bán vượt số đã mua → cặp có `pnl_usdt = None`, không tính vào tổng.

- [ ] **Step 1: Viết test hỏng** (thêm vào `tests/test_fills.py`; thêm `round_trips` vào dòng import `from bot.fills import ...`)

```python
def F(tid, side, qty, price, oid=None, fee=0.0, fee_asset="USDT", source="tay", sym="BTCUSDT"):
    return {"trade_id": tid, "order_id": tid if oid is None else oid, "client_id": "", "symbol": sym,
            "side": side, "type": "MARKET", "qty": qty, "price": price, "quote": qty * price, "fee": fee,
            "fee_asset": fee_asset, "time": f"t{tid}", "ms": tid, "source": source}


def test_fee_in_coin_on_buy_and_usdt_on_sell():
    r = round_trips([F(1, "BUY", 1.0, 100.0, fee=0.001, fee_asset="BTC"),
                     F(2, "SELL", 0.999, 110.0, fee=0.10989, fee_asset="USDT")])
    (t,) = r["trades"]
    assert t["qty"] == pytest.approx(0.999)
    assert t["entry_price"] == pytest.approx(100.0) and t["exit_price"] == pytest.approx(110.0)
    assert t["pnl_usdt"] == pytest.approx(9.78011) and t["return_pct"] == pytest.approx(9.78011)
    assert r["open"] == [] and r["pnl_usdt"] == pytest.approx(9.78011) and r["count"] == 1


def test_one_sell_spans_two_buys_and_leaves_open_lot():
    r = round_trips([F(1, "BUY", 1.0, 100.0), F(2, "BUY", 1.0, 120.0), F(3, "SELL", 1.5, 130.0)])
    (t,) = r["trades"]
    assert t["qty"] == pytest.approx(1.5) and t["entry_price"] == pytest.approx(106.6666667)
    assert t["pnl_usdt"] == pytest.approx(35.0)
    assert t["entry_time"] == "t1" and t["exit_time"] == "t3"
    (o,) = r["open"]
    assert o["qty"] == pytest.approx(0.5) and o["entry_price"] == pytest.approx(120.0)
    assert o["cost"] == pytest.approx(60.0) and o["entry_time"] == "t2"


def test_selling_preexisting_coins_has_no_pnl():
    r = round_trips([F(1, "SELL", 1.0, 65000.0)])
    (t,) = r["trades"]
    assert t["pnl_usdt"] is None and t["entry_price"] is None and t["entry_time"] is None
    assert r["pnl_usdt"] == 0 and r["count"] == 0


def test_bot_d1_fills_are_excluded():
    r = round_trips([F(1, "BUY", 1.0, 100.0, source="d1"), F(2, "SELL", 1.0, 110.0, source="d1")])
    assert r == {"trades": [], "open": [], "pnl_usdt": 0, "count": 0}


def test_partial_fills_of_one_order_are_combined():
    r = round_trips([F(1, "BUY", 2.0, 100.0), F(2, "SELL", 1.0, 110.0, oid=9), F(3, "SELL", 1.0, 111.0, oid=9)])
    (t,) = r["trades"]
    assert t["qty"] == pytest.approx(2.0) and t["exit_price"] == pytest.approx(110.5)
    assert t["pnl_usdt"] == pytest.approx(21.0)


def test_newest_round_trip_first():
    r = round_trips([F(1, "BUY", 1.0, 100.0), F(2, "SELL", 1.0, 101.0),
                     F(3, "BUY", 1.0, 100.0), F(4, "SELL", 1.0, 99.0)])
    assert [t["exit_time"] for t in r["trades"]] == ["t4", "t2"]
    assert r["pnl_usdt"] == pytest.approx(0.0) and r["count"] == 2
```

- [ ] **Step 2: Chạy để thấy hỏng**

Run: `.venv/Scripts/python -m pytest tests/test_fills.py -v`
Expected: FAIL — `ImportError: cannot import name 'round_trips'`

- [ ] **Step 3: Thêm vào cuối `bot/fills.py`**

```python
def _base(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _orders(fills: list[dict]) -> list[dict]:
    """Gộp các lệnh khớp cùng một lệnh (symbol, order_id), bỏ lệnh của bot D1."""
    out: dict[tuple[str, int], dict] = {}
    for f in sorted(fills, key=lambda f: (f["ms"], f["trade_id"])):
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
        # phí bằng coin khác (BNB…) không quy đổi được ở đây → bỏ qua
    return sorted(out.values(), key=lambda o: o["ms"])


def round_trips(fills: list[dict]) -> dict:
    """Ghép mua–bán FIFO từng coin cho lệnh tay/lướt sóng; mỗi lệnh bán là một cặp."""
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
        if left > eps:  # bán coin có sẵn (vd. số dư mặc định của testnet): không có giá vốn
            trades.append({**base, "entry_time": None, "qty": left, "entry_price": None,
                           "pnl_usdt": None, "return_pct": None})
    open_ = [{"symbol": s, "source": lot["source"], "qty": lot["qty"], "entry_price": lot["price"],
              "cost": lot["cost"], "entry_time": lot["time"]} for s, q in lots.items() for lot in q]
    done = [t["pnl_usdt"] for t in trades if t["pnl_usdt"] is not None]
    return {"trades": trades[::-1], "open": open_, "pnl_usdt": sum(done), "count": len(done)}
```

- [ ] **Step 4: Chạy test**

Run: `.venv/Scripts/python -m pytest tests/test_fills.py -v`
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add bot/fills.py tests/test_fills.py
git commit -m "bot/fills.py: ghép cặp FIFO lệnh tay/lướt sóng, tính lãi lỗ sau phí"
```

---

### Task 5: Khóa liên tiến trình `bot/filelock.py` + `live_trade.py` dùng khóa

**Files:**
- Create: `bot/filelock.py`
- Modify: `live_trade.py` (import + khối `if __name__ == "__main__":` cuối file)
- Test: `tests/test_filelock.py`

**Interfaces:**
- Produces: `file_lock(path: str | Path = "live/git.lock", wait: float = 300.0, stale: float = 1800.0, poll: float = 0.5)` (context manager), `LockTimeout(RuntimeError)`.

- [ ] **Step 1: Viết test hỏng**

`tests/test_filelock.py`:
```python
import os
import time

import pytest

from bot.filelock import LockTimeout, file_lock


def test_lock_created_and_removed(tmp_path):
    p = tmp_path / "x.lock"
    with file_lock(p, wait=1):
        assert p.exists()
    assert not p.exists()


def test_second_holder_times_out(tmp_path):
    p = tmp_path / "x.lock"
    with file_lock(p, wait=1):
        with pytest.raises(LockTimeout):
            with file_lock(p, wait=0.2, poll=0.05):
                pass
        assert p.exists()  # khóa của người giữ đầu không bị xóa
    assert not p.exists()


def test_stale_lock_is_taken_over(tmp_path):
    p = tmp_path / "x.lock"
    p.write_text("123")
    old = time.time() - 3600
    os.utime(p, (old, old))
    with file_lock(p, wait=0.5, stale=60):
        assert p.read_text() == str(os.getpid())


def test_released_on_exception(tmp_path):
    p = tmp_path / "x.lock"
    with pytest.raises(ValueError):
        with file_lock(p, wait=1):
            raise ValueError
    assert not p.exists()
```

- [ ] **Step 2: Chạy để thấy hỏng**

Run: `.venv/Scripts/python -m pytest tests/test_filelock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.filelock'`

- [ ] **Step 3: Viết `bot/filelock.py`**

```python
"""Khóa giữa các tiến trình (bot hằng ngày, watch.py) bằng file tạo độc quyền — chạy được trên Windows."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


class LockTimeout(RuntimeError):
    pass


@contextmanager
def file_lock(path: str | Path = "live/git.lock", wait: float = 300.0, stale: float = 1800.0,
              poll: float = 0.5):
    """Giữ khóa trong khối with. Chờ tối đa `wait` giây; khóa cũ hơn `stale` giây coi là treo và bị xóa."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait
    while True:
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - p.stat().st_mtime > stale:
                    p.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() >= deadline:
                raise LockTimeout(f"Chờ khóa {p} quá {wait:.0f} giây")
            time.sleep(poll)
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        break
    try:
        yield
    finally:
        p.unlink(missing_ok=True)
```

- [ ] **Step 4: Chạy test**

Run: `.venv/Scripts/python -m pytest tests/test_filelock.py -v`
Expected: `4 passed`

- [ ] **Step 5: `live_trade.py` giữ khóa suốt lần chạy**

Thêm import (sau `from bot.exchange import BinanceSpot`):
```python
from bot.filelock import file_lock
```
Thay khối cuối file:
```python
if __name__ == "__main__":
    main()
```
bằng:
```python
if __name__ == "__main__":
    with file_lock(wait=600):  # không chạy chồng với lần chạy khác / watch.py đang đẩy GitHub
        main()
```

Run: `.venv/Scripts/python -c "import ast; ast.parse(open('live_trade.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok` (không chạy thật `live_trade.py` — nó sẽ chạy bot và đẩy GitHub)

- [ ] **Step 6: Chạy toàn bộ test và commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `44 passed`

```bash
git add bot/filelock.py tests/test_filelock.py live_trade.py
git commit -m "Khóa live/git.lock: bot và watcher không chạy/đẩy GitHub chồng nhau"
```

---

### Task 6: `bot/watcher.py` — `FillWatcher`

**Files:**
- Create: `bot/watcher.py`
- Test: `tests/test_watcher.py`

**Interfaces:**
- Consumes: `fill_from_event`, `fill_from_rest`, `merge`, `key`, `round_trips` (`bot/fills.py`); exchange có `my_trades(symbol, from_id=None)`, `get_order(symbol, order_id) -> {"clientOrderId", "type", …}`, `free("USDT") -> float`.
- Produces:
  ```
  FillWatcher(ex, publish: Callable[[dict], None], symbols: list[str], topic: str = "",
              fills_path=Path("live/fills.json"), docs_path=Path("docs/fills.json"),
              state_path=Path("live/state.json"), clock=time.time)
    .fills: list[dict]  .usdt: float | None  .dirty: bool  .bot_stop_filled: bool
    .load() -> None
    .backfill() -> int                      # số lệnh mới lấy bù; cập nhật usdt
    .handle(frame: dict) -> list[dict]      # khung WS; trả lệnh vừa phát; eventStreamTerminated → ConnectionError
    .tick() -> list[dict]                   # phát lệnh đã chờ quá 0,5 giây
    .export() -> dict                       # ghi docs/fills.json, dirty=False
  ```
  Tin ntfy: `{"v": 1, "kind": "fill", "fill": <bản ghi>, "usdt": float | None}`.
  `docs/fills.json`: `{"updated": ISO ms "…Z", "topic": str, "usdt": float|None, "fills": [200 lệnh mới nhất trước], "round_trips": <round_trips(toàn bộ)>}`.

- [ ] **Step 1: Viết test hỏng**

`tests/test_watcher.py`:
```python
import json
from datetime import datetime, timezone

import pytest

from bot.watcher import FillWatcher


def report(**kw):
    ev = {"e": "executionReport", "E": 1794669000000, "s": "BTCUSDT", "c": "scalp-1", "S": "BUY", "o": "MARKET",
          "q": "0.1", "p": "0", "x": "TRADE", "X": "FILLED", "i": 11, "l": "0.1", "L": "65000", "Y": "6500",
          "n": "0", "N": "BTC", "T": 1794669000000, "t": 501, "z": "0.1", "Z": "6500"}
    ev.update(kw)
    return {"subscriptionId": 0, "event": ev}


def balance(usdt):
    return {"subscriptionId": 0, "event": {"e": "outboundAccountPosition", "E": 1, "u": 1,
                                           "B": [{"a": "USDT", "f": str(usdt), "l": "0"}]}}


def rest(tid, ms, order):
    return {"symbol": "BTCUSDT", "id": tid, "orderId": order, "price": "65000", "qty": "0.1", "quoteQty": "6500",
            "commission": "0", "commissionAsset": "BTC", "time": ms, "isBuyer": True, "isMaker": False}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeEx:
    def __init__(self, trades=None, orders=None):
        self.trades, self.orders, self.calls = trades or {}, orders or {}, []

    def my_trades(self, symbol, from_id=None, limit=1000):
        self.calls.append((symbol, from_id))
        return [t for t in self.trades.get(symbol, []) if from_id is None or t["id"] >= from_id]

    def get_order(self, symbol, order_id):
        return self.orders[order_id]

    def free(self, asset):
        return 9996.82


def make(tmp_path, ex=None, state=None, clock=None):
    sent = []
    sp = tmp_path / "state.json"
    if state is not None:
        sp.write_text(json.dumps(state), encoding="utf-8")
    w = FillWatcher(ex or FakeEx(), sent.append, ["BTCUSDT"], topic="t", fills_path=tmp_path / "fills.json",
                    docs_path=tmp_path / "docs" / "fills.json", state_path=sp, clock=clock or Clock())
    return w, sent


def test_fill_published_together_with_balance(tmp_path):
    w, sent = make(tmp_path)
    assert w.handle(report()) == [] and sent == []
    out = w.handle(balance(9990))
    assert len(out) == 1 and sent == [{"v": 1, "kind": "fill", "fill": out[0], "usdt": 9990.0}]
    assert out[0]["source"] == "scalp"
    assert json.loads((tmp_path / "fills.json").read_text(encoding="utf-8"))["fills"] == [out[0]]
    assert w.dirty


def test_fill_published_after_wait_without_balance(tmp_path):
    clock = Clock()
    w, sent = make(tmp_path, clock=clock)
    w.handle(report())
    assert w.tick() == []
    clock.t += 0.6
    assert len(w.tick()) == 1 and len(sent) == 1


def test_duplicate_event_not_republished(tmp_path):
    w, sent = make(tmp_path)
    for _ in range(2):
        w.handle(report())
        w.handle(balance(1))
    assert len(sent) == 1 and len(w.fills) == 1


def test_bot_stop_fill_sets_flag(tmp_path):
    w, _ = make(tmp_path, state={"positions": {"BTCUSDT": {"stop_order_id": 11}}})
    w.handle(report(c="web_x", o="STOP_LOSS", S="SELL"))
    assert w.bot_stop_filled
    assert w.handle(balance(1))[0]["source"] == "d1"


def test_stream_terminated_raises(tmp_path):
    w, _ = make(tmp_path)
    with pytest.raises(ConnectionError):
        w.handle({"subscriptionId": 0, "event": {"e": "eventStreamTerminated", "E": 1}})


def test_backfill_respects_start_then_continues_from_last_id(tmp_path):
    start_ms = int(datetime(2026, 11, 14, 13, 50, 31, tzinfo=timezone.utc).timestamp() * 1000)
    ex = FakeEx({"BTCUSDT": [rest(1, start_ms - 1000, 6), rest(2, start_ms + 1000, 7)]},
                {7: {"clientOrderId": "scalp-1-0", "type": "MARKET"}})
    w, sent = make(tmp_path, ex=ex, state={"start": "2026-11-14T13:50:31Z", "positions": {}})
    assert w.backfill() == 1
    assert w.fills[0]["trade_id"] == 2 and w.fills[0]["source"] == "scalp"
    assert w.usdt == 9996.82 and w.dirty and sent == []  # lấy bù không phát ntfy
    assert w.backfill() == 0
    assert ex.calls[-1] == ("BTCUSDT", 3)


def test_load_restores_saved_fills(tmp_path):
    w, _ = make(tmp_path)
    w.handle(report())
    w.handle(balance(5))
    w2, _ = make(tmp_path)
    w2.load()
    assert w2.fills == w.fills and w2.usdt == 5.0


def test_export_writes_public_file(tmp_path):
    w, _ = make(tmp_path)
    w.handle(report(t=1, i=1))
    w.handle(report(t=2, i=2, S="SELL", L="65100", Y="6510", N="USDT", T=1794669001000))
    w.handle(balance(10010))
    data = w.export()
    assert json.loads((tmp_path / "docs" / "fills.json").read_text(encoding="utf-8")) == data
    assert data["topic"] == "t" and data["usdt"] == 10010.0
    assert [f["trade_id"] for f in data["fills"]] == [2, 1]
    assert data["round_trips"]["count"] == 1 and data["round_trips"]["pnl_usdt"] == pytest.approx(10.0)
    assert data["updated"].endswith("Z") and w.dirty is False
```

- [ ] **Step 2: Chạy để thấy hỏng**

Run: `.venv/Scripts/python -m pytest tests/test_watcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.watcher'`

- [ ] **Step 3: Viết `bot/watcher.py`**

```python
"""Theo dõi lệnh khớp: lấy bù qua REST, xử lý khung WebSocket, phát tin, ghi file.

Phần mạng (exchange, hàm publish) được truyền vào để test không cần sàn. watch.py lo vòng lặp WebSocket.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .fills import fill_from_event, fill_from_rest, iso_ms, key, merge, round_trips

BALANCE_WAIT = 0.5  # giây chờ outboundAccountPosition để gửi kèm số dư
KEEP = 200          # số lệnh khớp ghi vào docs/fills.json


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

    # ---------- tệp ----------
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

    # ---------- trạng thái bot ----------
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

    # ---------- lấy bù ----------
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

    # ---------- sự kiện WebSocket ----------
    def handle(self, frame: dict) -> list[dict]:
        ev = frame.get("event")
        if not isinstance(ev, dict):
            return []  # phản hồi request, không phải sự kiện
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
```

- [ ] **Step 4: Chạy test**

Run: `.venv/Scripts/python -m pytest tests/test_watcher.py -v`
Expected: `8 passed`

- [ ] **Step 5: Chạy toàn bộ test và commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `52 passed`

```bash
git add bot/watcher.py tests/test_watcher.py
git commit -m "bot/watcher.py: FillWatcher lấy bù REST, xử lý sự kiện, phát tin, xuất fills.json"
```

---

### Task 7: `watch.py`, `theo_doi.cmd`, cấu hình và README

**Files:**
- Create: `watch.py`, `theo_doi.cmd`
- Modify: `requirements.txt`, `README.md`, `.env` (thêm `NTFY_TOPIC`, không commit — đã có trong `.gitignore`)

**Interfaces:**
- Consumes: `FillWatcher` (Task 6), `file_lock` (Task 5), `BinanceSpot`, `sign` (`bot/exchange.py`), `Config`, `UNSUPPORTED`, `now_iso` (`bot/live.py`).
- Produces: lệnh `.venv/Scripts/python watch.py [--no-push]`; log `live/watch.log`.

- [ ] **Step 1: Thêm phụ thuộc**

`requirements.txt` thêm dòng cuối:
```
websocket-client>=1.8
```
Run: `.venv/Scripts/python -m pip install -q -r requirements.txt && .venv/Scripts/python -c "import websocket; print(websocket.__version__)"`
Expected: `1.9.2` (hoặc mới hơn)

- [ ] **Step 2: Tạo topic ntfy trong `.env`**

```bash
grep -q '^NTFY_TOPIC=' .env || echo "NTFY_TOPIC=cbb-$(.venv/Scripts/python -c 'import secrets; print(secrets.token_hex(10))')" >> .env
grep -c '^NTFY_TOPIC=cbb-' .env
```
Expected: `1`

- [ ] **Step 3: Viết `watch.py`**

```python
"""Theo dõi lệnh khớp real time trên Binance Spot (mặc định testnet) → ntfy.sh + docs/fills.json.

    .venv\\Scripts\\python watch.py              # chạy liên tục (theo_doi.cmd tự chạy lại nếu thoát)
    .venv\\Scripts\\python watch.py --no-push    # không đẩy GitHub (thử nghiệm)

Cần trong .env: BINANCE_API_KEY, BINANCE_API_SECRET, NTFY_TOPIC.
- Mỗi lệnh khớp: phát ntfy ngay (dashboard nhận sau 1–3 giây), ghi live/fills.json.
- Gom tối đa 60 giây/lần: ghi docs/fills.json, commit + push (trong khóa live/git.lock).
- Lệnh STOP_LOSS của bot D1 khớp: chạy live_trade.py --push để bot chốt sổ ngay.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests
from websocket import WebSocketTimeoutException, create_connection

from bot.config import Config
from bot.exchange import BinanceSpot, sign
from bot.filelock import file_lock
from bot.live import UNSUPPORTED, now_iso
from bot.watcher import FillWatcher

sys.stdout.reconfigure(encoding="utf-8")

PUSH_EVERY = 60.0
BOT_RUN_EVERY = 60.0
LOG = Path("live/watch.log")


def log(msg: str) -> None:
    line = f"{now_iso()} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ws_url(ex: BinanceSpot) -> str:
    return ("wss://ws-api.testnet.binance.vision/ws-api/v3" if ex.is_testnet
            else "wss://ws-api.binance.com:443/ws-api/v3")


def publisher(topic: str):
    def publish(payload: dict) -> None:
        try:
            requests.post(f"https://ntfy.sh/{topic}", timeout=5,
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8")).raise_for_status()
        except requests.RequestException as e:
            log(f"Gửi ntfy lỗi: {e}")
    return publish


def subscribe(ws, ex: BinanceSpot) -> None:
    """userDataStream.subscribe.signature: ký HMAC trên các tham số đã sắp xếp (gồm apiKey)."""
    p = {"apiKey": ex.key, "recvWindow": 10000, "timestamp": int(time.time() * 1000) + ex._offset}
    p["signature"] = sign(ex.secret, "&".join(f"{k}={p[k]}" for k in sorted(p)))
    ws.send(json.dumps({"id": "sub", "method": "userDataStream.subscribe.signature", "params": p}))
    r = json.loads(ws.recv())
    if r.get("status") != 200:
        raise RuntimeError(f"Đăng ký nhận lệnh khớp bị từ chối: {r.get('error', r)}")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")


def push_fills() -> bool:
    """Commit + push riêng docs/fills.json. True nếu đã đẩy hoặc không có gì mới."""
    try:
        with file_lock(wait=300):
            git("add", "docs/fills.json")
            if git("diff", "--cached", "--quiet", "--", "docs/fills.json").returncode == 0:
                return True
            c = git("commit", "-m", f"Lệnh khớp {now_iso()}", "--", "docs/fills.json")
            if c.returncode != 0:
                log(f"Commit lỗi: {(c.stderr or c.stdout).strip()}")
                return False
            r = git("push")
            log("Đã đẩy docs/fills.json lên GitHub." if r.returncode == 0 else f"Đẩy GitHub lỗi: {r.stderr.strip()}")
            return r.returncode == 0
    except Exception as e:
        log(f"Đẩy GitHub lỗi: {type(e).__name__}: {e}")
        return False


def run_bot() -> None:
    log("Stop của bot D1 vừa khớp → chạy live_trade.py --push để chốt sổ")
    r = subprocess.run([sys.executable, "live_trade.py", "--push"], capture_output=True, text=True,
                       encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    log(f"live_trade.py kết thúc (mã {r.returncode})")


class Background:
    """Một việc chạy nền tại một thời điểm."""

    def __init__(self):
        self.thread: threading.Thread | None = None

    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, fn) -> None:
        self.thread = threading.Thread(target=fn, daemon=True)
        self.thread.start()


def main() -> None:
    no_push = "--no-push" in sys.argv
    ex = BinanceSpot()  # đọc .env
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not ex.has_keys or not topic:
        sys.exit("Cần BINANCE_API_KEY, BINANCE_API_SECRET và NTFY_TOPIC trong .env")
    symbols = [s for s in Config().symbols if s not in UNSUPPORTED]
    w = FillWatcher(ex, publisher(topic), symbols, topic=topic)
    w.load()
    w.dirty = True  # luôn xuất docs/fills.json lần đầu để trang biết topic
    pusher, bot = Background(), Background()
    last_push = last_bot = 0.0
    delay = 5
    log(f"Bắt đầu theo dõi ({'testnet' if ex.is_testnet else 'LIVE'}), {len(symbols)} coin"
        + (", KHÔNG đẩy GitHub" if no_push else ""))

    def push_job() -> None:
        if not push_fills():
            w.dirty = True  # thử lại ở lượt gom sau

    while True:
        ws = None
        try:
            ex.sync_time()
            n = w.backfill()
            log(f"Lấy bù {n} lệnh khớp; số dư USDT {w.usdt:,.2f}")
            ws = create_connection(ws_url(ex), timeout=10)
            subscribe(ws, ex)
            ws.settimeout(0.5)
            log("Đang nghe lệnh khớp qua WebSocket")
            delay = 5
            while True:
                try:
                    out = w.handle(json.loads(ws.recv()))
                except WebSocketTimeoutException:
                    out = []
                for f in out + w.tick():
                    log(f"KHỚP {f['side']} {f['qty']:g} {f['symbol']} @ {f['price']:g} ({f['source']}) → đã phát ntfy")
                now = time.time()
                if w.dirty and not pusher.busy() and now - last_push >= PUSH_EVERY:
                    w.export()
                    last_push = now
                    if not no_push:
                        pusher.start(push_job)
                if w.bot_stop_filled and not bot.busy() and now - last_bot >= BOT_RUN_EVERY:
                    w.bot_stop_filled = False
                    last_bot = now
                    bot.start(run_bot)
        except KeyboardInterrupt:
            log("Dừng theo dõi")
            break
        except Exception as e:
            log(f"Mất kết nối ({type(e).__name__}: {e}); nối lại sau {delay} giây")
            time.sleep(delay)
            delay = min(delay * 2, 60)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Viết `theo_doi.cmd` (CRLF)**

```bash
printf '@echo off\r\nrem Theo doi lenh khop real time (WebSocket testnet -> ntfy.sh + docs/fills.json). Tu chay lai neu thoat.\r\ncd /d "%%~dp0"\r\nset PYTHONIOENCODING=utf-8\r\n:loop\r\n.venv\\Scripts\\python.exe watch.py\r\ntimeout /t 10 /nobreak >nul\r\ngoto loop\r\n' > theo_doi.cmd
cat -A theo_doi.cmd
```
Expected: 8 dòng kết thúc `^M$`, dòng 3 là `cd /d "%~dp0"^M$`, dòng 6 là `.venv\Scripts\python.exe watch.py^M$`.

- [ ] **Step 5: Chạy thử 25 giây, không đẩy GitHub**

Chạy nền: `.venv/Scripts/python watch.py --no-push` (Bash `run_in_background: true`), đợi tới khi `live/watch.log` có dòng `Đang nghe lệnh khớp qua WebSocket` (lấy bù 29 coin mất khoảng 10–60 giây; dùng Monitor, không `sleep`), rồi:
Run: `tail -5 live/watch.log; .venv/Scripts/python -c "import json; d=json.load(open('docs/fills.json', encoding='utf-8')); print(len(d['fills']), d['round_trips']['count'], round(d['round_trips']['pnl_usdt'], 2), bool(d['topic']))"`
Expected: log có `Lấy bù 2 lệnh khớp; số dư USDT 9,996.82` và `Đang nghe lệnh khớp qua WebSocket`, không có `Mất kết nối`; dòng in `2 1 -3.18 True` (lệnh lướt sóng BTC ngày 14/11, không có nhãn nên nguồn `tay`).
Dừng tiến trình nền (TaskStop). Xóa file tạm: `rm docs/fills.json live/fills.json` (để Task 10 thấy lại bước lấy bù; bản thật do Task 10 tạo).

- [ ] **Step 6: README**

Thêm vào cuối `README.md`:
````markdown
## Lệnh khớp real time

`watch.py` nghe lệnh khớp trên tài khoản testnet qua WebSocket, phát ngay lên ntfy.sh (dashboard nhận sau 1–3 giây, cả điện thoại) và đẩy `docs/fills.json` lên GitHub (gom tối đa 60 giây/lần). Lệnh cắt lỗ của bot D1 khớp giữa ngày → tự chạy `live_trade.py --push` để chốt sổ ngay.

1. `.env` cần `NTFY_TOPIC=<tên ngẫu nhiên>`; tạo tên: `.venv\Scripts\python -c "import secrets; print('cbb-' + secrets.token_hex(10))"`.
2. Chạy `theo_doi.cmd` (tự chạy lại nếu thoát). Tự bật khi đăng nhập Windows:
   `schtasks /Create /TN "CryptoBot TheoDoi" /TR "\"D:\LearnCode\bot\theo_doi.cmd\"" /SC ONLOGON /F`
3. Nguồn lệnh theo `clientOrderId`: `d1-…` bot D1, `scalp-…` lướt sóng (`scalp60.py`), còn lại là lệnh tay. Lệnh tay/lướt sóng có lãi/lỗ riêng (ghép mua–bán FIFO), không tính vào vốn bot D1.

| File | Vai trò |
|---|---|
| `bot/fills.py` | Chuẩn hóa lệnh khớp, phân loại nguồn, ghép cặp FIFO |
| `bot/watcher.py` | Lấy bù qua REST, xử lý sự kiện WebSocket, phát ntfy, ghi `live/fills.json` và `docs/fills.json` |
| `bot/filelock.py` | Khóa `live/git.lock` để bot và watcher không đẩy GitHub chồng nhau |
| `watch.py` | Vòng lặp WebSocket, nối lại khi rớt, đẩy GitHub, chạy bot khi stop khớp |

Tên topic ntfy là công khai (nằm trong `docs/fills.json`): trang chỉ tin tin ntfy mới hơn `fills.json`, tin giả bị thay khi `fills.json` cập nhật.
````

- [ ] **Step 7: Commit**

```bash
git add watch.py theo_doi.cmd requirements.txt README.md
git commit -m "watch.py: nghe lệnh khớp qua WebSocket, phát ntfy, đẩy docs/fills.json"
```

---

### Task 8: Dashboard — thẻ lệnh khớp trực tiếp, lệnh khác, số dư testnet

**Files:**
- Modify: `docs/index.html`

**Interfaces:**
- Consumes: `docs/fills.json` và tin ntfy đúng định dạng Task 6; `LIVE`, `DIRTY`, `table`, `kpi`, `fmt`, `px`, `pct`, `sgn`, `cls`, `esc`, `coin`, `vnDate`, `startFeed`, `render`, `renderLive` sẵn có trong trang.

- [ ] **Step 1: CSS** — sau dòng `.empty { color: var(--t3); font-size: 13px; margin: 2px 0; }` thêm:

```css
td { transition: background 1.5s; }
tr.new td { background: color-mix(in srgb, var(--accent) 16%, transparent); }
.tag { display: inline-block; font-size: 10.5px; line-height: 1; padding: 2px 5px; border-radius: 4px; background: var(--line); color: var(--t2); }
.tag.n { background: var(--accent); color: #fff; }
```

- [ ] **Step 2: HTML** — sau dòng `<section class="card" id="pos-card" hidden>…</section>` thêm:

```html
  <section class="card" id="fl-card" hidden>
    <h2>Khớp lệnh trực tiếp <span class="meta" id="fl-meta"></span></h2>
    <div class="wrap" id="fills"></div>
  </section>
  <section class="card" id="mt-card" hidden>
    <h2>Lệnh khác (tay/lướt sóng) <span class="meta" id="mt-meta"></span></h2>
    <div class="wrap" id="manual"></div>
  </section>
```

- [ ] **Step 3: `table()` nhận class cho dòng** — thay:

```js
function table(cols, rows) {
  if (!rows.length) return "";
  return `<table><thead><tr>${cols.map(c => `<th class="${c.r ? "r" : ""}">${c.h}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(r => "<tr>" + cols.map(
```
bằng:
```js
function table(cols, rows, rowCls) {
  if (!rows.length) return "";
  return `<table><thead><tr>${cols.map(c => `<th class="${c.r ? "r" : ""}">${c.h}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(r => `<tr class="${rowCls ? rowCls(r) : ""}">` + cols.map(
```

- [ ] **Step 4: Biến và hàm phụ** — sau dòng `let DATA = null, LIVE = {}, FLASH = {}, …, SHOW_ALL = false;` thêm:

```js
let FILLS = null, RT = [], RT_USDT = null, NEW = {}, NT = null, NT_OK = false, NT_TOPIC = "", REFETCH = null;
const SRC = { d1: "Bot D1", scalp: "Lướt sóng", tay: "Tay" };
const fkey = f => f.symbol + ":" + f.trade_id;
const vnClock = ms => new Date(ms).toLocaleTimeString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour12: false });
const fillsUpdated = () => FILLS ? +new Date(FILLS.updated) : 0;
const srcTag = s => `<span class="tag">${esc(SRC[s] || s)}</span>`;

function allFills() {
  const base = FILLS?.fills || [], seen = new Set(base.map(fkey));
  return [...RT.filter(f => !seen.has(fkey(f))).sort((a, b) => b.ms - a.ms), ...base];
}
function usdtNow(D) {
  if (RT_USDT && RT_USDT.ms > fillsUpdated()) return RT_USDT.v;
  if (FILLS && Number.isFinite(FILLS.usdt)) return FILLS.usdt;
  return Number.isFinite(D.account?.usdt) ? D.account.usdt : null;
}
```

- [ ] **Step 5: KPI vốn có số dư testnet** — trong `renderLive`, thay:

```js
  $("kpis").innerHTML = [
    kpi("Vốn (USDT)", fmt(equity), `ban đầu ${fmt(cap, 0)}`),
```
bằng:
```js
  const usdt = usdtNow(D);
  $("kpis").innerHTML = [
    kpi("Vốn (USDT)", fmt(equity), `ban đầu ${fmt(cap, 0)}` + (usdt != null ? `<br>số dư testnet ${fmt(usdt)}` : "")),
```

- [ ] **Step 6: Gọi hai thẻ mới** — trong `renderLive`, ngay sau dòng bắt đầu bằng `` $("live").innerHTML = `<span class="dot `` thêm:

```js
  renderFills();
  renderManual();
```

- [ ] **Step 7: Hàm hiển thị, ntfy, tải fills.json** — ngay trước dòng `// ---------- giá trực tiếp: WebSocket Binance, dự phòng hỏi REST 10 giây/lần ----------` thêm:

```js
// ---------- lệnh khớp: fills.json (bản gốc) + ntfy (real time) ----------
function renderFills() {
  const rows = allFills().slice(0, 10), inFile = new Set((FILLS?.fills || []).map(fkey));
  $("fl-card").hidden = !rows.length;
  $("fl-meta").innerHTML = `<span class="dot ${NT_OK ? "on" : ""}"></span>${NT_OK ? "lệnh trực tiếp" : "đang kết nối lệnh…"}`;
  $("fills").innerHTML = table([
    { h: "Giờ", f: r => `${vnClock(r.ms)} <span class="mut">${vnDate(r.time)}</span>` },
    { h: "Lệnh", f: r => r.side === "BUY" ? `<b class="pos">Mua</b>` : `<b class="neg">Bán</b>` },
    { h: "Coin", f: r => `<b>${coin(r.symbol)}</b>` },
    { h: "Khối lượng", r: 1, f: r => px(r.qty) },
    { h: "Giá", r: 1, f: r => px(r.price) },
    { h: "Giá trị", r: 1, f: r => fmt(r.quote) },
    { h: "Nguồn", f: r => srcTag(r.source) + (inFile.has(fkey(r)) ? "" : ` <span class="tag n">mới</span>`) },
  ], rows, r => Date.now() - (NEW[fkey(r)] || 0) < 4000 ? "new" : "");
}

function renderManual() {
  const R = FILLS?.round_trips;
  const open = (R?.open || []).map(o => {
    const p = LIVE[o.symbol];
    return { ...o, price: p, pnl: p ? o.qty * p - o.cost : null };
  });
  const trades = (R?.trades || []).slice(0, 10);
  $("mt-card").hidden = !open.length && !trades.length;
  if ($("mt-card").hidden) return;
  const live = open.reduce((s, o) => s + (o.pnl || 0), 0);
  $("mt-meta").textContent = `đã chốt ${sgn(R.pnl_usdt)} USDT · ${R.count} cặp` + (open.length ? ` · đang mở ${sgn(live)}` : "");
  $("manual").innerHTML = (open.length ? table([
    { h: "Đang mở", f: r => `<b>${coin(r.symbol)}</b> ${srcTag(r.source)}` },
    { h: "Khối lượng", r: 1, f: r => px(r.qty) },
    { h: "Giá vào", r: 1, f: r => px(r.entry_price) },
    { h: "Hiện tại", r: 1, f: r => r.price ? `<span class="${FLASH[r.symbol] || ""}">${px(r.price)}</span>` : "—" },
    { h: "Lãi / lỗ", r: 1, f: r => r.pnl == null ? "—" : sgn(r.pnl), c: r => cls(r.pnl || 0) },
  ], open) : "") + table([
    { h: "Coin", f: r => `<b>${coin(r.symbol)}</b> ${srcTag(r.source)}` },
    { h: "Vào → ra", f: r => r.entry_time
        ? `${vnClock(+new Date(r.entry_time))} → ${vnClock(+new Date(r.exit_time))} <span class="mut">${vnDate(r.exit_time)}</span>`
        : `<span class="mut">bán coin có sẵn · ${vnDate(r.exit_time)}</span>` },
    { h: "Giá vào → ra", r: 1, f: r => r.entry_price ? `${px(r.entry_price)} → ${px(r.exit_price)}` : px(r.exit_price) },
    { h: "Lãi / lỗ", r: 1, f: r => r.pnl_usdt == null ? "—" : `${pct(r.return_pct)} <span class="mut">${sgn(r.pnl_usdt)}</span>`,
      c: r => cls(r.pnl_usdt || 0) },
  ], trades);
}

function validFill(f) {
  return !!f && typeof f.symbol === "string" && /^[A-Z0-9]{2,20}$/.test(f.symbol) && Number.isFinite(f.trade_id) &&
    Number.isFinite(f.ms) && f.ms < Date.now() + 60000 && (f.side === "BUY" || f.side === "SELL") &&
    [f.qty, f.price, f.quote].every(Number.isFinite);
}

function startNtfy(topic, sinceIso) {
  if (!topic || topic === NT_TOPIC) return;
  NT_TOPIC = topic;
  if (NT) NT.close();
  const since = Math.floor(new Date(sinceIso) / 1000);
  NT = new EventSource(`https://ntfy.sh/${encodeURIComponent(topic)}/sse?since=${since > 0 ? since : "1h"}`);
  NT.onopen = () => { NT_OK = true; DIRTY = true; };
  NT.onerror = () => { NT_OK = false; DIRTY = true; };  // EventSource tự nối lại
  NT.onmessage = ev => {
    let m;
    try { m = JSON.parse(JSON.parse(ev.data).message); } catch (e) { return; }
    if (!m || m.v !== 1 || m.kind !== "fill" || !validFill(m.fill)) return;
    const f = m.fill, k = fkey(f);
    if (f.ms <= fillsUpdated() - 5000 || RT.some(x => fkey(x) === k)) return;  // chỉ tin tin mới hơn fills.json
    RT.push(f);
    NEW[k] = Date.now();
    setTimeout(() => { DIRTY = true; }, 4100);
    if (Number.isFinite(m.usdt) && (!RT_USDT || f.ms >= RT_USDT.ms)) RT_USDT = { v: m.usdt, ms: f.ms };
    clearTimeout(REFETCH);
    REFETCH = setTimeout(load, 90000);  // lấy bản fills.json đã đăng
    DIRTY = true;
  };
}

async function loadFills() {
  try {
    const r = await fetch("fills.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) return;
    FILLS = await r.json();
    const inFile = new Set(FILLS.fills.map(fkey)), upd = fillsUpdated();
    RT = RT.filter(f => !inFile.has(fkey(f)) && f.ms > upd - 5000);
    startNtfy(FILLS.topic, FILLS.updated);
    if (DATA) startFeed(DATA);
    DIRTY = true;
  } catch (e) { /* chưa có fills.json → bỏ qua */ }
}
```

- [ ] **Step 8: `startFeed` theo dõi giá cả coin lệnh tay đang mở** — thay dòng đầu của `startFeed`:

```js
  const syms = [...new Set([...(D.radar || []).map(r => r.symbol), ...D.positions.map(p => p.symbol)])].sort(), key = syms.join(",");
```
bằng:
```js
  const syms = [...new Set([...(D.radar || []).map(r => r.symbol), ...D.positions.map(p => p.symbol),
                            ...(FILLS?.round_trips?.open || []).map(o => o.symbol)])].sort(), key = syms.join(",");
```

- [ ] **Step 9: `load()` tải thêm fills.json** — thay:

```js
async function load() {
  try { render(await (await fetch("data.json?t=" + Date.now(), { cache: "no-store" })).json()); }
  catch (e) { $("say").textContent = "Không tải được dữ liệu bot: " + e.message; }
}
```
bằng:
```js
async function load() {
  try { render(await (await fetch("data.json?t=" + Date.now(), { cache: "no-store" })).json()); }
  catch (e) { $("say").textContent = "Không tải được dữ liệu bot: " + e.message; }
  await loadFills();
}
```

- [ ] **Step 10: Kiểm tra cú pháp JS**

```bash
.venv/Scripts/python -c "import re; s=open('docs/index.html',encoding='utf-8').read(); open('C:/Users/vandu/AppData/Local/Temp/claude/be8e2e56c22aabbe/730b06f7-0424-459f-8be5-5edf5c77cad0/scratchpad/page.js','w',encoding='utf-8').write(re.search(r'<script>(.*)</script>', s, re.S).group(1))"
node --check "C:/Users/vandu/AppData/Local/Temp/claude/be8e2e56c22aabbe/730b06f7-0424-459f-8be5-5edf5c77cad0/scratchpad/page.js" && echo JS_OK
```
Expected: `JS_OK`

- [ ] **Step 11: Thử trên trình duyệt với topic thử (không đụng topic thật)**

1. Tạo `docs/fills.json` mẫu (topic thử, 1 lệnh cũ, 1 cặp đã chốt, 1 lô đang mở):
```bash
.venv/Scripts/python - <<'EOF'
import json, secrets, time
from bot.fills import iso_ms, round_trips
now = int(time.time() * 1000)
def f(tid, side, qty, price, ms):
    return {"trade_id": tid, "order_id": tid, "client_id": "", "symbol": "BTCUSDT", "side": side, "type": "MARKET",
            "qty": qty, "price": price, "quote": qty * price, "fee": 0.0, "fee_asset": "USDT", "time": iso_ms(ms),
            "ms": ms, "source": "tay"}
fills = [f(1, "BUY", 0.01, 65000.0, now - 600000), f(2, "SELL", 0.01, 65100.0, now - 300000), f(3, "BUY", 0.02, 65200.0, now - 60000)]
topic = "probe-" + secrets.token_hex(6)
json.dump({"updated": iso_ms(now), "topic": topic, "usdt": 9995.0, "fills": fills[::-1], "round_trips": round_trips(fills)},
          open("docs/fills.json", "w", encoding="utf-8"))
print(topic)
EOF
```
2. Chạy nền `.venv/Scripts/python -m http.server 8765 -d docs` (Bash `run_in_background: true`).
3. Claude in Chrome: `tabs_context_mcp` → `tabs_create_mcp` → mở `http://localhost:8765/`. Kỳ vọng: thẻ "Khớp lệnh trực tiếp" có 3 dòng, chấm "lệnh trực tiếp" xanh; thẻ "Lệnh khác" ghi `đã chốt +1,00 USDT · 1 cặp · đang mở …` và có lô BTC 0,02 với giá hiện tại; KPI Vốn có dòng `số dư testnet 9.995,00`.
4. Gửi một tin ntfy giả lập vào topic thử (thay `<topic>` bằng giá trị in ở bước 1):
```bash
.venv/Scripts/python -c "
import json, time, requests, sys
ms = int(time.time()*1000)
fill = {'trade_id': 4, 'order_id': 4, 'client_id': 'scalp-1', 'symbol': 'ETHUSDT', 'side': 'SELL', 'type': 'MARKET', 'qty': 0.5, 'price': 1850.0, 'quote': 925.0, 'fee': 0.0, 'fee_asset': 'USDT', 'time': '', 'ms': ms, 'source': 'scalp'}
requests.post('https://ntfy.sh/' + sys.argv[1], data=json.dumps({'v': 1, 'kind': 'fill', 'fill': fill, 'usdt': 10920.0}), timeout=5).raise_for_status(); print('sent')
" <topic>
```
Kỳ vọng (chụp màn hình trong ≤3 giây): dòng đầu "Bán ETH 0,5 … Lướt sóng [mới]" sáng nền; KPI ghi `số dư testnet 10.920,00`. `read_console_messages` (pattern `Error`) không có lỗi.
5. Dọn: dừng http.server (TaskStop), đóng tab, `rm docs/fills.json`.

- [ ] **Step 12: Commit**

```bash
git add docs/index.html
git commit -m "Dashboard: khớp lệnh trực tiếp qua ntfy, mục lệnh tay/lướt sóng, số dư testnet"
```

---

### Task 9: Đưa `scalp60.py` vào repo, gắn nhãn `scalp`

**Files:**
- Create: `scalp60.py` (chép từ `C:\Users\vandu\AppData\Local\Temp\claude\be8e2e56c22aabbe\730b06f7-0424-459f-8be5-5edf5c77cad0\scratchpad\scalp60.py`)

**Interfaces:**
- Consumes: `BinanceSpot.market_buy_quote(..., tag=)`, `market_sell(..., tag=)` (Task 2).

- [ ] **Step 1: Chép file**

```bash
cp "C:/Users/vandu/AppData/Local/Temp/claude/be8e2e56c22aabbe/730b06f7-0424-459f-8be5-5edf5c77cad0/scratchpad/scalp60.py" scalp60.py
```

- [ ] **Step 2: Sửa**

a) Dòng đầu docstring `"""Phiên scalping 60 giây: lệnh thật trên Binance Spot TESTNET (tiền ảo), vốn 10.000 USDT.` → thêm ngay sau nó:
```
    .venv\\Scripts\\python scalp60.py    (chạy từ thư mục bot; lệnh gắn nhãn scalp- → dashboard xếp vào "Lướt sóng")
```
b) Thay khối:
```python
BOT_DIR = r"D:\LearnCode\bot"
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)  # để load_env đọc .env

import requests  # noqa: E402

from bot.exchange import BinanceSpot, fill_summary, round_step  # noqa: E402
```
bằng:
```python
import requests

from bot.exchange import BinanceSpot, fill_summary
```
c) Sau `FEE_REAL = 0.001` thêm `TAG = "scalp"`.
d) `OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scalp60_result.json")` → `OUT = os.path.join("live", "scalp60_result.json")`
e) `o = ex.market_buy_quote(sym, cand["notional"])` → `o = ex.market_buy_quote(sym, cand["notional"], tag=TAG)`
f) `o2 = ex.market_sell(sym, qty_net)` → `o2 = ex.market_sell(sym, qty_net, tag=TAG)`
g) `ex.market_sell(pos["sym"], pos["qty"])` → `ex.market_sell(pos["sym"], pos["qty"], tag=TAG)`
h) `with open(OUT, "w", encoding="utf-8") as f:` → thêm dòng `os.makedirs("live", exist_ok=True)` ngay trước.

- [ ] **Step 3: Kiểm tra (không đặt lệnh)**

Run: `.venv/Scripts/python -c "import scalp60; print(scalp60.TAG, scalp60.OUT)"; grep -c "tag=TAG" scalp60.py`
Expected: `scalp live\scalp60_result.json` (hoặc `live/scalp60_result.json`) và `3`

- [ ] **Step 4: Commit**

```bash
git add scalp60.py
git commit -m "Thêm scalp60.py (phiên lướt sóng 60 giây, lệnh gắn nhãn scalp)"
```

---

### Task 10: Chạy thật end-to-end và đăng lên GitHub Pages

**Files:** không sửa code (tạo `docs/fills.json` thật qua watcher).

- [ ] **Step 1: Toàn bộ test**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `52 passed`

- [ ] **Step 2: Đẩy code lên GitHub** (trang mới cần `index.html` mới)

Run: `git push && git log --oneline -1 origin/main`
Expected: push thành công, commit mới nhất là của Task 9.

- [ ] **Step 3: Bật watcher thật** — chạy nền `.venv/Scripts/python watch.py` (Bash `run_in_background: true`). Đợi (Monitor) tới khi log có `Đã đẩy docs/fills.json lên GitHub.` (lấy bù 10–60 giây + push), rồi:
Run: `tail -6 live/watch.log; git log --oneline -1`
Expected: `Lấy bù 2 lệnh khớp`, `Đang nghe lệnh khớp qua WebSocket`, `Đã đẩy docs/fills.json lên GitHub.`; commit mới nhất `Lệnh khớp …`.

- [ ] **Step 4: Đợi GitHub Pages đăng**

Run (lặp tối đa ~3 phút): `curl -s "https://huynhvanduc.github.io/crypto-bot-beta/fills.json?t=$(date +%s)" | head -c 120`
Expected: JSON bắt đầu bằng `{"updated": "2026-11-…`, có `"topic": "cbb-`.

- [ ] **Step 5: Lệnh thật nhỏ, xem real time**

1. Claude in Chrome mở `https://huynhvanduc.github.io/crypto-bot-beta/` (tab mới), xác nhận thẻ "Khớp lệnh trực tiếp" (2 lệnh BTC cũ, chấm "lệnh trực tiếp" xanh) và "Lệnh khác" (`đã chốt -3,18 USDT · 1 cặp`).
2. Mua 20 USDT BTC trên testnet, nhãn `tay`:
```bash
.venv/Scripts/python -c "
from bot.exchange import BinanceSpot, fill_summary
ex = BinanceSpot(); assert ex.is_testnet; ex.sync_time()
o = ex.market_buy_quote('BTCUSDT', 20, tag='tay'); q, avg, fee = fill_summary(o, 'BTC'); print('MUA', q, avg)
open('C:/Users/vandu/AppData/Local/Temp/claude/be8e2e56c22aabbe/730b06f7-0424-459f-8be5-5edf5c77cad0/scratchpad/e2e_qty.txt','w').write(repr(q))
"
```
3. Trong ≤3 giây: `tail -2 live/watch.log` có `KHỚP BUY … BTCUSDT … (tay) → đã phát ntfy`; chụp màn hình trang: dòng "Mua BTC … Tay [mới]" sáng nền, số dư testnet giảm ~20.
4. Bán lại đúng số vừa mua:
```bash
.venv/Scripts/python -c "
from bot.exchange import BinanceSpot
ex = BinanceSpot(); assert ex.is_testnet; ex.sync_time()
q = float(open('C:/Users/vandu/AppData/Local/Temp/claude/be8e2e56c22aabbe/730b06f7-0424-459f-8be5-5edf5c77cad0/scratchpad/e2e_qty.txt').read())
print('BÁN', ex.market_sell('BTCUSDT', q, tag='tay')['status'])
"
```
Kỳ vọng: dòng "Bán BTC" xuất hiện trên trang trong ≤3 giây; sau ~2–3 phút (watcher đẩy + Pages đăng + trang tải lại 90 giây) thẻ "Lệnh khác" có 2 cặp.
5. Kiểm tra số dư: `BTC` vẫn `1.0`, không còn lệnh mở (`/api/v3/openOrders` rỗng).

- [ ] **Step 6: Dừng watcher chạy thử** (TaskStop) — từ đây người dùng chạy `theo_doi.cmd` hoặc cài Task Scheduler theo README.
