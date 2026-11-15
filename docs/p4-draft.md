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
| Tin tức | **Henrry yêu cầu thêm vào P4.** Gateway P3 có bước grounding You.com Search (khối `GROUNDING_DATA`, fail-open) đã deploy 12/11 theo `docs/youcom-grounding/DEPLOY.md`, nhưng lúc đó You.com trả 403 nên **grounding chưa được xác minh hoạt động**. Chưa có danh sách nguồn tin được duyệt. | Chốt allowlist nguồn tin, tần suất cập nhật, ngưỡng độ mới, quyền sử dụng nội dung (chỉ tóm tắt + link) và cách xử lý tin thiếu ngày/giờ. |

### 1.2 Tài khoản, dịch vụ và thông tin xác thực

| Dịch vụ/kênh | Đã có | Còn cần trước khi bật |
|---|---|---|
| Apex `aistockvn.com` | Henrry xác nhận domain dùng cho trang bài viết hằng ngày. | Xác nhận tài khoản Cloudflare quản lý DNS/zone và không thay đổi apex record khi gắn P4. |
| Cloudflare Pages | Cloudflare Worker P3 đã có theo hồ sơ P3. **Pages project P4 chưa được xác minh/tạo.** | Tạo project Pages gắn với repo P4; thêm Custom Domain `chat.aistockvn.com` sau khi hostname được chốt; kiểm DNS/TLS/HTTPS. |
| P3 + LiteLLM | Gateway P3 có URL và secret bindings theo `p3-public-addr-STATE.md`; cấu hình/model alias có trong source repo. | Xác minh live Worker chuyển sang `vn-stock-assistant`; đồng bộ config alias/fallback trên tất cả LiteLLM upstream; test auth và SSE bằng credential test ít quyền. |
| Telegram | Repo ghi nhận bot LightVela 1 `@br_stock_bot`/skill tham chiếu. **Token bot, webhook và quyền dùng cho P4 chưa xác minh ở repo.** | Chủ sở hữu cung cấp/duyệt bot token qua secret store; cấu hình webhook HTTPS, test quyền và giới hạn. Không commit token. |
| Zalo | Chưa có bằng chứng OA/API P4 đã sẵn sàng. | Zalo Official Account, ứng dụng/quyền API, credential và webhook chính thức; xác minh hạn mức/chính sách tin nhắn hiện hành. |
| WhatsApp | Chưa có bằng chứng Business API P4 đã sẵn sàng. | Meta Business, WhatsApp Business Platform/Cloud API, số điện thoại/app, quyền duyệt, webhook và cấu hình template/cửa sổ tin nhắn; xác minh phí/quota hiện hành. |
| Nguồn tin tức | Secret `YOUCOM_API_KEY` đã có trên Worker P3 theo hồ sơ deploy 12/11; key/credit chưa xác minh lại sau lỗi 403. | Kiểm tra key/quota You.com hoặc chọn nguồn thay thế; xác minh điều khoản RSS/feed của từng nguồn báo chí trước khi lấy tự động. |
| Model/providers | P3 có cấu hình nguồn cho Cerebras và một số fallback; cấu hình trong repo không đảm bảo key còn hiệu lực hay upstream đang hoạt động. | Kiểm tra key/quota/điều khoản từng model (ví dụ Ember, Gemini, DeepSeek/GLM) phía server; chỉ bật model đã được duyệt. |

**Thứ tự sẵn sàng:** (1) chốt repo/project, hostname và auth web an toàn; (2) xác minh P3/LiteLLM alias/fallback cùng credentials; (3) bật web + Telegram nếu token/quyền sẵn sàng; (4) triển khai Zalo/WhatsApp sau khi có đủ tài khoản/API chính thức. Không coi mục “có cấu hình trong file” là bằng chứng deploy thành công.

## 2. Cách làm sau khi prerequisites được duyệt

### 2.1 Sản phẩm và phạm vi MVP

