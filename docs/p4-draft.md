# Bản thảo P4 — Ứng dụng web chat AI VN Stock

**Trạng thái:** Bản thảo theo các quyết định hiện tại để Henrry duyệt. Chưa triển khai mã P4, chưa tạo Pages project và chưa cấu hình DNS.

## 1. P4 là gì và phạm vi sản phẩm

P4 là ứng dụng chat AI trên web, phục vụ hỏi đáp và phân tích thị trường/chứng khoán Việt Nam. Người dùng truy cập qua tên miền thuộc **`aistockvn.com`**; đề xuất hostname là **`chat.aistockvn.com`**, chờ Henrry chốt. P4 **không phải bot Telegram**. P4 cũng độc lập với Pocket Personal: repo, giao diện, cấu hình, triển khai, thông tin xác thực và dữ liệu riêng; không tích hợp hoặc dùng lại dịch vụ/secret/database của Pocket Personal.

P4 được host như một **web tĩnh trên Cloudflare Pages**. “Tĩnh” chỉ nói về cách phân phối file giao diện; khi chat, trình duyệt vẫn gọi trực tiếp qua HTTPS tới API gateway P3 để nhận câu trả lời AI dạng stream. P4 không chứa trọng số model, không chạy model trong trình duyệt và không gọi nhà cung cấp model trực tiếp.

### Phạm vi chức năng MVP

P4 cần có đủ nhóm khả năng phân tích của bot LightVela 1 (`@br_stock_bot`), dựa trên skill **`vn-stock-market-research`**, nhưng thể hiện bằng giao diện web:

1. **Tóm tắt phiên:** tóm tắt diễn biến phiên giao dịch từ dữ liệu sẵn có; nêu rõ ngày/nguồn dữ liệu và điểm đáng chú ý.
2. **Phân tích một mã:** người dùng nhập mã; trình bày dữ liệu OHLCV, RSI/MACD và các vùng hỗ trợ/kháng cự khi dữ liệu cho phép. Phân biệt dữ liệu quan sát được với diễn giải; không bịa trường bị thiếu.
3. **Dòng tiền theo mã:** trình bày khối ngoại và tự doanh theo mã, ghi rõ cửa sổ thời gian/đơn vị/nguồn; báo “không có số liệu” nếu nguồn không cung cấp.
4. **Cách trả lời:** tiếng Việt; kết luận ngắn đặt trước, sau đó là số liệu và luận cứ; luôn kèm disclaimer rằng đây là thông tin tham khảo, không phải khuyến nghị đầu tư. Nếu dữ liệu thiếu, cũ hoặc không đủ căn cứ thì nói rõ.
5. **Chat tương tác:** gửi/dừng câu hỏi, nhận stream, hiển thị lỗi có thể thử lại, xóa hội thoại; lịch sử MVP chỉ lưu cục bộ trong trình duyệt và người dùng tự xóa được.

**Ngoài phạm vi MVP:** Telegram bot, đặt lệnh/giao dịch, tự nhận là môi giới hay tư vấn tài chính, tài khoản và đồng bộ lịch sử lên server, fine-tune riêng, hoặc xây nền tảng dữ liệu/retrieval mới. Các phần này cần phê duyệt và thiết kế riêng.

## 2. Kiến trúc và chuyển model

```text
Người dùng
   └─ https://chat.aistockvn.com (đề xuất; tên miền con chờ chốt)
       └─ Web tĩnh P4 trên Cloudflare Pages
           └─ HTTPS /v1/chat/completions (SSE stream)
               └─ P3 Cloudflare Worker gateway
                   └─ LiteLLM Proxy / upstream
                       └─ Qwen2.5-14B-Instruct base + adapter LoRA P2 khi được duyệt
```

