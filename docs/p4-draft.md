# Bản thảo P4 — Trợ lý phân tích chứng khoán đa kênh, đa model

**Trạng thái:** bản đề xuất để Henrry duyệt; chưa triển khai P4, tạo tài khoản/kênh mới hay phát hành production.

## 1. Cần chuẩn bị và chốt trước khi bắt tay triển khai

Các trạng thái dưới đây phân biệt việc đã có bằng chứng trong repo/kế hoạch với việc chưa xác minh. “Có mã nguồn” không đồng nghĩa dịch vụ production đã được cấu hình/deploy.

### 1.1 Quyết định sản phẩm cần chốt

| Hạng mục | Trạng thái hiện tại | Cần chuẩn bị/chốt |
|---|---|---|
| Phân chia domain | **Đã chốt:** apex `aistockvn.com` là trang đăng bài hằng ngày về chứng khoán, vĩ mô Việt Nam và vĩ mô thế giới. P4 không chiếm apex. | **Chờ chốt:** hostname P4, đề xuất `chat.aistockvn.com`. |
| Kênh | **Đã chốt hướng:** P4 là web chat, không phải Telegram bot đơn lẻ; định hướng đa kênh cùng backend P3. | Chốt MVP gồm web + Telegram; Zalo/WhatsApp làm MVP hay phase sau. |
| Repo/tài khoản P4 | **Chưa xác định trong bản thảo/repo.** | Chọn repo, chủ sở hữu, Cloudflare account/Pages project riêng, không dùng lại Pocket Personal. |
| Xác thực client web | P3 gateway có `GATEWAY_API_KEY` và LiteLLM master key theo hồ sơ P3; **chưa có phương án an toàn đã chốt cho client web công khai**. | Thiết kế xác thực/rate limit cho người dùng cuối. Không nhúng gateway/master/provider key vào JavaScript tĩnh. |
| Model tạm và chuyển model | **Có trong mã nguồn:** alias `vn-stock-assistant` được thêm vào hai cấu hình LiteLLM và Worker nguồn. **Chưa xác minh deploy trên P3 production.** | Xác minh alias/fallback trên mọi upstream đang chạy; sau P2 duyệt adapter cuối rồi chuyển alias server-side. |
| Lưu lịch sử | Đề xuất MVP lưu web history cục bộ, bot short-context riêng từng kênh. | Henrry duyệt thời hạn short context, retention và việc có/không gửi prompt vào analytics/log. |
| Chất lượng/dữ liệu | Có skill `vn-stock-market-research` và bộ năng lực đã chốt. | Chốt nguồn/ngày dữ liệu, ngưỡng độ mới/chất lượng, bộ acceptance test và ngưỡng latency/chi phí. |

### 1.2 Tài khoản, dịch vụ và thông tin xác thực

| Dịch vụ/kênh | Đã có | Còn cần trước khi bật |
|---|---|---|
| Apex `aistockvn.com` | Henrry xác nhận domain dùng cho trang bài viết hằng ngày. | Xác nhận tài khoản Cloudflare quản lý DNS/zone và không thay đổi apex record khi gắn P4. |
| Cloudflare Pages | Cloudflare Worker P3 đã có theo hồ sơ P3. **Pages project P4 chưa được xác minh/tạo.** | Tạo project Pages gắn với repo P4; thêm Custom Domain `chat.aistockvn.com` sau khi hostname được chốt; kiểm DNS/TLS/HTTPS. |
| P3 + LiteLLM | Gateway P3 có URL và secret bindings theo `p3-public-addr-STATE.md`; cấu hình/model alias có trong source repo. | Xác minh live Worker chuyển sang `vn-stock-assistant`; đồng bộ config alias/fallback trên tất cả LiteLLM upstream; test auth và SSE bằng credential test ít quyền. |
| Telegram | Repo ghi nhận bot LightVela 1 `@br_stock_bot`/skill tham chiếu. **Token bot, webhook và quyền dùng cho P4 chưa xác minh ở repo.** | Chủ sở hữu cung cấp/duyệt bot token qua secret store; cấu hình webhook HTTPS, test quyền và giới hạn. Không commit token. |
| Zalo | Chưa có bằng chứng OA/API P4 đã sẵn sàng. | Zalo Official Account, ứng dụng/quyền API, credential và webhook chính thức; xác minh hạn mức/chính sách tin nhắn hiện hành. |
| WhatsApp | Chưa có bằng chứng Business API P4 đã sẵn sàng. | Meta Business, WhatsApp Business Platform/Cloud API, số điện thoại/app, quyền duyệt, webhook và cấu hình template/cửa sổ tin nhắn; xác minh phí/quota hiện hành. |
| Model/providers | P3 có cấu hình nguồn cho Cerebras và một số fallback; cấu hình trong repo không đảm bảo key còn hiệu lực hay upstream đang hoạt động. | Kiểm tra key/quota/điều khoản từng model (ví dụ Ember, Gemini, DeepSeek/GLM) phía server; chỉ bật model đã được duyệt. |

