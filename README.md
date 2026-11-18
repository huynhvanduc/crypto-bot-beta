# Bot trading crypto — Phase 1

Backtest chiến lược gốc (tầng 1) trên BTC/USDT khung 1h, dữ liệu Binance công khai (không cần API key).

## Chạy

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run_backtest.py   # tải/cập nhật dữ liệu + backtest
.venv\Scripts\python -m pytest         # test
```

## Cấu trúc

| File | Vai trò |
|---|---|
| `bot/config.py` | Tham số chiến lược và ngưỡng đạt |
| `bot/data.py` | Data Feed: tải nến Binance, cache `data/BTCUSDT_1h.csv` |
| `bot/indicators.py` | EMA, RSI (Wilder), ATR (Wilder) |
| `bot/strategy.py` | Tầng 1: close > EMA200, EMA20 > EMA50, RSI(14) cắt lên 40 |
| `bot/labeling.py` | Triple-barrier: TP 2×ATR, SL 1×ATR, tối đa 24 nến; chạm cả hai trong 1 nến = thua |
| `bot/backtest.py` | Vào ở giá mở nến kế tiếp, 1 lệnh một lúc, phí 0,1 %/chiều |
| `bot/metrics.py` | Expectancy, profit factor, drawdown, so OOS/IS |
| `run_backtest.py` | Chạy toàn bộ, in báo cáo, ghi nhật ký lệnh `data/trades_phase1.csv` |

Nhật ký lệnh là dữ liệu huấn luyện cho meta-model ở tầng 2.

## Tầng 2 — meta-model

```powershell
.venv\Scripts\python run_meta.py
```

| File | Vai trò |
|---|---|
| `bot/features.py` | 24 feature: bối cảnh 1h, chế độ thị trường, động lượng gần đây, khung 4h/1D (chỉ nến đã đóng), bối cảnh BTC |
| `bot/meta.py` | Logistic Regression và LightGBM, huấn luyện walk-forward theo quý (chỉ học từ lệnh đã đóng trước quý đó) |
| `run_meta.py` | Chọn mô hình + cửa sổ học theo AUC in-sample, dò ngưỡng trên in-sample, áp nguyên cho out-of-sample; lưu `models/meta_config.json` |
| `train_live.py` | Huấn luyện lại trên dữ liệu tới hôm nay theo cấu hình đã chọn, lưu `models/meta_live.joblib`, chấm điểm tín hiệu 30 ngày qua |

## Bot beta: lệnh thật trên Binance Spot Testnet + web theo dõi

1. Tạo key ở https://testnet.binance.vision (đăng nhập GitHub → Generate HMAC_SHA256 Key), chép `.env.example` thành `.env` và điền key.
2. `.venv\Scripts\python live_trade.py --push` mỗi ngày lúc 07:05 giờ VN (Task Scheduler). Không có key thì chạy chế độ mô phỏng.
3. Web theo dõi: `docs/index.html` + `docs/data.json`, đăng qua GitHub Pages (thư mục `/docs`).

| File | Vai trò |
|---|---|
| `bot/exchange.py` | Client Binance Spot (ký HMAC), mặc định testnet |
| `bot/sim_exchange.py` | Sàn mô phỏng cùng interface, giá thật, không cần key |
| `bot/live.py` | Đối chiếu lệnh stop, nâng trailing stop, vào lệnh mới; trạng thái ở `live/state.json` |
| `live_trade.py` | Chạy một lần, xuất `docs/data.json`, `--push` đẩy lên GitHub |

## Paper trading (Donchian 20 ngày, trailing 3×ATR, khung 1D)

```powershell
.venv\Scripts\python paper_trade.py   # chạy mỗi ngày sau 07:00 giờ VN
```

Lần đầu tạo `paper/config.json` (ngày bắt đầu). Mỗi lần chạy tính lại từ dữ liệu, in vốn ảo, lệnh đang mở, tín hiệu mới, và ghi sự kiện mới vào `paper/journal.csv`.

## Đổi giả thuyết tầng 1

`run_explore.py [1h|4h|1d]` chạy 11 biến thể cố định (khung 4h/1d gộp từ nến 1h đã đóng) (`bot/variants.py`: pullback MA+RSI và breakout Donchian × các cách thoát trong `bot/exits.py`), chọn theo in-sample, kiểm tra 1 biến thể trên out-of-sample.

Quy trình: `run_meta.py` (chọn cấu hình) → `train_live.py` (huấn luyện cho tình hình hiện tại).

## Lệnh khớp real time

`watch.py` nghe lệnh khớp trên tài khoản testnet qua WebSocket, phát ngay lên ntfy.sh (dashboard nhận sau 1–3 giây, cả điện thoại) và đẩy `docs/fills.json` lên GitHub (gom tối đa 60 giây/lần). Lệnh cắt lỗ của bot D1 khớp giữa ngày → tự chạy `live_trade.py --push` để chốt sổ ngay.

1. `.env` cần `NTFY_TOPIC=<tên ngẫu nhiên>`; tạo tên: `.venv\Scripts\python -c "import secrets; print('cbb-' + secrets.token_hex(10))"`.
2. Chạy `theo_doi.cmd` (tự chạy lại nếu thoát). Tự bật khi đăng nhập Windows:
   `schtasks /Create /TN "CryptoBot TheoDoi" /TR "\"D:\LearnCode\bot\theo_doi.cmd\"" /SC ONLOGON /F`
3. Nguồn lệnh theo `clientOrderId`: `d1-…` bot D1, `scalp-…` lướt sóng (lịch sử), còn lại là lệnh tay. Lệnh tay/lướt sóng có lãi/lỗ riêng (ghép mua–bán FIFO), không tính vào vốn bot D1.

Lướt sóng ngắn hạn đã bỏ: backtest 2 năm nến 1 phút (`run_intraday_explore.py`, `specs/2026-11-15-intraday-strategy-design.md`)
cho cả 6 biến thể lỗ ≈ −0,3 %/lệnh sau phí và trượt giá.

| File | Vai trò |
|---|---|
| `bot/fills.py` | Chuẩn hóa lệnh khớp, phân loại nguồn, ghép cặp FIFO |
| `bot/watcher.py` | Lấy bù qua REST, xử lý sự kiện WebSocket, phát ntfy, ghi `live/fills.json` và `docs/fills.json` |
| `bot/filelock.py` | Khóa `live/git.lock` để bot và watcher không đẩy GitHub chồng nhau |
| `watch.py` | Vòng lặp WebSocket, nối lại khi rớt, đẩy GitHub, chạy bot khi stop khớp |

Tên topic ntfy là công khai (nằm trong `docs/fills.json`): trang chỉ tin tin ntfy mới hơn `fills.json`, tin giả bị thay khi `fills.json` cập nhật.

## Claude tự giao dịch (testnet)

Task Scheduler `CryptoBotClaude` chạy `claude_tu_dong.cmd` mỗi 30 phút. File này gọi Claude Code (`claude -p`) với prompt trong `claude_tu_dong.md`. Claude tự chạy `claude_trade.py status / journal / scan`, có thể tìm tin tức trên web, rồi quyết định mua, bán sớm hoặc đứng ngoài, kèm lý do. Lệnh của Claude có mã bắt đầu bằng `ai-` và hiện nhãn "Claude" trên dashboard.

- Trong lúc chạy theo lịch, Claude chỉ được dùng `claude_trade.py` và WebSearch (`--permission-mode dontAsk`).
- Giới hạn cứng nằm trong `bot/ai_limits.py`, khai báo ở `LIMITS` trong `claude_trade.py`: tối đa 200 USDT mỗi lệnh, 5 lệnh mở, và ngừng mua khi lỗ đã chốt trong ngày từ 150 USDT trở lên (tính theo giờ VN, sau phí).
- `claude_trade.py watch forever` tự bán khi chạm TP/SL hoặc khi đã giữ 30 phút. Mỗi lần chạy, `claude_tu_dong.cmd` đều bật tiến trình này; nếu đã có một bản đang chạy thì bản mới tự thoát.
- Nhật ký: `live/claude_auto.log` ghi quyết định của Claude, `live/claude_watch.log` ghi các lần bán tự động.
- Tạm dừng: `schtasks /change /tn CryptoBotClaude /disable`. Bật lại: thay `/disable` bằng `/enable`.

## Chạy trên điện thoại Android (Termux)

Không cần bật máy tính: điện thoại cắm sạc + wifi chạy cả bot D1 (07:05 giờ VN, chạy bù nếu lỡ) lẫn watcher.

1. Cài **Termux** và **Termux:Boot** từ F-Droid (bản trên Google Play đã cũ), mở Termux:Boot 1 lần.
2. Tắt tối ưu pin cho Termux (Cài đặt → Ứng dụng → Termux → Pin → Không hạn chế).
3. Trên máy tính: dừng bot ở máy (tắt task `CryptoBotBeta`, đóng `theo_doi.cmd` và `telegram.cmd`), chép `live\state.json`, `live\fills.json`, `live\telegram.json` (và `live\manual.json` nếu có)
   vào thư mục **Download** của điện thoại (có thể chép thêm `.env` thành `Download/bot.env`, nếu không script sẽ hỏi khóa).
4. Trong Termux:
   `curl -fsSLo install.sh https://raw.githubusercontent.com/huynhvanduc/crypto-bot-beta/main/android/install.sh && bash install.sh`