- **Giao diện → gateway:** ứng dụng gửi request OpenAI-compatible tới P3 `/v1/chat/completions`, nhận phản hồi SSE. Không gọi LiteLLM hoặc nhà cung cấp trực tiếp từ browser.
- **Bảo mật:** không nhúng master key LiteLLM, HF token hay provider key vào JavaScript/build tĩnh. Xác nhận URL P3 và phương án khóa client an toàn/ít quyền trước khi public; static client không thể giữ bí mật dùng chung. Gateway tiếp tục chịu trách nhiệm xác thực, rate limit, logging phù hợp và failover.
- **Trong khi P2 đang train:** dùng alias model tạm (ví dụ `vn-stock-assistant`) trỏ tới Qwen2.5-14B-Instruct base đã được duyệt. Client chỉ biết alias, không phụ thuộc model/backend cụ thể.
- **Sau khi P2 hoàn tất:** đánh giá và phê duyệt adapter cuối; pin revision/artifact, sau đó đổi cấu hình phía LiteLLM để alias dùng base Qwen2.5-14B cùng LoRA adapter. Nếu health/chất lượng giảm, rollback alias về base. Không cần build lại client khi đổi model.
- Checkpoint giữa chừng chỉ dùng để khôi phục train, không tự động được promote production. Chỉ adapter cuối đã đánh giá mới được xem xét đưa vào serving.
- Frontend xử lý stream từng phần, `[DONE]`, lỗi upstream, timeout, cancel, retry có giới hạn và thông báo rõ khi P3 không có dữ liệu nền. Không khẳng định dữ liệu thị trường là realtime nếu chưa xác nhận.

## 3. Giao diện và trải nghiệm chính

- Trang chat tiếng Việt, responsive cho điện thoại và desktop; bố cục rõ giữa input, câu trả lời, số liệu và nguồn/ngày dữ liệu.
- Chọn tác vụ: hỏi đáp chung, tóm tắt phiên hoặc phân tích một mã; khi chọn phân tích mã, nhập ticker và ngữ cảnh tùy chọn.
- Phân tích một mã hiển thị OHLCV, RSI/MACD, hỗ trợ/kháng cự, khối ngoại và tự doanh theo cửa sổ thời gian có dữ liệu. Kết luận đặt đầu; số liệu và giải thích theo sau.
- Trạng thái đang trả lời/dừng/lỗi, có thể thử lại; nút xóa hội thoại và lịch sử cục bộ.
- Luôn có disclaimer và thông tin thiếu/cũ. Không tự tạo số liệu BCTC, dòng tiền hay giá; không đưa khuyến nghị mua/bán cá nhân hóa.
- Accessibility: thao tác bàn phím, focus hợp lý, thông báo trạng thái stream có thể nhận biết.

## 4. Công nghệ và phương án host

- **TypeScript + React + Vite:** phù hợp ứng dụng SPA/PWA nhỏ, kiểu dữ liệu hữu ích khi xử lý API và SSE, build ra file tĩnh, không cần server client chạy thường trực.
- **Cloudflare Pages:** host file tĩnh P4 trong project/repo riêng; triển khai preview trước, production sau khi có duyệt. Không dùng lại secret/database Pocket Personal.
- **Cloudflare DNS/Custom Domain:** đề xuất `chat.aistockvn.com`, chờ Henrry xác nhận. Thêm hostname qua Cloudflare Pages → project → Custom domains; kiểm tra zone `aistockvn.com` thuộc đúng tài khoản, chỉ tạo/chỉnh record Pages hướng dẫn cho hostname con, không sửa apex hay record dịch vụ khác. Chờ TLS active, kiểm HTTPS và gọi P3 end-to-end.
- **P3 Worker + LiteLLM:** giữ làm cổng duy nhất tới model; alias server-side cho phép thay base bằng adapter mà không đổi client.
- **SSE tương thích OpenAI:** tránh khóa chặt frontend vào SDK của một hãng/model.
- **Không có database P4 trong MVP:** lịch sử cục bộ giảm dữ liệu nhạy cảm và đơn giản hóa việc xóa. Chỉ thêm đồng bộ server sau khi có duyệt, chính sách lưu giữ và threat review.

## 5. Lộ trình và mốc kiểm chứng