**Thứ tự sẵn sàng:** (1) chốt repo/project, hostname và auth web an toàn; (2) xác minh P3/LiteLLM alias/fallback cùng credentials; (3) bật web + Telegram nếu token/quyền sẵn sàng; (4) triển khai Zalo/WhatsApp sau khi có đủ tài khoản/API chính thức. Không coi mục “có cấu hình trong file” là bằng chứng deploy thành công.

## 2. Cách làm sau khi prerequisites được duyệt

### 2.1 Sản phẩm và phạm vi MVP

P4 là trợ lý AI phân tích thị trường/chứng khoán Việt Nam, chạy cùng backend nghiệp vụ qua web và các adapter kênh. Các kênh chỉ khác giao thức giao tiếp; mọi tin nhắn được chuẩn hóa vào cùng pipeline P4/P3, dùng chung skill, policy, model routing và format phản hồi. Không nhân bản logic/model cho từng bot.

Năng lực nghiệp vụ theo bot LightVela 1 (`@br_stock_bot`) và skill `vn-stock-market-research`:

1. Tóm tắt phiên giao dịch từ dữ liệu có sẵn, kèm ngày/nguồn.
2. Phân tích một mã: OHLCV, RSI/MACD và vùng hỗ trợ/kháng cự khi dữ liệu cho phép.
3. Khối ngoại và tự doanh theo mã, ghi rõ cửa sổ thời gian/đơn vị/nguồn; báo “không có số liệu” khi thiếu.
4. Trả lời tiếng Việt, kết luận trước rồi số liệu/luận cứ sau; luôn có disclaimer: thông tin tham khảo, không phải khuyến nghị đầu tư. Không bịa số hoặc tuyên bố dữ liệu realtime nếu chưa xác nhận.

MVP đề xuất: web chat + một adapter Telegram; stream ở web; hội thoại ngắn tách theo người dùng/kênh; xóa/reset, rate limit và lỗi rõ ràng. Zalo/WhatsApp bật theo giai đoạn sau khi đủ điều kiện chính thức. Ngoài phạm vi: đặt lệnh, tự nhận là môi giới/tư vấn, lưu lịch sử lâu dài, fine-tune riêng theo kênh, hoặc tích hợp Pocket Personal.

### 2.2 Kiến trúc đa kênh, đa model

```text
Apex aistockvn.com: trang bài viết hằng ngày (giữ nguyên, không thuộc P4)
P4 web: chat.aistockvn.com (đề xuất) ───────────────────┐
Telegram Bot API ────────────────────────────────────────┤
Zalo Official Account API/webhook ───────────────────────┼─> Adapter kênh P4
WhatsApp Business Platform/Cloud API ────────────────────┘      │
                                                                   v
                       Chuẩn hóa định danh + conversation + policy + skill
                                                                   │
                                                                   v
                 P3 Cloudflare Worker gateway /v1/chat/completions
                    auth, rate limit, logging, failover, routing
                                                                   │
                                                                   v
                 LiteLLM alias vn-stock-assistant + fallback/upstreams
                 Tạm: Cerebras gpt-oss-120b; sau P2: Qwen2.5-14B + LoRA
```

