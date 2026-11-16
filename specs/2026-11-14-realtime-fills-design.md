# Cập nhật lệnh mua bán real time lên dashboard

Ngày: 2026-11-14 · Trạng thái: đã duyệt

## Mục tiêu

Mọi lệnh khớp trên tài khoản Binance Spot Testnet (bot D1, lướt sóng, lệnh tay) hiện trên dashboard
GitHub Pages trong **1–3 giây**, xem được cả trên điện thoại. Lệnh không phải của bot D1 nằm ở **mục riêng**,
không làm lẫn vốn và thống kê của chiến lược D1 (vẫn dùng để so với backtest).

Hiện nay dashboard chỉ biết lệnh khi `live_trade.py` chạy lúc 07:05 và đẩy `docs/data.json`; lệnh stop
khớp giữa ngày phải chờ tới sáng hôm sau mới được chốt sổ.

## Kiến trúc

```
Binance testnet ──WebSocket (executionReport, outboundAccountPosition)──► watch.py (máy người dùng)
                                                                          │
                     ┌────────────────────────────────────────────────────┼──────────────────────────────┐
                     ▼                                                    ▼                              ▼
          POST https://ntfy.sh/<topic>                       live/fills.json → docs/fills.json   stop D1 khớp → chạy
          (1–3 giây tới trình duyệt)                         → git push (gom 60 giây)            live_trade.py --push
                     │                                                    │
                     ▼                                                    ▼
          docs/index.html: EventSource ntfy  ◄────── tải fills.json + data.json ──────  GitHub Pages
```

## Thành phần

### `bot/exchange.py` — gắn nhãn lệnh
- `market_buy_quote`, `market_sell`, `stop_loss_sell` nhận thêm `tag: str | None = None`; có tag thì gửi
  `newClientOrderId = f"{tag}-{ms}"` (ms = thời gian hiện tại tính bằng mili giây; tối đa 36 ký tự, chỉ `[.A-Za-z0-9:/_-]`).
- `SimExchange` nhận cùng tham số (bỏ qua) để giữ chung interface.
- `bot/live.py` gắn `tag="d1"` cho mọi lệnh của bot.

### `bot/fills.py` — xử lý lệnh khớp (thuần, không mạng, có test)
- `fill_from_event(ev) -> dict | None`: từ `executionReport` có `x == "TRADE"` tạo bản ghi
  `{trade_id, order_id, client_id, symbol, side, type, qty, price, quote, fee, fee_asset, time, source}`;
  sự kiện khác trả `None`.
- `fill_from_rest(trade, client_id, order_type) -> dict`: cùng định dạng từ `GET /api/v3/myTrades` (dùng khi lấy bù).
- `classify(client_id, order_id, bot_order_ids) -> "d1" | "scalp" | "tay"`: theo tiền tố `d1-` / `scalp-`; `order_id` nằm
  trong lệnh stop đang theo dõi ở `live/state.json` cũng là `d1`; còn lại là `tay`.
- `merge(fills, new) -> list`: gộp, bỏ trùng theo `(symbol, trade_id)`, sắp theo thời gian.
- `round_trips(fills) -> {"trades": [...], "open": [...], "pnl_usdt": float}`: chỉ lệnh nguồn `scalp`/`tay`,
  ghép mua–bán theo FIFO từng coin. Mỗi lệnh bán tạo một cặp `{symbol, source, entry_time, exit_time, qty,
  entry_price (bình quân lô đã dùng), exit_price, pnl_usdt (đã trừ phí quy USDT), return_pct}`. Phần bán vượt quá
  số đã mua (bán coin có sẵn của testnet) ghi `pnl_usdt = null`, không cộng vào tổng. Lô mua còn dư → `open`.

### `bot/filelock.py` — khóa liên tiến trình
- Context manager tạo `live/git.lock` bằng `os.open(O_CREAT | O_EXCL)`, chờ tối đa 5 phút, coi khóa cũ hơn
  10 phút là treo và xóa.
- `live_trade.py` giữ khóa suốt lần chạy (hai lần chạy bot không chồng nhau); `watch.py` chỉ giữ khóa khi
  commit/push `docs/fills.json`.

### `watch.py` — tiến trình chạy nền
1. Khởi động: đọc `live/fills.json`; **lấy bù** bằng `myTrades` cho các coin của bot + coin đã có trong lịch sử,
   từ `trade_id` lớn nhất đã biết (lần đầu: từ `start` trong `live/state.json`); lấy `clientOrderId` bằng
   `GET /api/v3/order` (nhớ đệm theo `order_id`). Lần đầu sẽ lấy được lệnh lướt sóng BTC ngày 2026-11-14.
2. Mở `wss://ws-api.testnet.binance.vision/ws-api/v3`, gửi `userDataStream.subscribe.signature`
   (`apiKey`, `timestamp`, `recvWindow`, `signature` HMAC trên chuỗi tham số đã sắp xếp — kiểm chứng định dạng
   chính xác khi làm). Sự kiện tới dạng `{"subscriptionId": n, "event": {...}}`.
