# Thiết kế: chiến lược lướt sóng trong ngày có kiểm chứng (giai đoạn 1 — nghiên cứu)

Ngày: 15/11/2026

## Bối cảnh

`scalp60.py` (lướt sóng vài phút) chưa từng được backtest. Thực tế 14 lệnh (14–15/11/2026) chỉ 3 lệnh lãi sau phí,
lũy kế −196,51 USDT nếu tính phí thật 0,1 %/chiều. Nguyên nhân chính: mục tiêu mỗi lệnh (20–40 bps) xấp xỉ phí
+ trượt giá (~30 bps), và bot mua các nhịp hồi ngắn khi thị trường đang giảm.

Yêu cầu của người dùng: chỉ giao dịch khi "khởi sắc", không mua mù quáng; muốn bằng chứng có lãi trước khi chạy.

## Mục tiêu

Trả lời bằng dữ liệu: có biến thể lướt sóng trong ngày (giữ tối đa 60 phút) nào **có lãi sau phí và trượt giá trên
dữ liệu chưa dùng để chọn** hay không. Không đặt lệnh nào trong giai đoạn này.

Ngoài phạm vi: chạy thật (giai đoạn 2, spec riêng, chỉ khi có biến thể đạt); sửa `scalp60.py` (một phiên làm việc khác
đang sửa file này).

## Thành phần

| File | Việc |
|---|---|
| `bot/minute_data.py` | Tải và cache nến 1 phút từ `data.binance.vision` |
| `bot/intraday.py` | Bộ lọc thị trường thuận, tín hiệu A/B/C, mô phỏng thoát lệnh, bộ 6 biến thể cố định |
| `run_intraday_explore.py` | Chạy biến thể, chọn trên in-sample, kiểm tra out-of-sample, in kết luận |
| `tests/test_intraday.py` | Test cho các phần trên |

Dùng lại: `bot/metrics.py` (`compute_metrics`, `check_thresholds`, `print_checks`, `tstat`), `bot/indicators.py`
(`ema`, `rsi`, `atr`), `Config.split_time` (`in_sample_frac` = 0,7, với `start` đổi thành 15/11/2024).

## Dữ liệu (`bot/minute_data.py`)

- Coin: ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, BTCUSDT. Giai đoạn: 15/11/2024 00:00 UTC → 14/11/2026 23:59 UTC.
- Nguồn: `https://data.binance.vision/data/spot/monthly/klines/<SYM>/1m/<SYM>-1m-<YYYY-MM>.zip` cho các tháng đã
  qua; tháng hiện tại lấy file theo ngày `.../daily/klines/<SYM>/1m/<SYM>-1m-<YYYY-MM-DD>.zip`.
- Cột trong file: open_time, open, high, low, close, volume, close_time, quote_volume, count,
  taker_buy_base_volume, taker_buy_quote_volume, ignore. Giữ: open_time, open, high, low, close, volume,
  taker_buy_base_volume.
- Mốc thời gian: dữ liệu spot từ 2025 dùng micro giây, trước đó mili giây → nhận biết theo độ lớn và quy về một đơn vị.
- Cache: `data/1m/<SYM>.csv` (thư mục `data/` không đưa lên git); lần sau chỉ tải tháng/ngày còn thiếu.
- Tải lỗi: thử lại 5 lần (chờ tăng dần); vẫn lỗi → dừng, báo tên file thiếu. Không backtest khi dữ liệu thủng.
- Chỗ trống > 5 phút liên tục được liệt kê trong báo cáo.

## Luật giao dịch (`bot/intraday.py`) — chốt trước khi xem kết quả

Dòng tiền của một nến = (2 × taker_buy_base_volume − volume) / volume, trong [−1, +1] (volume = 0 → 0).

Nến 5 phút và 1 giờ gộp từ nến 1 phút (volume và taker_buy_base_volume cộng dồn), chỉ dùng **khi đã đóng đủ số nến
1 phút** (5 và 60). Chỉ báo chưa đủ dữ liệu khởi động (vd. EMA200 1 giờ cần 200 nến) → không có tín hiệu.

**Bộ lọc thị trường thuận** (bắt buộc với mọi tín hiệu), trên nến 1 giờ đã đóng gần nhất:
- coin: close > EMA200 và EMA50 > EMA200;
- BTC: close > EMA200.

