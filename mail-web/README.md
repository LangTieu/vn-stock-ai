# Web mail aistockvn.com (`mail.aistockvn.com`)

Ứng dụng web mail cho hộp thư `admin@aistockvn.com`, ưu tiên điện thoại, giao diện tiếng Việt: hộp thư đến, đọc thư (HTML an toàn, tệp đính kèm), soạn / trả lời / chuyển tiếp, thư đã gửi, tìm kiếm, đếm thư chưa đọc.

## Phương án đã chốt (17/11)

**Một Cloudflare Worker** (`aistockvn-mail`) gồm: giao diện tĩnh (React + Tailwind, Workers Static Assets), API `/api/*`, và `email()` handler.

### Hộp thư đến: chọn (a) Email Routing → Worker → R2 + D1

| Hướng | Đánh giá |
|---|---|
| **(a) Email Routing "Send to a Worker"** ✅ | Worker nhận `ForwardableEmailMessage` (envelope from/to, headers, `raw` MIME) — [Cloudflare runtime API](https://developers.cloudflare.com/email-routing/email-workers/runtime-api/). Lưu bản gốc `.eml` vào R2, siêu dữ liệu + text để tìm kiếm vào D1, rồi **`message.forward("skillshare01br@mail.com")`** nên luồng forward hiện tại vẫn giữ nguyên (đích phải là địa chỉ đã xác minh — đúng với địa chỉ đang dùng). Không cần tài khoản bên thứ ba, không đổi MX, không chờ xác minh tay. Nếu lưu lỗi vẫn forward; chỉ khi cả hai lỗi mới báo lỗi để server gửi thử lại. |
| (b) Gmail `lethanhdongus@gmail.com` + Gmail API | Phải chờ Henrry xác minh đích, tạo dự án Google Cloud + OAuth consent với scope Gmail nhạy cảm, refresh token lưu server; thư nằm lẫn trong Gmail cá nhân. Nhiều phụ thuộc hơn mà không thêm gì so với (a). Không cần nữa. |
| (c) Resend Inbound | Có thật ([docs](https://resend.com/docs/dashboard/receiving/create-receiving-webhook)) nhưng phải trỏ **MX** của domain (hoặc subdomain) sang Resend → xung đột Email Routing hiện tại; cần key full-access (key `vn-stock-ai` là sending-only); webhook chỉ có metadata, phải gọi API lấy nội dung. Loại. |

Giới hạn thật: thư cũ đã nằm ở mail.com **không nhập được** (mail.com không có API) — hộp thư web chỉ có thư nhận **từ lúc bật routing vào Worker** trở đi. Không có dữ liệu mẫu nào được tạo.

### Gửi thư: Resend API
`POST https://api.resend.com/emails` từ Worker, `from: "AI Stock VN <admin@aistockvn.com>"`, có `Idempotency-Key` chống gửi trùng; trả lời đặt `In-Reply-To`/`References` để giữ luồng hội thoại. Key nằm trong **Worker secret** `RESEND_API_KEY`, không bao giờ xuống trình duyệt. Thư gửi thành công được lưu vào mục "Đã gửi".

### Đăng nhập: Google Sign-In → cookie phiên phía server
- Trình duyệt chỉ nhận **ID token** từ Google Identity Services và gửi lên `/api/auth/google`.
- Worker tự xác minh chữ ký RS256 với JWKS của Google, kiểm `iss`, `aud` = `GOOGLE_CLIENT_ID`, `exp`, `email_verified`, và email nằm trong `ALLOWED_EMAILS` (mặc định chỉ `admin@aistockvn.com`).
- Cấp cookie `HttpOnly; Secure; SameSite=Strict` ký HMAC bằng secret `SESSION_SECRET` (30 ngày; mỗi request kiểm lại allowlist). Mọi request ghi bắt buộc header `X-Mail-Client` (chặn CSRF).
- Không có key nào trong mã web. Client ID của Google là thông tin công khai.
- `DEV_LOGIN=1` chỉ tồn tại trong `.dev.vars` local/preview; production không có biến này nên đường đăng nhập thử trả 404.

### Hiển thị thư an toàn
HTML hiển thị trong iframe `sandbox` **không có `allow-scripts`**, CSP chặn mọi tài nguyên ngoài; ảnh từ xa ẩn tới khi bấm "Hiển thị hình ảnh"; ảnh nhúng `cid:` được thay bằng data URL. Tệp đính kèm luôn tải về (`application/octet-stream` + `nosniff`).

### Hosting
Worker gắn Custom Domain `mail.aistockvn.com` (apex giữ nguyên cho trang bài viết).

## Chạy local

```bash
cd mail-web && npm ci
cp .dev.vars.example .dev.vars   # đặt SESSION_SECRET ngẫu nhiên
npm run dev                      # http://localhost:8787 — nút "Đăng nhập bản thử"
npm test && npm run typecheck
# Smoke e2e (dùng --persist-to thư mục TẠM, thư thử không lẫn vào preview):
#   npx wrangler dev --port 8788 --persist-to /tmp/mail-e2e
#   SMOKE_BASE=http://localhost:8788 npx vitest run worker/smoke.e2e.test.ts
```

## Triển khai lên Cloudflare (cần token Cloudflare — Hoplite không có)

Token cần quyền: Workers Scripts Edit, D1 Edit, R2 Edit (account `e6e3dca0…`), và trên zone `aistockvn.com`: Workers Routes Edit + Email Routing Rules Edit.

```bash
cd mail-web && npm ci
npx wrangler d1 create aistockvn-mail            # chép database_id vào wrangler.jsonc
npx wrangler r2 bucket create aistockvn-mail-raw
npx wrangler secret put RESEND_API_KEY < /data/home/.resend_api_key   # IB1; không in giá trị
openssl rand -hex 32 | npx wrangler secret put SESSION_SECRET
# Điền GOOGLE_CLIENT_ID vào "vars" trong wrangler.jsonc
npm run deploy                                    # build + migrate D1 remote + deploy
```

Sau khi deploy: Cloudflare → `aistockvn.com` → Email → Email Routing → Routing rules → sửa rule `admin@aistockvn.com` (hoặc catch-all) sang action **Send to a Worker → `aistockvn-mail`**. Worker tự forward tiếp về `skillshare01br@mail.com`.

## Thiết kế v0

`design/v0-prompt.md` là prompt thiết kế; `node design/v0_generate.mjs /home/agentuser/.v0_api_key` (LV1) hoặc với `~/.v0_api_key` (VM) gọi v0 Platform API và lưu mã vào `design/v0-output/` (gitignored). Script chỉ đọc key từ file, không in ra.