- **Web:** file tĩnh trên Cloudflare Pages ở hostname con `chat.aistockvn.com` (đề xuất). Không trỏ hoặc thay nội dung apex; trình duyệt gọi HTTPS/SSE qua P3.
- **Telegram:** adapter Telegram Bot API. Định danh namespace `telegram:<bot-id>:<chat_id>`; username hiển thị không phải định danh ổn định. Token chỉ ở server secret store.
- **Zalo:** chỉ dùng Zalo Official Account và API/webhook chính thức; cần OA, quyền ứng dụng, credential, webhook. Định danh `zalo:<oa-id>:<user-id>`.
- **WhatsApp:** chỉ dùng WhatsApp Business Platform/Cloud API chính thức; cần Meta Business, app/số phù hợp, quyền duyệt và webhook; có thể có quy tắc template/cửa sổ hội thoại và phí. Định danh `whatsapp:<phone-number-id>:<wa-id>`. Không dùng automation WhatsApp Web.
- Mặc định namespace/short context tách riêng theo nền tảng và bot/OA/phone number; không tự ghép người dùng giữa các kênh. Liên kết đa kênh cần consent và thiết kế riêng.
- Adapter chuẩn hóa channel, channel_user_id, conversation_id, nội dung, locale, thời điểm và metadata cho phép; cùng policy/skill/model routing; trả lời về đúng kênh nguồn.

### 2.3 Model tạm, nhiều model và chuyển sang P2

- **Model tạm đã chọn:** alias P4 server-side **`vn-stock-assistant` → Cerebras `gpt-oss-120b`**, giữ cùng fallback chain hiện có của alias `vn-stock`. Cấu hình nguồn alias có trong repo LiteLLM; Worker nguồn được cập nhật để ép request P4 vào alias này. Đây là lựa chọn theo model/upstream đã có trong P3 và đường gateway đã kiểm thử, không phải kết luận benchmark tiếng Việt tốt nhất. Cần xác minh deploy Worker và alias trên mọi LiteLLM upstream theo prerequisite trước khi dùng production.
- **Sau P2:** đánh giá/phê duyệt adapter cuối; đổi cấu hình LiteLLM server-side của alias `vn-stock-assistant` sang Qwen2.5-14B-Instruct + LoRA P2 đã pin revision. Client/kênh không đổi alias. Canary, kiểm tra health/chất lượng và rollback về cấu hình tạm nếu giảm chất lượng.
- **Nhiều model:** cho phép thêm Ember, Gemini, DeepSeek/GLM qua P3/LiteLLM sau khi xác minh model ID, credential, quota/chi phí, điều khoản dữ liệu và chất lượng. Ví dụ không đồng nghĩa model đã cấu hình/duyệt.
- **Chọn model:** mặc định policy server-side theo tác vụ; web có thể cho chọn trong allowlist đã duyệt; bot dùng policy mặc định, không tự chọn endpoint. Ghi nhận model thực tế được dùng.
- **Fallback:** chỉ tự chuyển model khi lỗi hạ tầng phục hồi được (timeout, unavailable, 5xx); không âm thầm fallback do 4xx/prompt/quyền hoặc chất lượng thấp. Giới hạn retry/thời gian, không vượt allowlist, thông báo khi đổi model ảnh hưởng kết quả.
- **Nhất quán:** cùng system policy, skill `vn-stock-market-research`, kết luận-trước, quy tắc OHLCV/RSI/MACD/hỗ trợ-kháng cự, cửa sổ khối ngoại/tự doanh và disclaimer; dùng một bộ acceptance test cho mọi model/kênh. Không giả định các model tương đương chỉ vì cùng API.

### 2.4 Công nghệ

- TypeScript + React + Vite: SPA/PWA tĩnh, kiểu dữ liệu giúp xử lý API/SSE.
- Cloudflare Pages: chỉ host web tĩnh; custom domain là hostname con P4, giữ apex cho website bài viết.
- Adapters server-side Telegram/Zalo/WhatsApp: webhook/API chính thức, chuẩn hóa event vào backend chung.
- P3 Worker + LiteLLM: cổng chung `/v1/chat/completions`, auth/rate limit/model alias/fallback; provider keys chỉ phía server.
- OpenAI-compatible API/SSE: giao thức thống nhất, tránh phụ thuộc SDK nhà cung cấp.
- MVP không có database P4: web lưu local; bot giữ short context riêng trong thời hạn được duyệt. Không đồng bộ đa kênh/lưu lâu dài nếu chưa có quyết định quyền riêng tư.

