# Bản thảo P4 — Trợ lý phân tích chứng khoán đa kênh, đa model

**Trạng thái:** Bản đề xuất cập nhật để Henrry duyệt. Chưa triển khai mã, chưa tạo tích hợp kênh hoặc deploy.

## 1. Sản phẩm và phạm vi

P4 là trợ lý AI phân tích thị trường/chứng khoán Việt Nam, dùng cùng một backend nghiệp vụ qua nhiều kênh: web trên tên miền thuộc **`aistockvn.com`** (đề xuất `chat.aistockvn.com`, chờ chốt), Telegram, Zalo và WhatsApp. P4 không phải bot Telegram đơn lẻ; đây là trợ lý đa kênh với web là một trong các kênh truy cập. Đây là sản phẩm độc lập Pocket Personal: repo, giao diện, cấu hình, triển khai, thông tin xác thực và dữ liệu riêng.

Các kênh chỉ là những adapter giao tiếp khác nhau; tất cả phải chuẩn hóa tin nhắn vào **cùng backend P4 và gateway P3**, dùng chung skill, chính sách, định tuyến model và định dạng câu trả lời. Không triển khai một chatbot/model/logic phân tích riêng cho từng bot/kênh.

**Năng lực nghiệp vụ cốt lõi** kế thừa bot LightVela 1 (`@br_stock_bot`) và skill `vn-stock-market-research`:

1. Tóm tắt phiên giao dịch từ dữ liệu có sẵn, kèm ngày/nguồn.
2. Phân tích một mã: OHLCV, RSI/MACD và vùng hỗ trợ/kháng cự khi dữ liệu cho phép.
3. Khối ngoại và tự doanh theo mã, ghi rõ cửa sổ thời gian, đơn vị, nguồn; nói rõ khi thiếu dữ liệu.
4. Trả lời bằng tiếng Việt, kết luận trước rồi tới số liệu/luận cứ, luôn kèm disclaimer: thông tin tham khảo, không phải khuyến nghị đầu tư. Không bịa số liệu hoặc tuyên bố dữ liệu realtime nếu chưa xác nhận.

**Phạm vi MVP đề xuất:** web chat và một adapter Telegram dùng chung backend; bộ kỹ năng phân tích trên; streaming ở web; hội thoại ngắn theo từng người dùng/kênh; xóa/reset hội thoại; giới hạn tần suất và trạng thái lỗi rõ ràng. Zalo/WhatsApp là adapter theo giai đoạn, chỉ bật sau khi có tài khoản doanh nghiệp/API chính thức, quyền duyệt ứng dụng và webhook production.

**Ngoài phạm vi:** đặt lệnh/giao dịch; tự nhận là môi giới hay tư vấn tài chính; lưu đồng bộ lịch sử lâu dài; fine-tune riêng cho từng kênh; logic hoặc model độc lập theo từng bot; tích hợp Pocket Personal. Cần duyệt riêng trước khi mở rộng.

## 2. Kiến trúc đa kênh, đa model

```text
Web: chat.aistockvn.com (hostname đề xuất; chờ chốt) ─┐
Telegram Bot API ──────────────────────────────────────┤
Zalo Official Account API / webhook ──────────────────┼─> Adapter kênh P4
WhatsApp Business Platform / Cloud API ───────────────┘      │
                                                              v
                         Chuẩn hóa định danh + conversation + policy + skill
                                                              │
                                                              v
                 P3 Cloudflare Worker gateway /v1/chat/completions
                    auth, rate limit, logging, failover, routing
                                                              │
                                                              v
                              LiteLLM Proxy: alias/model registry
                                  ├─ Model chính: Qwen2.5-14B-Instruct + LoRA P2
                                  ├─ Dự phòng/lựa chọn: Ember, Gemini, DeepSeek/GLM…
                                  └─ Các upstream được duyệt khác
```

### Các kênh và điều kiện kết nối

