# VN Stock AI — Plan v0.4 (Model phân tích chứng khoán Việt Nam)

Ngày: 2026-11-11
Chat: side chat ac20b59f (chat riêng xây model AI)
Trạng thái: **ĐANG BUILD — Henrry ra lệnh 14:39 10/11 "Kêu touke làm đi, lỗi thì tự xử lý, a chỉ muốn kết quả".** P0 XONG 15:21 10/11 + eval 14B XONG 23:11 10/11 (60/60 run, rubric 9,13/10, ABSTAIN 60/60). P1 dataset XONG + vòng sửa nội dung ĐÓNG 20:30 10/11 (verified 20:41; nợ: BCTC fundamentals cho 200 mẫu + xác nhận holdout-range — giao Tuoke 20:43 10/11). P2 train LoRA BẮT ĐẦU sau khi P1 xong nợ. P3 gateway LIVE, fallback FOSTA 1-1 ra 6/6 router xong 20:27 10/11. Dữ liệu train thô ĐÃ ĐỦ. Model chính: Qwen2.5-14B-Instruct. Tuoke là model ưu tiên số 1 cho mọi việc.

## 1. Mục tiêu
- Model phân tích chứng khoán Việt Nam (tiếng Việt, kết luận trước).
- Skill lấy tạm từ bot LightVela 1.
- Dự án RIÊNG, độc lập Pocket Personal: tài khoản Cloudflare riêng + GitHub riêng.
  - GitHub: LangTieu (lethanhdongbr@gmx.com). Repo Public: https://github.com/LangTieu/vn-stock-ai
  - Cloudflare: Skillshare01br@mail.com (acc dự án, id `e6e3dca05591f48f9bc8a58767c3ee01`). Token `Muse_ai_build` đã nối.
  - Hugging Face: Jerlob (lethanhd0ngbr@mail.com), Free. Token Write `Muse_ai_build`.
  - Google Drive: thư mục `vn-stock-ai/` trên TK1 (lethienhieuhcm@gmail.com), 3 thư mục con `models/` `datasets/` `checkpoints/`; đã share writer cho TK2 (lethanhdongus@gmail.com).

## 2. Skill (nền tảng)
- `vn-stock-market-research` — bản local `~/workspace/custom-skills/vn-stock-market-research/`, gốc bot LightVela 1 (@br_stock_bot). Tự đồng bộ 6h/lần từ bot (cron `lv1-skills-sync`).
- Dạy: tóm tắt phiên, phân tích 1 mã (OHLCV qua api-finfo, chart MA/RSI/MACD, hỗ trợ/kháng cự), khối ngoại + tự doanh theo mã qua nmquan, output tiếng Việt kết luận trước + disclaimer.
- Giới hạn cứng: chỉ có khối ngoại + tự doanh theo mã/phiên (không có tổ chức/cá nhân theo mã); margin chỉ theo quý; nguồn chết đã biết: finfo-api, Yahoo query1/2 (429), TCBS/DNSE/stockbiz API — đi thẳng api-finfo.
- **Đánh giá 09/11 (xem `bot-lightvela1/EVALUATION.md`):** skill tốt, trung thực về backtest (bộ 6-signal THUA, K1–K5 VÔ DỤNG, chiến lược thắng = RSI<35 hoặc dd≥10% + MACD flip). Lỗi nhỏ: nhắc `flow_500.py` + `vnindex_full_chart.py` nhưng 2 file đó không còn trên máy; key Finhay ghi `~/.finhay_env` nhưng thật là `~/.finhay/credentials/.env`. Giữ nguyên skill, không sửa local (sync 6h ghi đè).

## 3. Kiến trúc
- Google Drive = kho lưu (model/backup/dataset/checkpoint). HF Hub = nguồn model gốc + đích adapter LoRA + thư viện train. Colab = xưởng train/test (T4 free). HF Space + ZeroGPU = demo (5 phút GPU/ngày, không train, không serve thật).
- Unified API Gateway 2 lớp: mặt tiền = Cloudflare Workers (auth key + rate limit + routing + logging, acc riêng); router/fallback = LiteLLM Proxy (Python/FastAPI, chạy ngoài Workers). Endpoint `/v1/chat/completions` qua adapter Gradio-to-OpenAI.
- Mode A (luôn sẵn): chuỗi fallback `vn-stock` = Tuoke gpt-6.1-sol/6-sol → Workers AI gpt-oss-120b (10.000 Neurons/ngày) → Cerebras gpt-oss-120b ($5 hết 25/11) → FOSTA key1 gpt-6.1-sol/astra/luna (45M token) → FOSTA key2 (55M token) → BeatAPI DeepSeek/GLM. Riêng IB1 có thêm 3 leg Gonka (GLM-5.3-Flash, DeepSeek-V4-Flash, MiniMax-M2.7 qua proxy.gonkabroker.com), ngoài chuỗi `vn-stock`, tự fallback lẫn nhau — từ 10/11 Gonka có trên cả 6 máy + thêm 1 leg `vn-stock-itera-qwen` mới (provider chưa rõ). "luôn sẵn" nghĩa là tự chuyển nhà cung cấp khác khi một cái hết, không phải token vô hạn.
- Mode B (demo): ZeroGPU Space.