**Tín hiệu** — xét tại lúc nến 5 phút đóng; vào lệnh ở giá **mở của phút kế tiếp**:
- A — Phá đỉnh: close 5 phút > max(high) của 12 nến 5 phút trước đó, và dòng tiền nến đó > +0,2.
- B — Nhịp chỉnh: RSI(14) khung 5 phút cắt lên 40 (nến trước < 40, nến này ≥ 40).
- C — Dòng tiền: dòng tiền nến 5 phút > +0,3 và close > open.

**Điều kiện chung khi vào lệnh:**
- ATR(14) khung 5 phút tại nến tín hiệu; bỏ tín hiệu nếu 3 × ATR / giá vào < 60 bps.
- Mỗi coin tối đa 1 lệnh một lúc; tín hiệu trong lúc đang giữ lệnh bị bỏ qua. Không vào lệnh trong 5 phút sau một
  chỗ trống dữ liệu.

**Thoát lệnh** (duyệt từng nến 1 phút từ phút vào lệnh):
- Kiểu 1 — Cố định: stop = giá vào − 1,5 × ATR; chốt lời = giá vào + 3 × ATR.
- Kiểu 2 — Trailing: stop ban đầu như kiểu 1; sau mỗi nến 1 phút đóng, stop = max(stop, đỉnh cao nhất − 1,5 × ATR).
- Cả hai: hết 60 phút → bán ở giá close của phút thứ 60.
- Giá mở của phút ≤ stop → bán ở giá mở. Low ≤ stop → bán ở stop. Cùng nến chạm stop và chốt lời → tính chạm stop.

**Chi phí:** phí 0,1 % mỗi chiều + trượt giá 5 bps mỗi chiều (giá mua cao hơn, giá bán thấp hơn).
Lãi một lệnh = (giá bán × (1 − 0,0005) × (1 − 0,001)) / (giá mua × (1 + 0,0005) × (1 + 0,001)) − 1.

**6 biến thể:** {A, B, C} × {Cố định, Trailing}.

## Đánh giá (`run_intraday_explore.py`)

- Chỉ số tính bằng `compute_metrics` trên lệnh của cả 5 coin (cột `symbol`): sụt vốn/lợi nhuận theo danh mục chia đều
  vốn cho từng coin, giống bot D1.
- Mốc chia: `replace(Config(), start="2024-11-15").split_time(<nến cuối>)` (70 % đầu của khoảng 15/11/2024 →
  14/11/2026 là in-sample, ~7 tháng cuối là out-of-sample; không dùng `Config().start` = 2020);
  lệnh thuộc phần nào theo thời điểm vào lệnh.
- In-sample: in bảng cả 6 biến thể; chọn **một** biến thể có lãi TB/lệnh cao nhất trong các biến thể ≥ 100 lệnh
  in-sample. Không biến thể nào ≥ 100 lệnh → kết luận "không đạt".
- Out-of-sample: chỉ chạy biến thể đã chọn, một lần.
- **Đạt** khi out-of-sample qua tất cả: lãi TB/lệnh > 0; profit factor > 1,3; sụt vốn tối đa < 20 %;
  lãi TB out-of-sample ≥ 70 % lãi TB in-sample; ≥ 100 lệnh; **t-stat ≥ 2**.
- Báo cáo thêm (chỉ để hiểu, không dùng để chọn): kết quả theo tháng, theo coin, và biến thể đã chọn khi **bỏ** bộ lọc
  thị trường thuận; danh sách chỗ trống dữ liệu.
- Ghi nhật ký lệnh: `data/trades_intraday_<biến thể>.csv`.
- Không đạt → kết luận không chạy lướt sóng. Không chỉnh tham số rồi chạy lại trên cùng dữ liệu.

## Kiểm thử (`tests/test_intraday.py`)

- Không nhìn trước: thay đổi dữ liệu sau thời điểm tín hiệu không làm đổi tín hiệu tại thời điểm đó.
- Gộp nến: nến 5 phút/1 giờ thiếu phút bị bỏ; thời điểm dùng được = lúc nến đóng.
- Thoát lệnh: chạm stop; chạm chốt lời; chạm cả hai cùng nến (tính stop); hết 60 phút; giá mở đã dưới stop; trailing
  nâng stop.
- Chi phí: công thức lãi trừ đúng phí và trượt giá hai chiều.
- Bộ lọc: BTC dưới EMA200 → không có tín hiệu.
- Đọc file Binance: đúng cột, mốc thời gian mili giây và micro giây đều quy đúng.
- 54 test hiện có vẫn pass.
