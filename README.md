# Crypto Bot Beta: Claude tự giao dịch trên Binance Spot Testnet

Cứ 30 phút, Claude tự xem thị trường, suy luận rồi quyết định mua, bán hoặc đứng ngoài, kèm lý do cho từng quyết định. Code giới hạn số tiền mỗi lệnh, số lệnh mở và mức lỗ trong ngày. Dashboard trên GitHub Pages hiện lệnh khớp và lời/lỗ gần như tức thì. Repo này cũng giữ phần đặt lệnh tay qua Telegram.

Bot D1, lướt sóng, backtest và các script nghiên cứu đã bị xóa. Nếu cần xem lại, chúng vẫn còn trong lịch sử git.

## Cài đặt

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
```

Tạo key ở https://testnet.binance.vision (đăng nhập GitHub, chọn Generate HMAC_SHA256 Key). Chép `.env.example` thành `.env` rồi điền key, `NTFY_TOPIC` và `TELEGRAM_BOT_TOKEN` (nếu dùng Telegram).

## Claude tự giao dịch

Task Scheduler `CryptoBotClaude` chạy `claude_tu_dong.cmd` mỗi 30 phút. File này gọi Claude Code (`claude -p`) với prompt trong `claude_tu_dong.md`. Mỗi lượt, Claude chạy `claude_trade.py status / journal / scan` và có thể tìm tin tức trên web. Sau đó nó mua, bán sớm hoặc đứng ngoài, và lệnh nào cũng ghi lý do. Lệnh của Claude có mã bắt đầu bằng `ai-` và hiện nhãn "Claude" trên dashboard.

- Trong lúc chạy theo lịch, Claude chỉ được dùng `claude_trade.py` và WebSearch (`--permission-mode dontAsk`).
- Giới hạn cứng nằm trong `bot/ai_limits.py`, khai báo ở `LIMITS` trong `claude_trade.py`: tối đa 200 USDT mỗi lệnh, 5 lệnh mở, và ngừng mua khi lỗ đã chốt trong ngày từ 150 USDT trở lên (tính theo giờ VN, sau phí).
- `claude_trade.py watch forever` tự bán khi chạm TP/SL hoặc khi đã giữ 30 phút. Mỗi lần chạy, `claude_tu_dong.cmd` đều bật tiến trình này; nếu đã có một bản đang chạy thì bản mới tự thoát.
- Nhật ký: `live/claude_auto.log` ghi quyết định của Claude, `live/claude_watch.log` ghi các lần bán tự động, `live/claude_journal.csv` lưu từng lệnh đã đóng.
- Tạm dừng: `schtasks /change /tn CryptoBotClaude /disable`. Bật lại: thay `/disable` bằng `/enable`.
- Lịch chạy không cần người ngồi trước máy, nên đăng nhập của Claude Code phải còn hạn. Hãy chạy `claude setup-token` để tạo token dài hạn.

## Lệnh tay qua Telegram

Chạy `telegram.cmd`; nếu thoát, file này tự chạy lại. `telegram_bot.py` nhận lệnh mua/bán và gửi trạng thái. Mỗi lệnh được ghi vào `live/manual_journal.csv` cùng bối cảnh thị trường lúc vào và lúc ra, rồi xuất ra `docs/manual.json`.

## Lệnh khớp real time và dashboard

`watch.py` nghe lệnh khớp trên tài khoản testnet qua WebSocket và phát ngay lên ntfy.sh. Dashboard nhận được sau 1–3 giây, kể cả trên điện thoại. Watcher cũng đẩy `docs/fills.json` lên GitHub, gom tối đa 60 giây một lần. Dashboard là `docs/index.html`, đăng qua GitHub Pages từ thư mục `/docs`.

1. `.env` cần `NTFY_TOPIC=<tên ngẫu nhiên>`. Tạo tên bằng lệnh `.venv\Scripts\python -c "import secrets; print('cbb-' + secrets.token_hex(10))"`.
2. Chạy `theo_doi.cmd`; nếu thoát, file này tự chạy lại. Để tự bật khi đăng nhập Windows:
   `schtasks /Create /TN "CryptoBot TheoDoi" /TR "\"D:\LearnCode\bot\theo_doi.cmd\"" /SC ONLOGON /F`
3. Nguồn của lệnh được xác định theo `clientOrderId`:
   - `ai-…`: Claude;
   - `tg-…` hoặc không có mã: lệnh tay;
   - `d1-…` và `scalp-…`: lệnh cũ của bot D1 và lướt sóng (chỉ còn trong lịch sử).

   Lời/lỗ được tính bằng cách ghép lệnh mua với lệnh bán theo thứ tự trước-sau (FIFO).

Tên topic ntfy là công khai vì nó nằm trong `docs/fills.json`. Vì vậy trang chỉ tin những tin ntfy mới hơn `fills.json`, và tin giả sẽ bị thay khi `fills.json` cập nhật.

## Cấu trúc

| File | Vai trò |
|---|---|
| `claude_trade.py` | Lệnh của Claude: `scan`, `status`, `journal`, `buy`, `sell`, `watch [forever]` |
| `claude_tu_dong.md` / `.cmd` | Prompt và file chạy theo lịch cho Claude |
| `bot/ai_limits.py` | Giới hạn cứng: USDT mỗi lệnh, số lệnh mở, lỗ trong ngày |
| `bot/manual.py` | Mua/bán, trạng thái lệnh, ghi nhật ký (dùng chung cho Claude và Telegram) |
| `bot/journal.py` | Bối cảnh thị trường (5m/15m/1h, BTC), thống kê, xuất JSON cho dashboard |
| `bot/indicators.py` | EMA, RSI, ATR |
| `bot/exchange.py` | Client Binance Spot (ký HMAC), mặc định testnet, gắn `clientOrderId` |
| `bot/common.py` | Danh sách coin, API công khai, giờ UTC |
| `telegram_bot.py`, `bot/telegram.py` | Lệnh tay qua Telegram |
| `watch.py`, `bot/watcher.py`, `bot/fills.py` | Lệnh khớp real time, phân loại nguồn, ghép cặp FIFO |
| `bot/gitops.py`, `bot/filelock.py` | Đẩy GitHub, khóa `live/git.lock` để các tiến trình không đẩy chồng nhau |

## Android

- `android/` gồm các script Termux để chạy `watch.py` và `telegram_bot.py` trên điện thoại.
  - Cài đặt: `curl -fsSLo install.sh https://raw.githubusercontent.com/huynhvanduc/crypto-bot-beta/main/android/install.sh && bash install.sh`
  - Điều khiển: `bash ~/crypto-bot-beta/android/bot.sh {status|stop|start}`
  - Chỉ chạy watcher ở MỘT nơi, máy tính hoặc điện thoại.
- `app/` là app .NET MAUI viết bằng C#, chạy độc lập, có bản C# riêng của bot D1 và theo dõi lệnh khớp. Build bằng lệnh `dotnet publish app/CryptoBot.App -f net9.0-android -c Release`.