## 4. Base model
- **Qwen2.5-14B-Instruct** (14,7B params, 128K context) — Chốt 19:20 08/11 "dừng ở 14B". 14B là cỡ lớn nhất chạy được trên T4 free (4-bit ~10GB VRAM). 32B không chạy được trên T4 free.
- **QLoRA từ đầu:** base 4-bit NF4 + double quant, compute float16. Adapter LoRA train ở P2.
- 7B giữ làm dự phòng. Tránh Llama 3.1 8B làm mặc định tiếng Việt.

## 5. Cách xây
- **P0.0 — Hạ tầng thử: XONG (trừ 1 test).** Space https://huggingface.co/spaces/Jerlob/vn-stock-ai (public, Gradio, zero-a10g) đã đổi sang 14B 4-bit 19:22 08/11, đang RUNNING; redeploy với prompt P0 20:45–20:56 10/11 (SYSTEM_PROMPT đầy đủ + sampling temp 0.1/top_p 0.75/top_k 40/max 1200); test sinh VCB 14B PASS (JSON hợp lệ, RSI 34,9 đúng, không bịa số); eval 14B trên Space chạy 5/60 rồi hết quota ZeroGPU, 55 run còn lại chạy xong trên Colab T4 23:11 10/11 (xem P0). Notebook test VCB thật (dữ liệu 06/11, `datasets/vcb_test.json`) đã chạy trên Colab T4 cho 1.5B/7B/14B/32B: 14B tốt nhất; 32B không chạy được; 4-bit cho kết quả lệch giữa các lần chạy → eval phải chạy nhiều lần. Dữ liệu test + kết quả đã đẩy lên Drive.
- **P0 — Skill-as-prompt (không train): XONG 15:21 10/11.** Prompt package trong `p0/` (system_prompt.txt 15 dòng + tool_spec.json + snapshot.py 102 dòng + vcb_snapshot.json; RSI 34,934, foreign −587,5 tỷ, prop +35,5 tỷ đã kiểm chứng đúng) + eval 20 mã × 3 run = 60 run, 0 lỗi, trên Tuoke 6 Sol qua LiteLLM. Kết quả Tuoke: rubric 10/10 (heuristic tự động); ABSTAIN 60/60 (đúng — snapshot thiếu BCTC/foreign-20/YTD/Fed); hướng 7/60 (11,67%, toàn DOWN); hit-rate hướng cổ phiếu 2/7 = 28,6%, hướng VN-Index 0/7 (VN-Index +14,18% trong cửa sổ). **Eval 14B XONG 23:11 10/11:** 60/60 run (5 Space + 55 Colab T4, 0 lỗi; Space redeploy với prompt P0 + sampling temp 0.1/top_p 0.75/top_k 40/max 1200; Colab A 28/28 TK1, B 27/27 TK2). Kết quả 14B: rubric 9,13/10 (Space 9,20; Colab A 9,21; B 9,04; STB 10,0 cao nhất); ABSTAIN 60/60, hướng UNKNOWN 60/60 — 0 dự đoán hướng (cùng nguyên nhân: snapshot thiếu BCTC/foreign-20/YTD/Fed — nợ P1, không phải lỗi eval). Kết quả gộp `p0/eval/results_14b.json` + đẩy GitHub (60/60 raw file). Lưu ý: mẫu 20 mã có look-ahead bias (xếp hạng từ dữ liệu sau cutoff) — hit-rate là kiểm tra prompt-data có kiểm soát, KHÔNG phải backtest out-of-sample.
- **P1 — Dataset: DỮ LIỆU THÔ ĐÃ ĐỦ (09/11), còn ráp dataset + mẫu CoT.**
  - (a) Spec chỉ số: **module chỉ báo ĐÃ XONG** — `scripts/indicators.py` (port từ `signal_engine.py` của bot LightVela 1, đã backtest; RSI(14) Wilder, EMA, MACD 12/26/9, SMA, ATR(14), Bollinger 20/2σ, OBV + logic tín hiệu đáy/đỉnh + winrate; đã kiểm chứng trên VCB thật; commit 90a5836). Ichimoku + volume-surge + buy-pressure + sector-flow + HAR-RV chưa có trong module — bổ sung khi ráp dataset. **RSI VCB tại 06/11 = 34,9 (Wilder chuẩn).** VCB hiện deep_now=True (RSI<35), chờ MACD flip.
  - (b) Dữ liệu thô: **ĐỦ 1.564 mã, 2014–2026, đã lên Drive.** Finhay (2017–2026: OHLCV + khối ngoại + tự doanh) 1.564/1.564 + finfo backfill (2014–2016: OHLCV) 1.564/1.564, gộp thành `datasets/train_2014_2026_<HOSE|HNX|UPCOM|OTC>.json` (0 mã thiếu; HOSE 154M, HNX 116M, UPCOM 251M, OTC nhỏ). Khối ngoại/tự doanh chỉ có từ 2017 (finfo không có). Script: `fetch_finhay_all.py`, `fetch_finfo_backfill_1416.py`, `merge_2014_2026.py`.
  - (c) Dataset ĐÃ RÁP XONG (build 10/11, rebuild 13:00 UTC): train 83.942, holdout 14.024 (13.824 bulk + 200 viết tay), smoke 7.503; hold-out tách theo thời gian; schema FinGPT instruction/input/output, loss chỉ trên output. Vòng sửa nội dung ĐÓNG 20:30 10/11 (200 mẫu phân biệt, có bằng chứng từng case, H001 sửa ngày 2026-11-06; rebuild dùng file HOSE mới MD5 34687491…). Nợ còn lại (giao Tuoke 20:43 10/11): BCTC fundamentals cho 200 mẫu + xác nhận holdout-range (STATE.md 2026-11-06 vs build.log 2026-11-09). Nguồn phụ Entrade/KBS/VPS/RSS chưa đưa vào. Không dùng vnstock (đã chết, proprietary).
  - (d) Vĩ mô: World Bank 2014–2025 đã lấy (CPI/GDP/lãi suất/M2, `datasets/macro_worldbank_2014.json`); USD/VND hằng ngày chạy cron 17:45 (`macro-tier1-daily-1745`, ghi `datasets/macro_daily.jsonl`). Treasury API bị chặn từ VM — cần FRED key hoặc đường máy cloud. FRED key vẫn chờ anh đăng ký.