| Mốc | Công việc | Điều kiện hoàn tất |
|---|---|---|
| M0 — duyệt phạm vi | Chốt web P4 độc lập Pocket Personal, bộ năng lực theo `vn-stock-market-research`, repo/project riêng, hostname con dưới `aistockvn.com`, URL/auth P3, dữ liệu và chính sách lịch sử. | Henrry duyệt bản thảo/ghi rõ thay đổi; không đụng DNS trước khi chốt hostname và quyền zone. |
| M1 — hợp đồng API | Đặc tả request/response/SSE, alias, rate limit, timeout/lỗi, xác thực client an toàn. | Test không dùng secret production gọi qua P3 thành công; hiểu rõ 401/429/5xx. |
| M2 — prototype | Dựng chat web với phản hồi stream giả lập, selector tác vụ, nhập ticker và bố cục số liệu. | Henrry duyệt UI desktop/mobile; keyboard, stop, retry, clear hoạt động. |
| M3 — tích hợp P3 | Gọi `/v1/chat/completions` từ client qua P3; đọc SSE tăng dần; xử lý lỗi/cancel. | E2E với test key; chứng minh không có master/provider key trong bundle hay browser logs. |
| M4 — hoàn thiện phân tích/an toàn | Ánh xạ đầu ra skill sang phần tóm tắt phiên, OHLCV/RSI/MACD/hỗ trợ-kháng cự, khối ngoại/tự doanh; kết luận trước, nguồn/ngày và dữ liệu thiếu; disclaimer. | Bộ test nghiệp vụ được duyệt; không bịa số khi thiếu; không đặt lệnh; kiểm tra quyền riêng tư/lịch sử local. |
| M5 — pilot base | Cho alias LiteLLM dùng Qwen2.5-14B base trong lúc P2 chưa xong. | Pilot nhỏ đạt ngưỡng chức năng/độ trễ/chất lượng do Henrry chốt; fallback hoạt động. |
| M6 — promote adapter | Đánh giá offline adapter P2 cuối, pin revision, cập nhật alias server-side, canary và rollback. | Đánh giá adapter được duyệt; health/chất lượng/độ trễ và rollback đạt. |
| M7 — Pages/domain và phát hành giới hạn | Deploy Pages preview; gắn hostname con đã chốt; xác minh DNS/TLS/HTTPS; phát hành sau duyệt. | P4 mở được qua `aistockvn.com` hostname đã chọn; chat P3 end-to-end; checklist và rollback được owner duyệt. |

**Tiêu chí pilot gợi ý:** trả lời và kết thúc SSE đúng; lỗi gateway hiển thị/phục hồi; đổi alias không cần sửa client; không lộ khóa đặc quyền; xóa được lịch sử; các nhóm phân tích có ngày/nguồn; không bịa dữ liệu; disclaimer hiện rõ. Chốt ngưỡng độ trễ/chất lượng định lượng trước M5.

## Các câu hỏi cần duyệt trước khi code

1. Xác nhận hostname con dưới `aistockvn.com` (đề xuất `chat.aistockvn.com`) và tài khoản Cloudflare có quyền Pages/DNS.
2. Repo/project Cloudflare Pages riêng nào sẽ sở hữu P4, tách biệt Pocket Personal?
3. P3 URL production và cơ chế xác thực client ít quyền nào được phép? Không phát hành master key trong client tĩnh.
4. Xác nhận các chức năng phân tích cần giống bot LightVela 1: tóm tắt phiên; OHLCV, RSI/MACD, hỗ trợ/kháng cự; khối ngoại/tự doanh; kết luận tiếng Việt trước và disclaimer. Nguồn/ngày dữ liệu và mức tươi tối thiểu nào cần hiển thị?
5. Chấp nhận lịch sử chỉ lưu trong browser không? Có cho phép gửi prompt vào analytics/log không?
6. Ai duyệt bộ test nghiệp vụ, đánh giá adapter P2 cuối và chuyển alias production?