5. Điều khiển: `bash ~/crypto-bot-beta/android/bot.sh {status|stop|start|ban-het|tam-dung|tiep-tuc}`

Chỉ chạy bot ở MỘT nơi (máy tính hoặc điện thoại), không chạy cả hai.

## App Android (.NET MAUI) — chạy bot trên điện thoại

`app/` là bản C# của bot D1 (không cần Termux): `CryptoBot.Core` (chỉ báo, chiến lược D1, client Binance, theo dõi lệnh khớp,
xuất `docs/data.json` / `docs/fills.json` và đẩy lên GitHub qua API) và `CryptoBot.App` (MAUI, chỉ build Android).

- D1 lúc 07:05 giờ VN (chạy bù nếu lỡ) + xét giá mỗi 15 phút: mua ngay khi giá vượt đỉnh 20 ngày và trên EMA200
  (vào lệnh giữa ngày chưa được backtest; luật thoát giữ nguyên).
- Lướt sóng (nghiên cứu, chỉ testnet): tín hiệu C dòng tiền 5 phút + lọc xu hướng 1h, giữ 10–30 phút, 100 USDT/lệnh, tối đa 500.
- Khóa API, NTFY_TOPIC, GitHub token (fine-grained, Contents: Read and write) nhập trong tab Cài đặt, lưu ở Android Keystore.
- Build: VS 2022 + workload ".NET Multi-platform App UI", Android SDK ở `D:\Android\sdk`;
  `dotnet publish app/CryptoBot.App -f net9.0-android -c Release` → `bin/Release/net9.0-android/publish/*-Signed.apk`.
- Tự nhập khi mở app: đặt `bot.env`, `state.json`, `fills.json` vào `Android/data/com.cryptobot.d1/files/import/`.

Nghiên cứu thêm (không đạt, không chạy): `run_meanrev_explore.py` (bắt đáy ≤ 4 giờ, OOS −0,35 %/lệnh),
`run_explore.py 4h` (khung 4 giờ, OOS −1,35 %/lệnh).
