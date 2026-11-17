// Smoke test end-to-end với `wrangler dev` (DEV_LOGIN=1, --persist-to thư mục TẠM).
// Chạy: SMOKE_BASE=http://localhost:8788 npx vitest run worker/smoke.e2e.test.ts
// Thư thử chỉ nằm trong kho tạm đó, không dùng cho preview/production.
import { describe, expect, it } from "vitest";

const BASE = process.env.SMOKE_BASE;
const H = { "X-Mail-Client": "1", "Content-Type": "application/json" };
const b64 = (s: string) => Buffer.from(s).toString("base64");

describe.skipIf(!BASE)("smoke local", () => {
  let cookie = "";
  const mid = `smoke-${Date.now()}@local.test`;
  const get = (p: string, c = cookie) => fetch(BASE + p, { headers: { Cookie: c } });
  const inject = (raw: string) =>
    fetch(`${BASE}/cdn-cgi/local/email?from=sender@local.test&to=admin@aistockvn.com`, { method: "POST", body: raw });

  it("chặn truy cập khi chưa đăng nhập và POST thiếu header", async () => {
    expect((await get("/api/messages", "")).status).toBe(401);
    expect((await get("/api/messages", "mail_session=forged.sig")).status).toBe(401);
    expect((await fetch(`${BASE}/api/auth/dev`, { method: "POST" })).status).toBe(403);
  });

  it("nhận thư qua email handler", async () => {
    const raw = [
      `From: "Người Gửi Thử" <sender@local.test>`,
      `To: admin@aistockvn.com`,
      `Subject: =?UTF-8?B?${b64("Thư kiểm thử cục bộ")}?=`,
      `Date: ${new Date().toUTCString()}`,
      `Message-ID: <${mid}>`,
      `MIME-Version: 1.0`,
      `Content-Type: multipart/mixed; boundary="b1"`,
      ``,
      `--b1`,
      `Content-Type: text/html; charset=utf-8`,
      ``,
      `<p>Nội dung <b>kiểm thử</b> khoa-smoke-xyz</p>`,
      `--b1`,
      `Content-Type: text/plain; name="note.txt"`,
      `Content-Disposition: attachment; filename="note.txt"`,
      ``,
      `hello attachment`,
      `--b1--`,
      ``,
    ].join("\r\n");
    const r = await inject(raw);
    expect(r.status).toBeLessThan(300);
  });

  it("đăng nhập, liệt kê, tìm kiếm, đọc, tải tệp", async () => {
    const login = await fetch(`${BASE}/api/auth/dev`, { method: "POST", headers: H });
    expect(login.status).toBe(200);
    cookie = login.headers.get("set-cookie")!.split(";")[0];

    const list = await (await get("/api/messages?folder=inbox")).json();
    const m = list.items.find((i: any) => i.subject === "Thư kiểm thử cục bộ");
    expect(m).toBeTruthy();
    expect(m.from).toEqual({ address: "sender@local.test", name: "Người Gửi Thử" });
    expect(m.isRead).toBe(false);
    expect(m.hasAttachments).toBe(true);
    expect((await (await get("/api/counts")).json()).unread).toBeGreaterThanOrEqual(1);

    const hit = await (await get("/api/messages?folder=inbox&q=khoa-smoke-xyz")).json();
    expect(hit.items.map((i: any) => i.id)).toContain(m.id);
    const miss = await (await get("/api/messages?folder=inbox&q=khong-ton-tai-zzz")).json();
    expect(miss.items).toEqual([]);

    const d = await (await get(`/api/messages/${m.id}`)).json();
    expect(d.html).toContain("<b>kiểm thử</b>");
    expect(d.attachments.map((a: any) => a.filename)).toEqual(["note.txt"]);
    const att = await get(`/api/messages/${m.id}/attachments/0`);
    expect(att.headers.get("content-disposition")).toContain("attachment");
    expect((await att.text()).trim()).toBe("hello attachment");

    const after = await (await get("/api/messages?folder=inbox")).json();
    expect(after.items.find((i: any) => i.id === m.id).isRead).toBe(true);
  });

  it("không lưu trùng cùng Message-ID", async () => {
    await inject(`From: sender@local.test\r\nTo: admin@aistockvn.com\r\nSubject: dup\r\nMessage-ID: <${mid}>\r\n\r\nx`);
    const list = await (await get("/api/messages?folder=inbox&q=dup")).json();
    expect(list.items).toEqual([]);
  });

  it("gửi thư báo rõ khi chưa có RESEND_API_KEY", async () => {
    const r = await fetch(`${BASE}/api/send`, {
      method: "POST",
      headers: { ...H, Cookie: cookie },
      body: JSON.stringify({ to: "a@b.com", subject: "x", text: "y" }),
    });
    expect(r.status).toBe(503);
  });
});