P4 là trợ lý AI phân tích thị trường/chứng khoán Việt Nam, chạy cùng backend nghiệp vụ qua web và các adapter kênh. Các kênh chỉ khác giao thức giao tiếp; mọi tin nhắn được chuẩn hóa vào cùng pipeline P4/P3, dùng chung skill, policy, model routing và format phản hồi. Không nhân bản logic/model cho từng bot.

Năng lực nghiệp vụ theo bot LightVela 1 (`@br_stock_bot`) và skill `vn-stock-market-research`:

1. Tóm tắt phiên giao dịch từ dữ liệu có sẵn, kèm ngày/nguồn.
2. Phân tích một mã: OHLCV, RSI/MACD và vùng hỗ trợ/kháng cự khi dữ liệu cho phép.
3. Khối ngoại và tự doanh theo mã, ghi rõ cửa sổ thời gian/đơn vị/nguồn; báo “không có số liệu” khi thiếu.
4. Tóm tắt tin tức thị trường/vĩ mô trong ngày: nhóm theo vĩ mô Việt Nam, vĩ mô thế giới có tác động tới VN, thị trường chứng khoán và tin doanh nghiệp nổi bật; mỗi tin ghi nguồn + ngày/giờ đăng; nêu mốc “tin cập nhật đến HH:MM ngày DD/MM/YYYY (giờ VN)”.
5. Trả lời câu hỏi về tin tức: tin vĩ mô (lãi suất, tỷ giá, CPI, GDP, chính sách NHNN/Bộ Tài chính, Fed…), tin doanh nghiệp/mã (công bố thông tin, kết quả kinh doanh, cổ tức, giao dịch nội bộ, M&A…) và tin thị trường (thanh khoản, dòng tiền, quy định UBCKNN/HOSE/HNX…). Chỉ dùng tin truy xuất được từ nguồn đã duyệt; phân biệt nội dung tin với nhận định của trợ lý.
6. Trả lời tiếng Việt, kết luận trước rồi số liệu/luận cứ sau; luôn có disclaimer: thông tin tham khảo, không phải khuyến nghị đầu tư. Không bịa số hoặc tuyên bố dữ liệu realtime nếu chưa xác nhận.

**Chuẩn chống bịa cho tin tức** (cùng chuẩn với các năng lực trên):

- Mỗi tin nêu ra phải có tên nguồn, link và ngày/giờ đăng (giờ VN, UTC+7). Tin không có nguồn thì không dùng; tin thiếu thời điểm đăng không được tính là “tin trong ngày” và phải ghi “không rõ thời điểm đăng”.
- Không bịa tin, không dùng kiến thức huấn luyện của model như tin hiện tại, không biến tin đồn/mạng xã hội thành sự kiện. Không tìm thấy tin trong cửa sổ độ mới thì trả lời rõ “không có tin/số liệu từ nguồn đã duyệt trong [cửa sổ]”, kèm mốc cập nhật gần nhất.
- Con số trong tin (lãi suất, CPI, lợi nhuận…) được trích kèm nguồn tin, không trộn với số liệu có cấu trúc (OHLCV, khối ngoại, BCTC); số BCTC vẫn chỉ lấy từ dữ liệu đã xác minh. Hai nguồn mâu thuẫn thì nêu cả hai, không tự chọn.
- Tóm tắt ngắn bằng lời của trợ lý kèm link, không chép nguyên văn dài bài báo.

**Kỹ thuật tin tức (đề xuất):**

