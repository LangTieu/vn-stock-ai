# Đánh giá skill + code bot LightVela 1 (Hermes @br_stock_bot)

Ngày đánh giá: 09/11/2026. Nguồn: `bot-lightvela1/vnstock_system/` (pull từ
LightVela 1) + skill `vn-stock-market-research` (đã sync, 84 file).
Người đánh giá: Muse. Kết luận ngắn: **skill rất tốt, code lõi (signal_engine)
rất tốt, còn lại chỉ tham khảo hoặc hỏng.**

## 1. Skill `vn-stock-market-research` — TỐT, đã dùng

- Nội dung: nguồn dữ liệu (finfo/nmquan/Finhay/World Bank/Treasury/FRED/GSO),
  chart 4-panel, sector-flow, multi-session flow ranking, cycle 4 năm,
  backtest 2014–2026, vĩ mô 3 tầng, output tiếng Việt conclusion-first.
- Điểm mạnh nhất: **trung thực về backtest** — nói rõ bộ 6-signal Bottom Model
  THẤT BẠI (không bao giờ đủ 5/6), bộ K1–K5 cũ VÔ DỤNG (K1&K2 không bao giờ
  cùng thỏa), và chiến lược thắng là bộ đơn giản (RSI<35 hoặc dd≥10% +
  MACD hist đảo dương). Đây là kiến thức đã trả giá bằng dữ liệu thật.
- Vấn đề (không chặn việc dùng):
  - `scratch/flow_500.py` và `scratch/vnindex_full_chart.py` được nhắc trong
    skill nhưng **KHÔNG CÒN trên máy** (scratch đã bị dọn). Tham chiếu cũ.
  - Key Finhay ghi là `~/.finhay_env` nhưng vị trí thật là
    `~/.finhay/credentials/.env`. Ai làm theo skill sẽ lỗi đọc key.
- Quyết định: **GIỮ NGUYÊN skill, dùng làm nguồn prompt P0 + tham chiếu P1.**
  Không sửa skill local (cron 6h sync sẽ ghi đè).

## 2. `signal_engine.py` (113 dòng) — TỐT NHẤT, lấy về dùng cho P1

- Công thức đã backtest 1.995 phiên VN-Index + 29 mã (2018–2026):
  đáy sâu = RSI14<35 HOẶC giảm ≥10% từ đỉnh 150 phiên (trong 20 phiên);
  xác nhận = MACD hist đảo âm→dương; đỉnh = RSI>70 VÀ giá >15% trên MA150.
  Kết quả: 28 tín hiệu, win 86% sau 120 phiên, avg +9,8%.
- Hàm chỉ báo viết tay bằng numpy, ĐÚNG chuẩn P1 cần:
  `rsi()` Wilder smoothing, `ema()`, `macd_hist()` (12/26/9), `sma()`.
  Khớp spec P1 (RSI(14) Wilder-seed; MACD 12/26/9; MA20/50/200).
- Hàm `signals()` + `winrate()` cho ra **regime class** (đáy sâu / chờ xác
  nhận / cảnh báo đỉnh / đợi) — dùng làm feature regime cho P1, và phương
  pháp đo win-rate sau 20/60/120 phiên dùng cho đánh giá P2a.
- **LỖI (khi tích hợp phải sửa):** khối `__main__` tìm data bằng
  `os.path.join(HERE, 'vnindex_vnstock.json')` nhưng data nằm ở `../data/`,
  không phải cùng thư mục `scripts/` — chạy trực tiếp sẽ in ra NOTHING
  (lặng lẽ, không báo lỗi). Khi đưa vào dự án phải truyền đường dẫn data
  tường minh, không dựa vào HERE.
- Quyết định: **LẤY các hàm `rsi/ema/macd_hist/sma/signals/winrate` làm
  module chỉ báo P1** (`scripts/indicators.py`), sửa lỗi đường dẫn.
  Đây là phần giá trị nhất của cả đợt review.

## 3. `finhay_api.py` (71 dòng) — tham khảo, KHÔNG lấy nguyên

- Client gọn: quotes / index_realtime / price_history qua urllib, UA custom
  bắt buộc (đúng như skill mô tả).
- Vấn đề: đọc key từ `~/.finhay_env` (sai vị trí thật
  `~/.finhay/credentials/.env`); `price_history` dùng `resolution=1D` +
  `from/to` kiểu giây — đã có bản `fetch_finhay_train.py` của dự án robust
  hơn (retry 429, rate-limit, resumable). Không cần lấy thêm.
- Quyết định: **không import nguyên file.** Chỉ ghi nhận endpoint
  `/market/quotes/stocks/{code}` và `/market/index-realtime` làm nguồn giá
  realtime khi cần.

## 4. `macro_monthly.py` (45 dòng) — tham khảo, chưa cần

- Tầng 3: parse CPI/IIP/xuất khẩu từ post NSO (nso.gov.vn wp-json) bằng regex.
  Chạy được (CPI 10/2026: +0,20% m/m, +5,09% y/y trong data).
- Vấn đề: regex dựa vào câu chữ bài post NSO — đổi format là vỡ; World Bank
  annual (đã lấy) robust hơn cho lịch sử. Chỉ hữu ích cho số tháng MỚI NHẤT.
- Quyết định: **chưa tích hợp.** Khi cần CPI tháng mới thì dùng lại pattern
  này, không đưa vào pipeline chính.

## 5. `backtest_full.py` (131 dòng) — CHỈ THAM KHẢO, KHÔNG DÙNG

- Đây là backtest bộ K1–K5 + đỉnh D1–D4 — chính bộ mà README/skill kết luận
  **VÔ DỤNG** (K1&K2 không bao giờ cùng thỏa → 0 tín hiệu). Giữ lại để biết
  "đã thử và thất bại", không dùng làm code.
- Thêm nữa: đọc data từ `/home/agentuser/.hermes/cache/scratch` — thư mục này
  **không còn tồn tại** → chạy là lỗi FileNotFound. Code chết.
- Quyết định: **KHÔNG import, KHÔNG chạy.** Chỉ giữ file trong
  `bot-lightvela1/` làm tài liệu "đã thử".

## 6. Data của bot — dùng làm baseline đối chiếu

- `vnindex_vnstock.json` (1.995 phiên) + `stocks_vnstock.json` (29 mã):
  dữ liệu backtest gốc. Dùng để đối chiếu khi P1/P2 chạy lại backtest —
  nếu kết quả khác nhiều thì kiểm tra lại, không tin ngay.
- `stock_rank.json`: xếp hạng WR từng mã (MBB/CTG/VHM/HDB/ACB cao;
  CMG/FPT/VIX thấp) — tham khảo khi chọn mã test P0/P2, không phải chân lý.
- `macro_state.json` / `macro_monthly.json`: lịch sử USD/VND + CPI tháng —
  đã có nguồn riêng (er-api + World Bank), chỉ đối chiếu khi lệch.

## Quyết định tích hợp (Henrry đã Chốt Perch làm chính 23:06 08/11)

1. **P1 indicators:** lấy hàm từ `signal_engine.py` → module chỉ báo của dự
   án (Perch làm). Sửa lỗi đường dẫn data.
2. **Regime feature:** logic `signals()` → feature regime cho P1.
3. **P2a eval:** phương pháp `winrate()` (20/60/120 phiên) → đánh giá
   direction/backtest.
4. **Không lấy:** `backtest_full.py` (chết + sai), `finhay_api.py` nguyên
   (đã có bản tốt hơn), `macro_monthly.py` (chưa cần).
5. Skill giữ nguyên, sync 6h tiếp tục.