- **P2 — LoRA fine-tune trên Qwen2.5-14B-Instruct (QLoRA): BẮT ĐẦU sau khi P1 xong nợ (Henrry lệnh 20:43 10/11).** Train ở Colab (cả 2 TK song song). Tách P2a (dự báo hướng TĂNG/GIẢM + xác suất 4 bậc) rồi P2b (Q&A/phân tích dài). Cấu hình: r=8, alpha=32, dropout=0.1, lr=1e-4, batch 4×grad_accum 8, warmup 0.05, linear, fp16, gradient checkpointing, epoch 2–3. **CẢNH BÁO: FinGPT ghi `qwen=["c_attn"]` là Qwen v1 — sai cho Qwen2.5, phải dùng Llama-style (`q/k/v/o_proj`).** Eval: temp 0.1, top_p 0.75, top_k 40. Phương pháp đo win-rate sau 20/60/120 phiên lấy từ `indicators.winrate()` (bot đã backtest).
- **P3 — Gateway: LIVE (10/11).** Workers (mặt tiền) + LiteLLM Proxy (router, ngoài Workers). LiteLLM chạy trên cả 6 máy (LV1/LV2/IB1–IB4, port 4000, 22 model/máy, 1 master key chung), chuỗi `vn-stock` như §3; fallback FOSTA 1-1 ra 6/6 router XONG 20:27 10/11 (health 200, chat test PING-OK cả 6 máy). Gateway https://vn-stock-ai-gateway.vn-stock-ai.workers.dev — /health upstreams:6, e2e test OK. LV1/LV2 qua Cloudflare Tunnel: healthy theo API nhưng edge không có route (acc không có DNS zone) — để làm fallback cuối, không tạo lại tunnel. Tailscale Funnel tạm gác. Còn lại: acceptance tests (hedge chat ~6s / first-token ~3s; 429=60s; 5xx=30s; breadth-first failover; EWMA latency).
- **P4 — Client độc lập:** khi P0–P2 đạt mới nối client (chatbot/AI Agent riêng), độc lập Pocket Personal.