- **Hai đường lấy tin, chạy server-side:** (a) *bộ thu tin định kỳ* cho bản tóm tắt trong ngày, lấy từ allowlist nguồn qua RSS/feed/trang công bố chính thức được phép; (b) *tìm theo câu hỏi* qua bước grounding You.com Search đã có ở gateway P3, giới hạn theo allowlist domain và bộ lọc độ mới. Không gọi nguồn tin từ trình duyệt/kênh và không lộ key.
- **Allowlist nguồn đề xuất:** nguồn chính thức (NHNN, Bộ Tài chính, Cục Thống kê, UBCKNN, công bố thông tin HOSE/HNX/VSDC, website IR doanh nghiệp) ưu tiên hơn báo tài chính (ví dụ Vietstock, CafeF, VnEconomy, Đầu tư Chứng khoán; Reuters/Bloomberg cho vĩ mô thế giới) — danh sách cuối do Henrry duyệt. Apex `aistockvn.com` không thuộc P4; P4 không đọc/ghi apex trừ khi được duyệt riêng.
- **Bản ghi tin chuẩn hóa:** `tieu_de`, `nguon`, `url`, `thoi_diem_dang` (ICT), `thoi_diem_lay`, `loai` (`vi_mo` | `doanh_nghiep` | `thi_truong`), `ma_lien_quan[]`, `tom_tat_ngan`; khử trùng lặp theo URL/tiêu đề. Đưa vào prompt dạng khối dữ liệu tin (như `GROUNDING_DATA`); model chỉ được nêu tin có trong khối.
- **Tần suất đề xuất:** 15 phút/lần trong giờ giao dịch (9:00–15:00 ICT ngày giao dịch), 60 phút/lần ngoài giờ; bản tóm tắt dựng sẵn lúc ~8:30 (trước phiên) và ~15:30 (sau phiên); câu hỏi trong ngày dùng bộ tin mới nhất.
- **Ngưỡng độ mới đề xuất:** “trong ngày” = từ 00:00 ICT hôm nay; câu hỏi tin doanh nghiệp/thị trường mặc định 72 giờ; tin vĩ mô 7 ngày (số liệu vĩ mô theo kỳ công bố thì nêu kỳ). Người dùng hỏi mốc cũ hơn thì tìm theo mốc đó và ghi rõ ngày. Tin cũ hơn ngưỡng chỉ được nêu khi ghi rõ là tin cũ.
- **Chế độ trả lời tin tức:** câu hỏi thuần tin tức dùng format tin (tóm tắt → danh sách tin có nguồn/giờ → giới hạn → disclaimer), không bị ép vào khuyến nghị/ABSTAIN của format phân tích mã — `docs/youcom-grounding/VERIFY.md` cho thấy format P0 hiện ép ABSTAIN ngay cả khi đã có tin có nguồn.
- **Lưu trữ:** bộ thu tin cần cache nhỏ chỉ chứa tin công khai, có TTL (ví dụ Cloudflare KV/D1), không chứa dữ liệu người dùng — ngoại lệ có giới hạn của nguyên tắc “MVP không có database P4” ở §2.4, cần duyệt.

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
- **Tin tức:** bộ thu tin định kỳ và bước tìm tin theo câu hỏi nằm phía server, trước bước gọi model; mọi kênh dùng chung kho/khối tin nên cùng câu hỏi nhận cùng bộ tin ở web và bot.

### 2.3 Model tạm, nhiều model và chuyển sang P2

- **Model tạm đã chọn:** alias P4 server-side **`vn-stock-assistant` → Cerebras `gpt-oss-120b`**, giữ cùng fallback chain hiện có của alias `vn-stock`. Cấu hình nguồn alias có trong repo LiteLLM; Worker nguồn được cập nhật để ép request P4 vào alias này. Đây là lựa chọn theo model/upstream đã có trong P3 và đường gateway đã kiểm thử, không phải kết luận benchmark tiếng Việt tốt nhất. Cần xác minh deploy Worker và alias trên mọi LiteLLM upstream theo prerequisite trước khi dùng production.
- **Sau P2:** đánh giá/phê duyệt adapter cuối; đổi cấu hình LiteLLM server-side của alias `vn-stock-assistant` sang Qwen2.5-14B-Instruct + LoRA P2 đã pin revision. Client/kênh không đổi alias. Canary, kiểm tra health/chất lượng và rollback về cấu hình tạm nếu giảm chất lượng.
- **Nhiều model:** cho phép thêm Ember, Gemini, DeepSeek/GLM qua P3/LiteLLM sau khi xác minh model ID, credential, quota/chi phí, điều khoản dữ liệu và chất lượng. Ví dụ không đồng nghĩa model đã cấu hình/duyệt.
- **Chọn model:** mặc định policy server-side theo tác vụ; web có thể cho chọn trong allowlist đã duyệt; bot dùng policy mặc định, không tự chọn endpoint. Ghi nhận model thực tế được dùng.
- **Fallback:** chỉ tự chuyển model khi lỗi hạ tầng phục hồi được (timeout, unavailable, 5xx); không âm thầm fallback do 4xx/prompt/quyền hoặc chất lượng thấp. Giới hạn retry/thời gian, không vượt allowlist, thông báo khi đổi model ảnh hưởng kết quả.
- **Nhất quán:** cùng system policy, skill `vn-stock-market-research`, kết luận-trước, quy tắc OHLCV/RSI/MACD/hỗ trợ-kháng cự, cửa sổ khối ngoại/tự doanh, chuẩn nguồn/ngày giờ/độ mới của tin tức và disclaimer; dùng một bộ acceptance test cho mọi model/kênh. Không giả định các model tương đương chỉ vì cùng API.

