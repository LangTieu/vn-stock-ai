# Bản thảo P4 — Client độc lập cho trợ lý VN Stock AI

**Trạng thái:** Bản đề xuất để Henrry xem và góp ý. Thay đổi này chưa triển khai mã P4 và chưa deploy.

## 1. P4 là gì, phạm vi đến đâu?

P4 là ứng dụng web chatbot/AI Agent để người dùng truy cập qua tên miền **`aistockvn.com`**; tên miền con cụ thể sẽ được Henrry chốt sau. P4 không phải bot Telegram. Đây là sản phẩm **độc lập với Pocket Personal**: giao diện, cấu hình, triển khai, thông tin xác thực và phạm vi sản phẩm riêng. P4 gọi P3 qua API; không chứa trọng số model và không gọi trực tiếp nhà cung cấp model từ trình duyệt.

**Phạm vi MVP đề xuất:** giao diện web/chat tiếng Việt, phản hồi dạng stream, trạng thái model/phản hồi rõ ràng, xóa hội thoại và lịch sử chỉ lưu trong trình duyệt. Năng lực phân tích lấy theo bot LightVela 1 (`@br_stock_bot`) và skill `vn-stock-market-research`, không phụ thuộc Telegram: (a) tóm tắt phiên; (b) phân tích một mã từ OHLCV, RSI/MACD và vùng hỗ trợ/kháng cự; (c) khối ngoại và tự doanh theo mã. Câu trả lời bằng tiếng Việt, đưa kết luận lên trước rồi mới đến số liệu/luận cứ và luôn có disclaimer. Giao diện phải nói rõ nội dung chỉ để tham khảo, dữ liệu có thể thiếu/cũ và không phải khuyến nghị đầu tư. MVP không đặt lệnh, không tự nhận là môi giới/tư vấn tài chính, không thu thập thông tin đăng nhập hay dữ liệu cá nhân nhạy cảm.

**Ngoài phạm vi MVP:** giao dịch/đặt lệnh; tài khoản người dùng và đồng bộ hội thoại lên cloud; fine-tune riêng; nền tảng truy xuất dữ liệu mới; tích hợp Pocket Personal. Chỉ xem xét sau khi có phê duyệt riêng và thiết kế bảo mật/quyền riêng tư.

## 2. Kiến trúc và chuyển model

```text
Người dùng → https://aistockvn.com (hostname/tên miền con sẽ chốt sau)
   └─ Ứng dụng web P4 (không phải Telegram bot)
       └─ HTTPS POST /v1/chat/completions (khóa client; stream SSE)
           └─ P3 Cloudflare Worker gateway (xác thực, giới hạn tần suất, log, failover)
               └─ LiteLLM Proxy / upstream
                   └─ Qwen2.5-14B-Instruct base → adapter LoRA P2 cuối cùng
```

- P4 dùng URL gateway P3 hiện có và API chat-completions tương thích OpenAI. Xác nhận URL production và cơ chế cấp khóa client được phép trước khi triển khai. Tuyệt đối không nhúng master key LiteLLM hay khóa nhà cung cấp vào mã trình duyệt.
- Trong lúc P2 còn train, cấu hình một alias model tạm trong LiteLLM (ví dụ `vn-stock-assistant`) trỏ đến Qwen2.5-14B-Instruct base đã được duyệt. Client chỉ gửi alias, không phụ thuộc endpoint riêng của nhà cung cấp.
- Khi P2 hoàn tất và adapter cuối đã được đánh giá/phê duyệt, cập nhật cấu hình model phía LiteLLM để alias đó dùng Qwen2.5-14B base cùng LoRA adapter. Giữ nguyên alias để không cần build lại client. Nếu kiểm tra health/chất lượng bị giảm, chuyển alias về cấu hình base.
- Checkpoint P2 chỉ phục vụ khôi phục train, không tự động trở thành model production. Chỉ promote adapter cuối đã đánh giá; pin revision/artifact và ghi nhận revision của base model.
- Giữ streaming SSE xuyên suốt LiteLLM → Worker → trình duyệt. UI cần xử lý event từng phần, `[DONE]`, lỗi upstream, timeout và thao tác người dùng dừng phản hồi.

## 3. Tính năng chính

