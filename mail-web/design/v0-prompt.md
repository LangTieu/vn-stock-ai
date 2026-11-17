# Prompt thiết kế v0 — Web mail aistockvn.com

Dán nguyên văn vào v0 (hoặc chạy `node design/v0_generate.mjs` trên máy có file key v0).

---

Thiết kế một ứng dụng web mail **ưu tiên điện thoại** (viewport 390×844, vẫn đẹp trên desktop với cột giữa tối đa ~768px), toàn bộ giao diện **tiếng Việt**, phong cách gần Gmail trên Android nhưng gọn hơn. Màu chủ đạo teal-700 (#0f766e), nền slate-50, chữ slate-900. Dùng React + Tailwind CSS (không cần Next.js routing; điều hướng bằng hash `#/inbox`, `#/sent`, `#/m/:id`, `#/compose`). Không dùng dữ liệu giả trong bản cuối: mọi màn hình nhận dữ liệu qua props/hàm API, có trạng thái đang tải, rỗng và lỗi.

Hộp thư: admin@aistockvn.com (chỉ một người dùng).

Màn hình:
1. **Đăng nhập** — nền gradient teal, thẻ trắng bo góc, logo phong bì, tiêu đề "Thư AI Stock VN", dòng địa chỉ hộp thư, nút "Đăng nhập bằng Google" (chỗ trống để render nút Google Identity Services), dòng thông báo lỗi.
2. **Hộp thư đến / Đã gửi** — thanh trên teal: tiêu đề, nút tìm kiếm (mở ô tìm kiếm toàn chiều rộng có nút quay lại), làm mới, đăng xuất. Danh sách: avatar chữ cái đầu màu theo tên, tên người gửi (Đã gửi: "Tới: …"), giờ/ngày rút gọn ("14:05", "17 thg 11"), tiêu đề, đoạn trích 1 dòng, biểu tượng ghim nếu có tệp; thư chưa đọc in đậm, giờ màu teal. Nút nổi "Soạn thư" góc phải dưới. Thanh điều hướng dưới: "Hộp thư đến" (badge số chưa đọc) và "Đã gửi". Nút "Tải thêm thư" cuối danh sách. Trạng thái rỗng có biểu tượng + lời giải thích.
3. **Đọc thư** — thanh trên trắng: quay lại, đánh dấu chưa đọc. Tiêu đề lớn, khối người gửi (avatar, tên, địa chỉ, "tới …", "cc …", ngày giờ đầy đủ), thân thư HTML trong iframe sandbox, băng thông báo "Hình ảnh từ bên ngoài đã bị ẩn… Hiển thị hình ảnh", danh sách tệp đính kèm dạng thẻ (tên, dung lượng, nút tải). Thanh hành động cố định dưới: "Trả lời", "Chuyển tiếp".
4. **Soạn / Trả lời / Chuyển tiếp** — thanh trên: nút đóng (X), tiêu đề màn hình, nút "Gửi" teal bo tròn (trạng thái "Đang gửi…", "Đã gửi"). Trường: Từ (cố định admin@aistockvn.com), Tới (bàn phím email, nút "Cc" để mở trường Cc), Tiêu đề, Nội dung (textarea cao). Hộp lỗi đỏ nhạt và hộp thành công xanh nhạt.

Yêu cầu: vùng chạm ≥ 44px, hỗ trợ safe-area iOS, không cuộn ngang, font hệ thống, tương phản AA.
