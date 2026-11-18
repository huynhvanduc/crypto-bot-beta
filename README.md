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

## Claude tự giao dịch (cloud)

Routine Claude Code trên cloud của Anthropic chạy mỗi giờ bằng gói Claude của người dùng, theo prompt `claude_tu_dong.md`, không cần bật máy tính. Mỗi lượt, Claude chạy `claude_trade.py status / journal / scan` và có thể tìm tin tức trên web. Sau đó nó mua, bán sớm hoặc đứng ngoài, và lệnh nào cũng ghi lý do. Lệnh của Claude có mã bắt đầu bằng `ai-` và hiện nhãn "Claude" trên dashboard.

- Mua xong, `claude_trade.py` đặt ngay lệnh OCO (chốt lời + cắt lỗ) trên sàn. Lượt sau, lệnh `status` sẽ ghi nhận lệnh nào đã khớp chốt lời hoặc cắt lỗ.
- Trạng thái lưu ở `ai/claude.json`, nhật ký ở `ai/claude_journal.csv`. Cả hai được commit và đẩy lên GitHub cùng `docs/claude.json`, để lượt chạy sau đọc được.
- Giới hạn cứng nằm trong `bot/ai_limits.py`, khai báo ở `LIMITS` trong `claude_trade.py`: tối đa 200 USDT mỗi lệnh, 5 lệnh mở, và ngừng mua khi lỗ đã chốt trong ngày từ 150 USDT trở lên (tính theo giờ VN, sau phí).
- Môi trường cloud cần biến `BINANCE_API_KEY`, `BINANCE_API_SECRET`, và phải cho phép mạng tới `testnet.binance.vision` và `data-api.binance.vision`.
- Xem, tạm dừng hoặc chạy ngay routine ở https://claude.ai/code/routines, hoặc từ app Claude trên điện thoại.

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
| `claude_trade.py` | Lệnh của Claude: `scan`, `status`, `journal`, `buy` (kèm OCO), `sell` |
| `claude_tu_dong.md` | Prompt cho routine Claude trên cloud |
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
- `app/` là app .NET MAUI viết bằng C# để theo dõi lệnh (của Claude, Telegram và app), lời/lỗ, và đặt lệnh tay: mua theo USDT, kèm lệnh cắt lỗ đặt sẵn trên sàn ở giá vào − 2×ATR khung 1h. Dữ liệu lấy từ dashboard trên GitHub Pages; app không có dịch vụ chạy nền. Muốn nhận thông báo khớp lệnh thì dùng app ntfy, đăng ký topic có trong `docs/fills.json`. Build bằng `dotnet publish app/CryptoBot.App -f net9.0-android -c Release`, test bằng `dotnet test app/CryptoBot.Tests`.