1. **Chat:** nhập prompt tiếng Việt, gửi/dừng, xem câu trả lời streaming, thử lại sau lỗi mạng có thể phục hồi và xóa hội thoại.
2. **Năng lực phân tích theo bot LightVela 1 (`@br_stock_bot`) / skill `vn-stock-market-research`:** (a) tóm tắt phiên; (b) phân tích một mã với OHLCV, RSI/MACD và vùng hỗ trợ/kháng cự; (c) khối ngoại và tự doanh theo mã. Đây là năng lực của web P4, không phải tích hợp Telegram.
3. **Cách trình bày phân tích:** trả lời tiếng Việt; kết luận đặt trước, tiếp theo là số liệu và luận cứ; ghi rõ ngày/nguồn và trường dữ liệu thiếu/cũ; luôn có disclaimer rằng nội dung tham khảo, không phải khuyến nghị đầu tư. Không bịa dữ liệu hoặc khuyến nghị khi đầu vào thiếu.
4. **Ngữ cảnh phân tích:** trường tùy chọn cho mã chứng khoán/thông tin đầu vào và phần tóm tắt ngữ cảnh gọn gửi cùng prompt. Hiển thị mã và ngày/nguồn dữ liệu để người dùng nhận ra dữ liệu cũ hoặc nhầm mã. Không tự bịa dữ liệu cơ bản còn thiếu.
5. **Chế độ tác vụ:** một số mẫu prompt rõ ràng (hỏi đáp chung, tóm tắt phiên, phân tích một mã); luôn cho biết chế độ đang dùng. Hướng dẫn hệ thống và quy tắc an toàn do server/gateway kiểm soát.
6. **Minh bạch và quyền riêng tư:** hiển thị alias model, trạng thái đang trả lời/lỗi và mức độ không chắc chắn. MVP chỉ lưu lịch sử trong bộ nhớ trình duyệt và cho phép xóa; không thêm lưu trữ server/analytics chứa prompt nếu chưa review riêng. Không log API key ở client, không lộ master key gateway.
7. **Responsive và accessibility:** dùng được bằng bàn phím, quản lý focus, trạng thái streaming dễ đọc, hiển thị phù hợp mobile và desktop.

## 4. Công nghệ đề xuất và lý do

- **TypeScript + React + Vite:** phù hợp SPA/PWA nhỏ; kiểu dữ liệu hỗ trợ xử lý API/SSE; phát triển nhanh, không cần server riêng chạy thường trực cho client.
- **Cloudflare Pages** cho client P4 tĩnh, cô lập trong repo/project/tài khoản P4 riêng với Pocket Personal; không dùng lại secret hay database của Pocket Personal.
- **P3 Worker gateway** là đường duy nhất từ client tới model. Ưu tiên khóa client riêng với quyền tối thiểu nếu P3 hỗ trợ; nếu không, phải thiết kế xác thực/giới hạn truy cập an toàn trước khi public. Website tĩnh không thể giữ bí mật dùng chung trong JavaScript.
- **SSE tương thích OpenAI** thay vì SDK riêng của nhà cung cấp để frontend độc lập với backend phục vụ model và việc rollout LoRA.
- **Không có database client trong MVP:** lưu lịch sử cục bộ giúp tránh thêm dịch vụ dữ liệu P4 và đơn giản hóa việc xóa. Đồng bộ server chỉ xem xét sau khi có phê duyệt riêng.

### Địa chỉ truy cập và gắn tên miền

**Henrry đã chốt domain gốc truy cập là `aistockvn.com`; hostname con của web P4 vẫn để mở và sẽ chốt sau** (ví dụ `chat.aistockvn.com` hoặc `app.aistockvn.com`). P4 là web app, không phải bot Telegram. Gateway P3 tiếp tục dùng hostname API riêng; không đặt client và API cùng một hostname/path trong MVP.

Các bước dự kiến khi được duyệt:
1. Tạo project Cloudflare Pages cho repo P4 riêng; cấu hình build command/output directory sau khi chốt framework.
2. Trong Cloudflare Pages → project → **Custom domains**, thêm hostname con đã được Henrry chốt, ví dụ `chat.aistockvn.com`.
3. Vì Henrry đã có `aistockvn.com`, xác nhận zone đang được quản lý trong Cloudflare tương ứng; Pages sẽ yêu cầu/tạo DNS record liên kết hostname với Pages. Kiểm tra record do Pages hướng dẫn, không tự đổi record apex hay các dịch vụ khác.
4. Đợi trạng thái domain active và TLS certificate sẵn sàng; kiểm tra HTTPS, redirect HTTP→HTTPS, tải trang và gọi P3 từ domain mới.
5. Chỉ cấu hình URL công khai và thông tin không bí mật ở Pages. Không đưa token HF, khóa LiteLLM master hay khóa upstream vào biến client/build công khai. Nếu cần bí mật phía server, phải qua Worker/backend có xác thực.