- **Web:** file giao diện tĩnh host trên Cloudflare Pages; trình duyệt gửi HTTPS/SSE qua gateway P3. Tên miền thuộc `aistockvn.com`, đề xuất `chat.aistockvn.com`; Henrry chốt hostname con và tài khoản Cloudflare/zone trước khi tạo DNS/TLS.
- **Telegram:** dùng Telegram Bot API làm adapter. Mỗi `chat_id` được ánh xạ thành danh tính theo namespace `telegram:<bot-id>:<chat_id>`; không coi username hiển thị là định danh ổn định. Token bot chỉ lưu phía server/secret store, không đưa vào client.
- **Zalo:** chỉ tích hợp qua Zalo Official Account và API/webhook chính thức. Cần OA, quyền/duyệt ứng dụng và credential do chủ tài khoản quản lý; điều kiện sử dụng, hạn mức và loại tin nhắn phải được xác minh trước triển khai. Định danh theo ID người dùng do Zalo cấp, namespace riêng `zalo:<oa-id>:<user-id>`.
- **WhatsApp:** chỉ tích hợp WhatsApp Business Platform/Cloud API chính thức. Cần tài khoản doanh nghiệp Meta, business/app/phone number phù hợp, quyền truy cập và webhook được Meta phê duyệt/cấu hình; có thể có yêu cầu template/cửa sổ hội thoại và chi phí theo chính sách hiện hành. Định danh theo WhatsApp ID/phone ID do nền tảng cấp, namespace `whatsapp:<phone-number-id>:<wa-id>`. Không dùng giả lập WhatsApp Web hoặc tự động hóa trái API chính thức.
- **Cô lập định danh:** mặc định mỗi nền tảng và bot/OA/phone number là namespace riêng. Không tự ghép web, Telegram, Zalo, WhatsApp thành cùng một người. Nếu cần liên kết tài khoản đa kênh, phải có luồng xác nhận/chấp thuận rõ ràng và thiết kế quyền riêng tư riêng.
- **Chuẩn hóa hội thoại:** adapter chuyển tin nhắn thành cấu trúc nội bộ chung gồm channel, channel_user_id, conversation_id, nội dung, locale, thời điểm và metadata được cho phép; cùng pipeline áp dụng giới hạn, system policy, skill `vn-stock-market-research`, lịch sử ngắn hạn và disclaimer. Chỉ trả kết quả về đúng kênh nguồn.

### Định tuyến và chuyển model (“nhiều não”)

- **Model chính:** alias production mặc định trỏ Qwen2.5-14B-Instruct + adapter LoRA P2 cuối đã đánh giá/phê duyệt. Trước khi P2 xong, dùng base Qwen2.5-14B-Instruct qua cùng alias.
- **Model bổ sung:** đăng ký model được duyệt qua gateway/LiteLLM, ví dụ Ember, Gemini, DeepSeek/GLM. Khả năng sử dụng, tên model, dữ liệu gửi đi, chi phí và quyền riêng tư cần kiểm chứng trước khi bật; ví dụ không đồng nghĩa đã cấu hình hoặc được duyệt.
- **Cách chọn:** mặc định theo tác vụ bằng policy server-side (ví dụ skill phân tích chứng khoán dùng model chính; dự phòng chỉ dùng model đã qua cùng bộ kiểm tra). Web có thể cho người dùng chọn trong danh sách model đã được duyệt. Telegram/Zalo/WhatsApp dùng mặc định theo policy; chỉ thêm lệnh chọn model nếu nền tảng UX, quyền truy cập và kiểm soát chi phí phù hợp. Kênh không được tự đặt endpoint hay bỏ qua gateway.
- **Fallback:** P3/LiteLLM thử model chính; chỉ khi lỗi hạ tầng có thể phục hồi (timeout, unavailable, 5xx) mới chuyển sang model dự phòng theo thứ tự cấu hình. Không âm thầm fallback khi model trả 4xx do prompt/quyền hoặc khi câu trả lời chất lượng thấp; ghi nhận model thực tế dùng và báo người dùng khi đổi model ảnh hưởng kết quả. Chặn vòng lặp, giới hạn retry/thời gian và không dispatch model ngoài allowlist.
- **Nhất quán chất lượng:** dùng cùng system policy, skill, cấu trúc kết luận-trước, quy tắc OHLCV/RSI/MACD/hỗ trợ-kháng cự, cửa sổ khối ngoại/tự doanh và disclaimer cho mọi model/kênh. Thêm bộ acceptance test cố định, đánh giá từng model trên cùng tập ca; hiển thị nguồn/ngày và đánh dấu dữ liệu thiếu. Không giả định các model tương đương chỉ vì cùng API.
- **Bảo mật:** trình duyệt và adapter kênh chỉ gọi P3; không để lộ LiteLLM master key/provider key. Secret Telegram/Zalo/Meta lưu phía server theo từng adapter. P3/LiteLLM là nơi duy nhất áp dụng auth, rate limit, allowlist model, routing và audit metadata tối thiểu.

