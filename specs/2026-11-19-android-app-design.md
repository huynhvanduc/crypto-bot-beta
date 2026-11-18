# App Android viết lại: theo dõi + lệnh tay

## Mục tiêu

App `app/` (.NET MAUI, chỉ Android) dùng để theo dõi lệnh của Claude, Telegram và chính app, xem lời/lỗ, và đặt lệnh tay trên Binance Spot Testnet. App không còn chạy bot D1, lướt sóng hay watcher lệnh khớp.

## Phạm vi

- Không có dịch vụ chạy nền và không cần GitHub token.
- Thông báo khớp lệnh dùng app ntfy chính chủ, đăng ký topic có trong `fills.json`. App không có code thông báo.
- Code theo kiểu KISS: không comment, ngắn gọn, xóa toàn bộ code cũ không dùng.

## Nguồn dữ liệu

- `<dashboard>/fills.json`: `usdt` (số dư), `fills` (lệnh khớp), `round_trips.open` (lệnh đang mở), `round_trips.trades` (lệnh đã đóng), `round_trips.pnl_usdt`.
- `<dashboard>/claude.json`: `open[]` và `closed[]` có `symbol` và `reason`.
- Giá hiện tại lấy từ `https://data-api.binance.vision/api/v3/ticker/price`.
- `<dashboard>` mặc định là `https://huynhvanduc.github.io/crypto-bot-beta`, sửa được trong Cài đặt.

Dữ liệu làm mới khi mở app, khi kéo xuống, và 15 giây một lần lúc app đang hiển thị.

## Màn hình chính (một trang cuộn)

1. **3 ô tổng:**
   - Số dư USDT (`usdt`).
   - Đã chốt (`round_trips.pnl_usdt`).
   - Đang mở: số lệnh kèm tổng lời/lỗ tạm tính, tính bằng tổng của (khối lượng × giá hiện tại − vốn).
2. **Mua:** chọn coin (29 coin, bỏ EOS), nhập số USDT (mặc định 100), bấm Mua.
3. **Đang mở:** lấy từ `round_trips.open`. Mỗi dòng gồm coin, nhãn nguồn, giá vào, giá hiện tại và lời/lỗ (% và USDT). Dòng nào thuộc lệnh app đang giữ thì có nút **Bán**.
4. **Claude:** lý do của các lệnh Claude đang mở, lấy từ `claude.json`.
5. **Đã đóng:** 20 lệnh gần nhất, gồm coin, nhãn nguồn, giá vào → ra và lời/lỗ.
6. **Mua/bán gần đây:** 20 lệnh khớp gần nhất, gồm giờ, Mua/Bán, coin, giá và số USDT.

Nhãn nguồn: `ai` hiện "Claude", `tay` hiện "Tay", `scalp` hiện "Lướt sóng", `d1` hiện "D1".

## Lệnh tay

- **Mua:**
  1. Đặt lệnh market mua theo số USDT (`quoteOrderQty`), `newClientOrderId` = `app-<ms>`.
  2. Tính ATR(14, Wilder) trên nến 1h đã đóng.
  3. Giá cắt lỗ = giá khớp trung bình − 2×ATR.
  4. Đặt lệnh `STOP_LOSS` bán toàn bộ khối lượng, giống `bot/exchange.py`: chạm giá stop thì bán theo giá thị trường. Giá stop làm tròn theo tick.
  5. Lưu vào Preferences: `{symbol, qty, entry, stopOrderId}`. Nếu đã có lệnh app cho coin đó thì không mua thêm.
- **Bán:** hủy lệnh cắt lỗ (bỏ qua lỗi), đặt lệnh market bán toàn bộ khối lượng, rồi xóa khỏi danh sách lưu.
- **Đối chiếu:** mỗi lần làm mới, kiểm tra từng lệnh app đang lưu. Nếu lệnh cắt lỗ có trạng thái `FILLED`, `CANCELED` hoặc `EXPIRED` thì xóa khỏi danh sách.
- **Khối lượng:** lấy `stepSize`, `tickSize`, `minNotional` từ `exchangeInfo`, lưu đệm theo coin. Lượng coin nhận được sau phí được làm tròn xuống theo step.

## Cài đặt

- API key và secret testnet, lưu trong SecureStorage.
- Địa chỉ dashboard, lưu trong Preferences.
- App chỉ dùng `https://testnet.binance.vision`.

## Lỗi

- Lỗi mạng hoặc lỗi sàn hiện thành một dòng báo đỏ ở đầu trang.
- Nếu mua thành công nhưng đặt cắt lỗ thất bại: app vẫn lưu lệnh với `stopOrderId = 0` và báo "Chưa đặt được cắt lỗ — bán tay khi cần".
- Nếu chưa có key: nút Mua/Bán bị khóa và trang hiện "Nhập key ở Cài đặt".

## Cấu trúc code

- `CryptoBot.Core/Binance.cs`: client ký HMAC; `Price`, `Filters`, `Atr1h`, `BuyQuote`, `StopLoss`, `Cancel`, `GetOrderStatus`, `Sell`.
- `CryptoBot.Core/Feed.cs`: tải và đọc `fills.json` và `claude.json` thành record.
- `CryptoBot.App/App.cs`: Shell gồm 2 tab.
- `CryptoBot.App/MainPage.cs`: màn hình chính.
- `CryptoBot.App/SettingsPage.cs`: trang Cài đặt.
- `CryptoBot.App/Platforms/Android/`: chỉ `MainActivity`, `MainApplication` và manifest có quyền INTERNET. Không có service.
- Xóa: BotEngine, LiveTrader, Strategy, Research, Bars, MarketData, Metrics, State, Dashboard, FillWatcher, Services, Fills, Indicators, Json, Exchange, Pages.

## Kiểm tra

Bản release phải build được bằng `dotnet publish app/CryptoBot.App -f net9.0-android -c Release`. Người dùng cài APK lên điện thoại để chạy thử, vì máy này không có thiết bị hay máy ảo Android.