Đây là đề xuất, chưa kiểm tra quyền sở hữu/zone hoặc tạo DNS record. Cần Henrry chốt hostname con và xác nhận tài khoản Cloudflare quản lý zone trước khi cấu hình thật; hiện chưa tạo DNS record hay cấu hình Pages domain.

## 5. Các bước triển khai và mốc kiểm chứng

| Mốc | Công việc | Bằng chứng hoàn tất |
|---|---|---|
| M0 — chốt quyết định | Duyệt ranh giới sản phẩm, người dùng mục tiêu, URL/auth gateway, repo/tài khoản hosting, yêu cầu độ mới dữ liệu, chính sách lưu lịch sử và hostname con dưới `aistockvn.com`. | Henrry duyệt bản thảo hoặc ghi rõ các điểm cần đổi. |
| M1 — hợp đồng API | Ghi request/response/SSE, alias model được phép, giới hạn tần suất, timeout/lỗi và xác thực an toàn. | Request thử không chứa secret production gọi qua P3 thành công; hiểu rõ 401/429/5xx. |
| M2 — prototype UI | Dựng khung chat và chế độ/ngữ cảnh với stream giả lập. | Duyệt mobile/desktop; thao tác bàn phím, dừng và xóa hoạt động. |
| M3 — tích hợp gateway | Kết nối P3 Worker route public; đọc SSE tăng dần; xử lý loading, cancel, retry, lỗi. | E2E smoke với test key không phải production; kiểm tra bundle và browser log không có master/provider key. |
| M4 — an toàn/quyền riêng tư | Thêm disclaimer, xử lý dữ liệu cũ/thiếu, xóa lịch sử cục bộ, review nội dung/logging. | Xác nhận không đặt lệnh, không lưu ngầm, thể hiện độ không chắc chắn. |
| M5 — pilot model base | Dùng Qwen2.5-14B base đã duyệt phía sau alias LiteLLM trong khi chờ P2. | Đánh giá chức năng/độ trễ/lỗi trên bộ test nhỏ được duyệt; kiểm tra fallback. |
| M6 — promote adapter | Đánh giá adapter P2 cuối offline; pin artifact/revision; đổi alias server-side, canary và rollback nếu cần. | Đánh giá được duyệt; health, chất lượng, độ trễ và rollback đạt. |
| M7 — phát hành giới hạn | Deploy client tĩnh riêng lên Pages và hostname đã duyệt; theo dõi health/rate limit mà không lưu prompt. | Checklist phát hành và owner duyệt; có phương án rollback/hỗ trợ. |

**Kiểm tra pilot gợi ý:** chat và kết thúc stream đúng; lỗi gateway hiển thị và phục hồi được; đổi alias model không cần sửa client; bundle không có khóa đặc quyền; xóa được hội thoại; không bịa dữ liệu trực tiếp. Chốt ngưỡng độ trễ/chất lượng định lượng với Henrry trước M5.

## Các điểm cần Henrry duyệt

1. MVP có đúng là web/PWA độc lập không, và repo/tài khoản riêng nào sẽ sở hữu P4?
2. Domain truy cập là `aistockvn.com`; Henrry sẽ chọn hostname con nào cho P4 (ví dụ `chat` hay `app`)? Zone `aistockvn.com` thuộc tài khoản Cloudflare nào và ai sẽ cấp quyền thêm Custom Domain/DNS?
3. P4 dùng URL P3 và cơ chế xác thực client an toàn nào? Không phát hành master key dùng chung trong JavaScript tĩnh.
4. Chấp nhận lịch sử chỉ ở browser không, và có cho phép gửi prompt vào analytics/log không?
5. Chế độ phân tích cần hiển thị nguồn/ngữ cảnh dữ liệu nào, yêu cầu độ mới/chất lượng ra sao?
6. Ai duyệt đánh giá adapter cuối và lần chuyển alias production?