## 3. Tính năng chính

1. Web chat tiếng Việt qua `aistockvn.com` hostname đã duyệt; stream câu trả lời, gửi/dừng, retry có giới hạn, xóa hội thoại.
2. Bot Telegram qua cùng backend; trả lời cùng skill/model policy, cùng format với web.
3. Adapter Zalo OA và WhatsApp Business API theo giai đoạn, chỉ hoạt động khi đủ quyền/tài khoản/API chính thức và vượt kiểm chứng webhook.
4. Các tác vụ: tóm tắt phiên; phân tích một mã (OHLCV, RSI/MACD, hỗ trợ/kháng cự); khối ngoại/tự doanh theo mã.
5. Định danh theo channel namespace; hội thoại/short context tách biệt mặc định, có chính sách reset/retention rõ ràng.
6. Chọn model theo policy/tác vụ; web cho chọn model nếu được duyệt; fallback minh bạch trong nhóm model allowlist khi lỗi hạ tầng.
7. Kết luận tiếng Việt trước, số liệu và luận cứ sau, nguồn/ngày dữ liệu cùng disclaimer; báo rõ khi thiếu/cũ hoặc đổi model.
8. Không đặt lệnh, không thu thập thông tin đăng nhập, không lưu prompt vào analytics/server lâu dài nếu chưa được duyệt.

## 4. Công nghệ và lý do

- **TypeScript + React + Vite:** web client tĩnh, kiểu dữ liệu hỗ trợ API/SSE, build nhanh, host Pages.
- **Cloudflare Pages:** phân phối giao diện web tĩnh; không dùng Pages để chứa secret hoặc xử lý model riêng. Custom domain thuộc `aistockvn.com` sẽ gắn sau khi chốt hostname/zone.
- **Adapters server-side:** webhook handlers riêng cho Telegram Bot API, Zalo OA API và WhatsApp Business Cloud API; cùng chuẩn hóa event rồi gọi chung backend P4/P3. Tách module theo nền tảng để giới hạn lỗi nhưng không nhân bản logic nghiệp vụ.
- **P3 Worker + LiteLLM:** điểm vào thống nhất `/v1/chat/completions`, xác thực, rate limit, model aliases, routing/fallback và upstreams; key nhà cung cấp chỉ phía server.
- **OpenAI-compatible API/SSE:** chuẩn giao tiếp chung để đổi nhiều model mà không thay UI; chuẩn hóa lỗi/stream ở một lớp adapter chung.
- **Lưu trữ MVP tối thiểu:** web giữ lịch sử trong browser; bot chỉ giữ short context tối thiểu theo namespace trong thời gian đã duyệt. Không thêm đồng bộ đa kênh hoặc database dài hạn khi chưa có quyết định quyền riêng tư.

## 5. Lộ trình M0–M7 và kiểm chứng