3. Mỗi `executionReport` loại `TRADE`: đợi tối đa 0,5 giây lấy `outboundAccountPosition` kế tiếp để có số dư USDT,
   rồi **phát ntfy** một tin JSON `{"v":1,"kind":"fill","fill":{...},"usdt":...}`; ghi `live/fills.json`;
   đánh dấu cần đẩy.
4. Gom đẩy: tối đa 60 giây/lần, ghi `docs/fills.json` (`updated`, `usdt`, 200 lệnh khớp gần nhất, `round_trips`),
   `git add docs/fills.json && git commit && git push` trong khóa.
5. Lệnh `d1` loại `STOP_LOSS` khớp hết (`X == "FILLED"`) → chạy `live_trade.py --push` (tiến trình con, tối đa
   1 lần/phút) để bot chốt sổ ngay.
6. Mất kết nối / bị sàn ngắt sau 24 giờ → nối lại sau 5, 10, 20… tối đa 60 giây, rồi lấy bù như bước 1.
7. Ghi log `live/watch.log`. Cấu hình `NTFY_TOPIC` trong `.env`.

### `theo_doi.cmd` + Task Scheduler
- `theo_doi.cmd` chạy `watch.py`, tự chạy lại sau 10 giây nếu thoát.
- Hướng dẫn cài `schtasks /Create /SC ONLOGON` trong README.

### `docs/index.html`
- Tên topic ntfy lấy từ trường `topic` của `fills.json` (watcher ghi từ `NTFY_TOPIC` trong `.env` — một nguồn duy nhất).
- Tải `fills.json` cùng `data.json` (mỗi 5 phút, và 90 giây sau khi có tin ntfy để lấy bản đã đăng).
- `EventSource("https://ntfy.sh/<topic>/sse?since=<fills.updated>")`; chỉ nhận tin hợp lệ có `fill.time`
  **mới hơn** `fills.updated`, bỏ trùng theo `(symbol, trade_id)`.
- Thẻ **Khớp lệnh trực tiếp**: 10 lệnh gần nhất — giờ (giây), Mua/Bán, coin, khối lượng, giá, giá trị, nguồn
  (Bot D1 / Lướt sóng / Tay); lệnh mới sáng lên vài giây, lệnh chưa có trong `fills.json` có nhãn "mới".
- Thẻ **Lệnh khác (tay/lướt sóng)**: tổng lãi/lỗ, các cặp lệnh, lô đang mở với lãi/lỗ theo giá trực tiếp (giá
  mainnet sẵn có trên trang). Ẩn khi trống.
- KPI Vốn: thêm "testnet: x USDT" từ `usdt` mới nhất (tin ntfy hoặc `fills.json`).
- Chấm trạng thái "lệnh trực tiếp" (đã nối ntfy hay chưa) bên cạnh chấm "giá trực tiếp".

### Việc kèm theo
- Sửa `ban_het.cmd`, `tam_dung.cmd`, `tiep_tuc.cmd`: dòng `cd` đang chứa ký tự backspace thay cho `\b`
  (`D:\LearnCode<BS>ot`), cả ba lệnh hiện không chạy được.
- Đưa kịch bản lướt sóng 60 giây vào repo `scalp60.py`, gắn `tag="scalp"`.
- `requirements.txt` thêm `websocket-client`. README thêm mục real time.

## Xử lý lỗi
| Tình huống | Cách xử lý |
|---|---|
| ntfy.sh lỗi / hết hạn mức | Bỏ qua, ghi log; web vẫn nhận lệnh qua `fills.json` (trễ 1–2 phút). |
| Tin giả gửi vào topic công khai | Trang chỉ hiện tin mới hơn `fills.json`; lần tải `fills.json` sau sẽ thay thế. |
| WebSocket rớt | Nối lại có backoff, lấy bù qua REST, bỏ trùng theo `trade_id`. |
| `git push` lỗi | Giữ cờ cần đẩy, thử lại ở lượt gom sau, ghi log. |
| Bot và watcher cùng đẩy | Khóa `live/git.lock`. |
| Máy tắt | Không real time (như bot hiện nay); bật lại thì lấy bù. |

## Kiểm thử
- Pytest cho `bot/fills.py` (mẫu `executionReport` thật, phân loại, bỏ trùng, FIFO gồm mua nhiều lần/bán một
  lần, bán vượt số đã mua, phí bằng coin và bằng USDT) và `bot/filelock.py` (khóa, chờ, khóa treo).
- Chạy thật: bật `watch.py`, đặt lệnh nhỏ trên testnet, thấy lệnh trên dashboard (máy tính và điện thoại) trong vài
  giây; tắt mạng rồi bật lại để thử lấy bù.

## Ngoài phạm vi
- Xác thực chữ ký tin ntfy, tài khoản ntfy riêng, server riêng.
- Gộp lệnh tay vào vốn bot D1.