### 2.5 Lộ trình M0–M7 và kiểm chứng

| Mốc | Công việc | Điều kiện hoàn tất |
|---|---|---|
| M0 — prerequisites/quyết định | Hoàn tất các mục chưa sẵn sàng ở phần 1: repo/project, hostname, auth, model alias live, token/quyền các kênh, credentials/upstream. | Checklist prerequisites được owner xác nhận; không triển khai kênh thiếu quyền/credential. |
| M1 — hợp đồng chung | Định nghĩa event schema, namespace user/conversation, format câu trả lời, dữ liệu/nguồn/ngày, lỗi/SSE và policy model. | Contract test cho mọi adapter; không ghép identity giữa kênh. |
| M2 — Web + P3 | Xây UI React/Vite, stream `/v1/chat/completions`, deploy preview Pages tại hostname con sau khi DNS/Pages sẵn sàng. | Chat/stop/retry, HTTPS, auth an toàn; bundle không có master/provider key; apex không đổi. |
| M3 — Telegram adapter | Webhook/Bot API server-side, xác minh update, chuẩn hóa ID và gọi backend chung. | Test chat và các tác vụ; namespace/secret đúng, dùng cùng policy/model. |
| M4 — năng lực research | Tích hợp tóm tắt phiên, phân tích mã/chỉ báo/vùng giá, khối ngoại/tự doanh, kết luận trước/disclaimer. | Bộ test nghiệp vụ đạt; thiếu dữ liệu báo rõ, không bịa; web/Telegram nhất quán. |
| M5 — alias model tạm/đa model | Xác minh/deploy alias `vn-stock-assistant` (Cerebras `gpt-oss-120b` + fallback `vn-stock`); test các upstream; thêm model sau duyệt. | Alias tồn tại trên mọi LiteLLM host; P3 chat test, fallback/log model và rollback được kiểm chứng. |
| M6 — Zalo/WhatsApp | Chỉ sau khi OA/Business API, quyền duyệt, credential/webhook/chi phí sẵn sàng; triển khai adapter riêng vào pipeline chung. | Từng kênh qua webhook/auth/identity/rate-limit và test nghiệp vụ chính thức. |
| M7 — promote P2 và phát hành | Đánh giá/pin LoRA cuối; đổi alias server-side sang Qwen2.5-14B + adapter, canary/rollback; deploy Pages production và bật kênh đã duyệt. | Chất lượng/health/latency/fallback đạt; domain HTTPS, từng kênh được owner nghiệm thu. |

**Tiêu chí chung:** cùng bộ test qua kênh/model; kết luận tiếng Việt trước, số liệu có nguồn/ngày/đơn vị, disclaimer; thiếu dữ liệu không bịa; identity không rò/ghép; fallback minh bạch; không lộ key. Chốt ngưỡng latency/chất lượng/chi phí trước pilot.

## Câu hỏi duyệt còn lại

1. Repo/tài khoản riêng sở hữu P4 và hostname con chính thức (đề xuất `chat.aistockvn.com`)? Ai quản lý Pages/DNS?
2. Cơ chế auth client web ít quyền nào được duyệt; P3 live alias `vn-stock-assistant` đã deploy/xác minh trên toàn bộ upstream chưa?
3. MVP có gồm web + Telegram không; Zalo/WhatsApp để phase sau tới khi OA/Business API và quyền chính thức sẵn sàng?
4. Duyệt Cerebras `gpt-oss-120b` qua alias P4 làm model tạm; sau P2 chuyển sang LoRA đã đánh giá? Model bổ sung nào được bật/chọn và theo tiêu chí nào?
5. Fallback order, timeout/retry, budget/chi phí và cách báo người dùng khi fallback?
6. Credential owner, retention, consent/identity linking, analytics/logging và ngưỡng chất lượng/độ trễ nào được duyệt?