## 6. Hạ tầng đã có
- GitHub repo LangTieu/vn-stock-ai (Public). Helper `custom.github/bin/github_api.py`. Workflow `.github/workflows/run-colab.yml` (dispatch notebook lên Colab qua vncolab, input notebook/gpu/timeout/runner).
- vncolab (`scripts/vncolab.py`): CLI Colab qua API (auth-url/auth-code, token file 0600). Đã xác nhận TK1 0 unit cấp được T4 free, tốn 0 unit. Cài trên cả 2 máy InstaBox (TK1 máy 1, TK2 máy 2) + runner GitHub `colab-driver` (máy 1) / `colab-driver-tk2` (máy 2). VM không chạy được vncolab (egress proxy chặn POST).
- Colab: TK1 lethienhieuhcm@gmail.com + TK2 lethanhdongus@gmail.com — cả 2 free T4, 0 unit, không subscribed. Dùng cả 2 acc train song song. (Câu hỏi mở: gói 122k/tháng đăng ký bằng email nào — chưa có câu trả lời.)
- Drive: thư mục vn-stock-ai (TK1) + share writer TK2. Cầu đồng bộ `scripts/drive_bridge.py` (status/push/pull, md5, không xóa). **Dữ liệu train 2014–2026 + vĩ mô đã lên Drive (20 file, md5 khớp).**
- HF Space: Jerlob/vn-stock-ai, 14B 4-bit, RUNNING. Token Write `Muse_ai_build`, connector custom.huggingface.
- Skill sync: cron `lv1-skills-sync` 6h/lần.
- **Agent chính: Perch (Chốt 23:06 08/11, thay Qoder cho dự án này; Qoder backup, 0 credit).** Perch CLI 2.4.126, acc lethanhdongbr@gmx.com, model free GLM 5.3 Flash (`--model glm-5.3-flash-starter`) / DeepSeek V4.1 Flash (`--model standard`). **Đã có trên 4 máy InstaBox (1, 2, 3, 4) + LightVela 1 (09/11).** Lưu ý: access token Perch chỉ sống 1 giờ (Supabase JWT) — `perch status` báo "Not signed in" gây hiểu lầm khi token hết hạn; cứ chạy lệnh Perch là nó tự refresh (refresh token còn sống). Không cần đăng nhập lại trừ khi refresh token chết.
- Macro cron: `macro-tier1-daily-1745` (T2–T6 17:45, USD/VND er-api).

## 7. Cần Chốt / việc mở
- Bắt đầu các bước build (CHƯA CODE vẫn giữ — cần lệnh anh để bắt đầu P0/P1/P2). **P1 đã sẵn dữ liệu + chỉ báo — chỉ còn ráp dataset + mẫu CoT là có thể bắt đầu khi anh Chốt.**
- Test sinh 14B trên Space (quota ZeroGPU reset 09/11 — chạy lại `scripts/test_space_14b.py`).
- Gói 122k/tháng đăng ký bằng email nào (chưa trả lời).
- FRED key (anh đăng ký tại fredaccount.stlouisfed.org, gửi qua form bảo mật) — mở Tier 2 vĩ mô (Fed funds, CPI Mỹ, DGS10) + lịch sử USD/VND.
- Verify live trước khi Chốt các bước liên quan: Radox api_base + model id; endpoint Entrade/VPS/KBS; per-key RPM/TPM LiteLLM; free tier Cerebras/Radox tại thời điểm build P3.

## 8. Giấy phép (đọc từ file thật trong clone 18 repo)
- Dùng được (giữ notice): FinGPT/AlphaFin/PIXIU/FinMem/litellm-free-models/freelm/lotusmarket/ai-hedge-fund MIT; TradingAgents/FinRobot/colabsh Apache-2.0. LiteLLM là MIT (metadata GitHub NOASSERTION sai) — không đụng `litellm/enterprise/` (thương mại).
- Chỉ tham khảo ý tưởng, không copy code: InvestLM (research-only), stock-foresight (không LICENSE), FinAgent (không xác định được), vnstock (proprietary, đã chết — không dùng).

## 9. Việc KHÔNG làm
- Không train lại model lớn, không đụng production stock.
- Không ghi token/key vào chat/file/log (trừ cách anh tự chọn: paste 1 lần dùng 1 lần rồi bỏ).
- Không premium-gate: tính năng mới free hết.