| Mốc | Công việc | Điều kiện hoàn tất |
|---|---|---|
| M0 — chốt sản phẩm/kênh/model | Duyệt web + Telegram MVP, Zalo/WhatsApp theo điều kiện; hostname `aistockvn.com`; model chính Qwen2.5-14B + LoRA sau P2; danh sách model dự phòng; chính sách định danh, retention và fallback. | Henrry chốt phạm vi, hostname con, repo/tài khoản, auth P3 và quyết định Zalo/WhatsApp có làm ngay hay phase sau. |
| M1 — hợp đồng chung | Định nghĩa schema event nội bộ, namespace user/conversation, format kết luận-trước, dữ liệu/nguồn/ngày, lỗi, SSE và policy model. | Contract test chứng minh mọi adapter tạo cùng payload chuẩn, không tự ghép danh tính giữa kênh. |
| M2 — Web + P3 | Xây UI React/Vite, stream qua `/v1/chat/completions`, deploy preview Pages, test tên miền khi được cấp. | Test chat, stop/retry, bảo mật bundle, không có master/provider key. |
| M3 — Telegram adapter | Webhook/Bot API server-side, xác minh webhook/update, chuẩn hóa ID và gọi backend chung. | Ca hỏi đáp/tóm tắt/phân tích chạy qua cùng skill/model policy; user namespace đúng. |
| M4 — năng lực nghiên cứu | Tích hợp luồng `vn-stock-market-research`: tóm tắt phiên, phân tích mã, chỉ báo/vùng giá, khối ngoại/tự doanh, kết luận trước/disclaimer. | Bộ test nghiệp vụ cố định; thiếu dữ liệu được báo rõ, không bịa; nội dung nhất quán web/Telegram. |
| M5 — đa model và fallback | Cấu hình alias Qwen base/P2; thêm model bổ sung sau duyệt; policy chọn theo tác vụ, model picker web (nếu duyệt), fallback có giới hạn. | Test cùng prompt trên allowlist, log model thực tế, fallback chỉ cho lỗi hạ tầng và chất lượng đạt ngưỡng đã chốt. |
| M6 — Zalo/WhatsApp | Đăng ký/cấu hình OA/API chính thức, webhook, xác thực, template/quyền và chi phí; xây adapters theo namespace riêng. | Chỉ mở kênh nào đã có quyền chính thức; webhook/signature, định danh, hạn mức và ca nghiệp vụ được kiểm thử. |
| M7 — adapter P2 và phát hành | Đánh giá/pin LoRA cuối; canary alias chính; deploy Pages production, gắn domain; bật từng kênh theo phê duyệt. | Health/chất lượng/độ trễ/fallback/rollback đạt; HTTPS/domain và từng kênh được owner nghiệm thu. |

**Tiêu chí chất lượng chung:** cùng tập ca kiểm thử qua các kênh và model; kết luận tiếng Việt ở đầu, số liệu có nguồn/ngày/đơn vị, disclaimer luôn có; thiếu dữ liệu không bịa; identity không rò/ghép giữa kênh; fallback có thông báo; không lộ khóa đặc quyền. Chốt ngưỡng chất lượng, độ trễ và chi phí trước M5.

## Các câu hỏi cần Henrry duyệt

1. Xác nhận web + Telegram là MVP; Zalo/WhatsApp đưa vào MVP hay phase sau khi hoàn tất điều kiện Official Account/Business API?
2. Chốt hostname con của `aistockvn.com` (đề xuất `chat.aistockvn.com`) và tài khoản Cloudflare/Pages/DNS.
3. Model chính là alias Qwen2.5-14B base tạm, sau đó LoRA P2 cuối; model bổ sung nào (Ember, Gemini, DeepSeek/GLM…) được phép, theo tác vụ nào và có cho web user chọn không?
4. Thứ tự/điều kiện fallback, giới hạn chi phí/timeout và cách thông báo người dùng khi đổi model?
5. Zalo OA/WhatsApp Business account, app review, số điện thoại/template, người sở hữu credential và chi phí được duyệt ra sao?
6. Định danh giữa kênh có giữ tách biệt hoàn toàn (mặc định đề xuất) hay cần liên kết tài khoản có consent? Retention short context của bot là bao lâu?
7. Nguồn/ngày dữ liệu và tiêu chí nghiệm thu cho tóm tắt phiên, OHLCV/RSI/MACD/hỗ trợ-kháng cự, khối ngoại/tự doanh là gì? Ai duyệt bộ test và chuyển LoRA production?