### 2.4 Công nghệ

- TypeScript + React + Vite: SPA/PWA tĩnh, kiểu dữ liệu giúp xử lý API/SSE.
- Cloudflare Pages: chỉ host web tĩnh; custom domain là hostname con P4, giữ apex cho website bài viết.
- Adapters server-side Telegram/Zalo/WhatsApp: webhook/API chính thức, chuẩn hóa event vào backend chung.
- P3 Worker + LiteLLM: cổng chung `/v1/chat/completions`, auth/rate limit/model alias/fallback; provider keys chỉ phía server.
- OpenAI-compatible API/SSE: giao thức thống nhất, tránh phụ thuộc SDK nhà cung cấp.
- MVP không có database P4: web lưu local; bot giữ short context riêng trong thời hạn được duyệt. Không đồng bộ đa kênh/lưu lâu dài nếu chưa có quyết định quyền riêng tư. Ngoại lệ đề xuất: cache tin công khai có TTL cho năng lực tin tức (xem §2.1), không chứa dữ liệu người dùng.
- Tin tức: bộ thu tin là job định kỳ server-side (ví dụ Cloudflare Cron Trigger) đọc RSS/feed/trang công bố trong allowlist; tìm theo câu hỏi dùng You.com Search ở gateway P3.

### 2.5 Lộ trình M0–M7 và kiểm chứng

| Mốc | Công việc | Điều kiện hoàn tất |
|---|---|---|
| M0 — prerequisites/quyết định | Hoàn tất các mục chưa sẵn sàng ở phần 1: repo/project, hostname, auth, model alias live, token/quyền các kênh, credentials/upstream. | Checklist prerequisites được owner xác nhận; không triển khai kênh thiếu quyền/credential. |
| M1 — hợp đồng chung | Định nghĩa event schema, namespace user/conversation, format câu trả lời (gồm format tin tức), dữ liệu/nguồn/ngày, bản ghi tin chuẩn hóa, lỗi/SSE và policy model. | Contract test cho mọi adapter; không ghép identity giữa kênh. |
| M2 — Web + P3 | Xây UI React/Vite, stream `/v1/chat/completions`, deploy preview Pages tại hostname con sau khi DNS/Pages sẵn sàng. | Chat/stop/retry, HTTPS, auth an toàn; bundle không có master/provider key; apex không đổi. |
| M3 — Telegram adapter | Webhook/Bot API server-side, xác minh update, chuẩn hóa ID và gọi backend chung. | Test chat và các tác vụ; namespace/secret đúng, dùng cùng policy/model. |
| M4 — năng lực research + tin tức | Tích hợp tóm tắt phiên, phân tích mã/chỉ báo/vùng giá, khối ngoại/tự doanh, kết luận trước/disclaimer. Tin tức: xác minh lại grounding You.com (hết 403) hoặc nguồn thay thế; bộ thu tin theo allowlist/tần suất đã duyệt; tóm tắt tin trong ngày; hỏi đáp tin vĩ mô/doanh nghiệp/thị trường; chế độ trả lời tin tức tách khỏi format khuyến nghị. | Bộ test nghiệp vụ đạt; thiếu dữ liệu báo rõ, không bịa; web/Telegram nhất quán. Tin tức: mọi tin trong câu trả lời có nguồn + link + ngày/giờ khớp bản ghi nguồn; không có tin ngoài khối dữ liệu tin; tin quá ngưỡng độ mới không được gọi là tin mới; câu hỏi không có tin trả lời “không có tin/số liệu từ nguồn đã duyệt”; bản tóm tắt có mốc cập nhật và chạy đúng lịch. |
| M5 — alias model tạm/đa model | Xác minh/deploy alias `vn-stock-assistant` (Cerebras `gpt-oss-120b` + fallback `vn-stock`); test các upstream; thêm model sau duyệt. | Alias tồn tại trên mọi LiteLLM host; P3 chat test, fallback/log model và rollback được kiểm chứng. |
| M6 — Zalo/WhatsApp | Chỉ sau khi OA/Business API, quyền duyệt, credential/webhook/chi phí sẵn sàng; triển khai adapter riêng vào pipeline chung. | Từng kênh qua webhook/auth/identity/rate-limit và test nghiệp vụ chính thức. |
| M7 — promote P2 và phát hành | Đánh giá/pin LoRA cuối; đổi alias server-side sang Qwen2.5-14B + adapter, canary/rollback; deploy Pages production và bật kênh đã duyệt. | Chất lượng/health/latency/fallback đạt; domain HTTPS, từng kênh được owner nghiệm thu. |

**Tiêu chí chung:** cùng bộ test qua kênh/model; kết luận tiếng Việt trước, số liệu và tin tức có nguồn/ngày(giờ)/đơn vị, disclaimer; thiếu dữ liệu không bịa; identity không rò/ghép; fallback minh bạch; không lộ key. Chốt ngưỡng latency/chất lượng/chi phí trước pilot.

## Câu hỏi duyệt còn lại

1. Repo/tài khoản riêng sở hữu P4 và hostname con chính thức (đề xuất `chat.aistockvn.com`)? Ai quản lý Pages/DNS?
2. Cơ chế auth client web ít quyền nào được duyệt; P3 live alias `vn-stock-assistant` đã deploy/xác minh trên toàn bộ upstream chưa?
3. MVP có gồm web + Telegram không; Zalo/WhatsApp để phase sau tới khi OA/Business API và quyền chính thức sẵn sàng?
4. Duyệt Cerebras `gpt-oss-120b` qua alias P4 làm model tạm; sau P2 chuyển sang LoRA đã đánh giá? Model bổ sung nào được bật/chọn và theo tiêu chí nào?
5. Fallback order, timeout/retry, budget/chi phí và cách báo người dùng khi fallback?
6. Credential owner, retention, consent/identity linking, analytics/logging và ngưỡng chất lượng/độ trễ nào được duyệt?
7. Tin tức — nguồn: duyệt allowlist nguồn chính thức và báo tài chính (đề xuất ở §2.1)? Tiếp tục dùng You.com Search (cần xử lý lỗi 403, kiểm tra key/credit) hay thêm/thay nguồn khác? Có dùng bài trên apex `aistockvn.com` làm nguồn chỉ-đọc không (mặc định: không)?
8. Tin tức — tần suất và độ mới: duyệt 15 phút trong giờ giao dịch/60 phút ngoài giờ, bản tóm tắt ~8:30 và ~15:30 ICT; ngưỡng “trong ngày” từ 00:00 ICT, 72 giờ cho tin doanh nghiệp/thị trường, 7 ngày cho tin vĩ mô?
9. Tin tức — lưu trữ và bản quyền: duyệt cache tin công khai có TTL (ngoại lệ “không database”) và quy tắc chỉ tóm tắt ngắn + link, không chép nguyên văn?
