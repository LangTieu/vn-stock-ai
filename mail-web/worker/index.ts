import PostalMime from "postal-mime";
import {
  SESSION_COOKIE,
  isAllowed,
  readCookie,
  sessionCookie,
  signSession,
  verifyGoogleIdToken,
  verifySession,
} from "./auth";
import {
  type AttachmentMeta,
  type Env,
  ingestInbound,
  inlineCidImages,
  makeSnippet,
  parseRecipients,
  textToHtml,
} from "./mail";

const json = (data: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...headers },
  });

const err = (message: string, status: number) => json({ error: message }, status);

type Row = Record<string, any>;

function listItem(r: Row) {
  return {
    id: r.id,
    folder: r.folder,
    from: { address: r.from_addr, name: r.from_name },
    to: JSON.parse(r.to_addrs),
    subject: r.subject,
    snippet: r.snippet,
    date: r.date,
    isRead: !!r.is_read,
    hasAttachments: r.attachments !== "[]",
  };
}

async function handleApi(req: Request, env: Env, url: URL): Promise<Response> {
  const path = url.pathname.replace(/\/+$/, "");
  const secure = url.protocol === "https:";

  // Header tùy biến buộc preflight CORS cho request khác origin (không được phép) → chặn CSRF.
  if (req.method !== "GET" && req.headers.get("X-Mail-Client") !== "1") return err("Thiếu header", 403);

  if (path === "/api/config" && req.method === "GET") {
    return json({
      googleClientId: env.GOOGLE_CLIENT_ID || "",
      devLogin: env.DEV_LOGIN === "1",
      mailbox: env.MAILBOX_ADDRESS,
      sendingEnabled: !!env.RESEND_API_KEY,
    });
  }

  if (path === "/api/auth/google" && req.method === "POST") {
    const { credential } = (await req.json().catch(() => ({}))) as { credential?: string };
    if (!credential) return err("Thiếu credential", 400);
    let email: string;
    try {
      ({ email } = await verifyGoogleIdToken(credential, env.GOOGLE_CLIENT_ID));
    } catch (e) {
      return err(`Đăng nhập Google thất bại: ${(e as Error).message}`, 401);
    }
    if (!isAllowed(email, env.ALLOWED_EMAILS)) return err(`Tài khoản ${email} không có quyền truy cập`, 403);
    return json({ email }, 200, { "Set-Cookie": sessionCookie(await signSession(email, env.SESSION_SECRET || ""), secure) });
  }

  if (path === "/api/auth/dev" && req.method === "POST") {
    if (env.DEV_LOGIN !== "1") return err("Không khả dụng", 404);
    const email = env.ALLOWED_EMAILS.split(",")[0].trim().toLowerCase();
    return json({ email }, 200, { "Set-Cookie": sessionCookie(await signSession(email, env.SESSION_SECRET || ""), secure) });
  }

  if (path === "/api/logout" && req.method === "POST") {
    return json({ ok: true }, 200, { "Set-Cookie": sessionCookie("", secure, 0) });
  }

  const user = await verifySession(readCookie(req, SESSION_COOKIE), env.SESSION_SECRET || "", env.ALLOWED_EMAILS);
  if (!user) return err("Chưa đăng nhập", 401);

  if (path === "/api/session") return json({ email: user, mailbox: env.MAILBOX_ADDRESS });

  if (path === "/api/messages" && req.method === "GET") {
    const folder = url.searchParams.get("folder") === "sent" ? "sent" : "inbox";
    const q = (url.searchParams.get("q") || "").trim();
    const before = Number(url.searchParams.get("before")) || Number.MAX_SAFE_INTEGER;
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit")) || 30, 1), 100);
    const binds: unknown[] = [folder, before];
    let where = "folder = ? AND date < ?";
    if (q) {
      const like = `%${q.replace(/[\\%_]/g, (c) => "\\" + c)}%`;
      where += ` AND (subject LIKE ?3 ESCAPE '\\' OR from_addr LIKE ?3 ESCAPE '\\' OR from_name LIKE ?3 ESCAPE '\\'
        OR to_addrs LIKE ?3 ESCAPE '\\' OR text_body LIKE ?3 ESCAPE '\\')`;
      binds.push(like);
    }
    const { results } = await env.DB.prepare(
      `SELECT id, folder, from_addr, from_name, to_addrs, subject, snippet, date, is_read, attachments
       FROM messages WHERE ${where} ORDER BY date DESC LIMIT ${limit + 1}`,
    )
      .bind(...binds)
      .all<Row>();
    const items = results.slice(0, limit).map(listItem);
    return json({ items, nextBefore: results.length > limit ? items[items.length - 1].date : null });
  }

  if (path === "/api/counts") {
    const r = await env.DB.prepare("SELECT COUNT(*) AS n FROM messages WHERE folder='inbox' AND is_read=0").first<{ n: number }>();
    return json({ unread: r?.n ?? 0 });
  }

  const m = path.match(/^\/api\/messages\/([0-9a-f-]{36})(?:\/(read|attachments\/(\d+)))?$/);
  if (m) {
    const row = await env.DB.prepare("SELECT * FROM messages WHERE id = ?").bind(m[1]).first<Row>();
    if (!row) return err("Không tìm thấy thư", 404);

    if (m[2] === "read" && req.method === "POST") {
      const { read } = (await req.json().catch(() => ({}))) as { read?: boolean };
      await env.DB.prepare("UPDATE messages SET is_read = ? WHERE id = ?").bind(read === false ? 0 : 1, row.id).run();
      return json({ ok: true });
    }

    if (m[3] !== undefined && req.method === "GET") {
      if (!row.raw_key) return err("Không có tệp đính kèm", 404);
      const obj = await env.RAW.get(row.raw_key);
      if (!obj) return err("Thiếu bản gốc thư", 404);
      const email = await PostalMime.parse(await obj.arrayBuffer());
      const a = email.attachments[Number(m[3])];
      if (!a) return err("Không tìm thấy tệp", 404);
      const name = (a.filename || `tep-${Number(m[3]) + 1}`).replace(/["\r\n]/g, "");
      return new Response(a.content as BodyInit, {
        headers: {
          // Luôn tải về, không render trong origin của ứng dụng.
          "Content-Type": "application/octet-stream",
          "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(name)}`,
          "X-Content-Type-Options": "nosniff",
          "Cache-Control": "private, no-store",
        },
      });
    }

    if (!m[2] && req.method === "GET") {
      let html: string | null = row.html_body;
      let text: string = row.text_body;
      if (row.folder === "inbox" && row.raw_key) {
        const obj = await env.RAW.get(row.raw_key);
        if (obj) {
          const email = await PostalMime.parse(await obj.arrayBuffer());
          html = email.html ? inlineCidImages(email.html, email) : null;
          text = email.text || text;
        }
      }
      if (!row.is_read) await env.DB.prepare("UPDATE messages SET is_read = 1 WHERE id = ?").bind(row.id).run();
      return json({
        ...listItem({ ...row, is_read: 1 }),
        cc: JSON.parse(row.cc_addrs),
        replyTo: row.reply_to ? JSON.parse(row.reply_to) : [],
        messageId: row.message_id,
        references: row.references_hdr,
        text,
        html,
        attachments: (JSON.parse(row.attachments) as AttachmentMeta[]).filter((a) => !a.inline),
      });
    }
  }

  if (path === "/api/send" && req.method === "POST") {
    if (!env.RESEND_API_KEY) return err("Chưa cấu hình RESEND_API_KEY trên server", 503);
    const body = (await req.json().catch(() => ({}))) as {
      to?: string;
      cc?: string;
      subject?: string;
      text?: string;
      replyToId?: string;
      clientId?: string;
    };
    let to: string[], cc: string[];
    try {
      to = parseRecipients(body.to);
      cc = parseRecipients(body.cc);
    } catch (e) {
      return err((e as Error).message, 400);
    }
    if (!to.length) return err("Cần ít nhất một người nhận", 400);
    const subject = (body.subject || "").trim();
    const text = body.text || "";
    if (!subject && !text.trim()) return err("Thư trống", 400);

    const headers: Record<string, string> = {};
    if (body.replyToId) {
      const orig = await env.DB.prepare("SELECT message_id, references_hdr FROM messages WHERE id = ?")
        .bind(body.replyToId)
        .first<Row>();
      if (orig?.message_id) {
        headers["In-Reply-To"] = orig.message_id;
        headers["References"] = [orig.references_hdr, orig.message_id].filter(Boolean).join(" ");
      }
    }
    const from = `${env.FROM_NAME} <${env.MAILBOX_ADDRESS}>`;
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
        // Chống gửi trùng khi người dùng bấm lại / mạng chập chờn.
        ...(body.clientId ? { "Idempotency-Key": body.clientId.slice(0, 256) } : {}),
      },
      body: JSON.stringify({
        from,
        to,
        cc: cc.length ? cc : undefined,
        subject: subject || "(Không có tiêu đề)",
        text,
        html: textToHtml(text),
        headers: Object.keys(headers).length ? headers : undefined,
      }),
    });
    const out = (await res.json().catch(() => ({}))) as { id?: string; message?: string };
    if (!res.ok || !out.id) return err(`Resend từ chối (${res.status}): ${out.message || "không rõ"}`, 502);

    const id = crypto.randomUUID();
    await env.DB.prepare(
      `INSERT INTO messages (id, folder, in_reply_to, references_hdr, from_addr, from_name, to_addrs, cc_addrs,
        subject, snippet, text_body, html_body, date, is_read, resend_id)
       VALUES (?, 'sent', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)`,
    )
      .bind(
        id,
        headers["In-Reply-To"] || null,
        headers["References"] || null,
        env.MAILBOX_ADDRESS,
        env.FROM_NAME,
        JSON.stringify(to.map((address) => ({ address, name: "" }))),
        JSON.stringify(cc.map((address) => ({ address, name: "" }))),
        subject || "(Không có tiêu đề)",
        makeSnippet(text),
        text,
        null,
        Date.now(),
        out.id,
      )
      .run();
    return json({ id, resendId: out.id });
  }

  return err("Không tìm thấy", 404);
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname.startsWith("/api/")) {
      try {
        return await handleApi(req, env, url);
      } catch (e) {
        console.error("api error", e);
        return err("Lỗi máy chủ", 500);
      }
    }
    return env.ASSETS.fetch(req);
  },

  async email(message: ForwardableEmailMessage, env: Env): Promise<void> {
    const raw = await new Response(message.raw).arrayBuffer();
    let stored = false;
    let forwarded = false;
    try {
      await ingestInbound(env, raw, { from: message.from, to: message.to });
      stored = true;
    } catch (e) {
      console.error("ingest failed", e);
    }
    // Giữ nguyên luồng forward hiện có để không mất thư nếu web lỗi.
    for (const dest of (env.FORWARD_TO || "").split(",").map((s) => s.trim()).filter(Boolean)) {
      try {
        await message.forward(dest);
        forwarded = true;
      } catch (e) {
        console.error("forward failed", dest, e);
      }
    }
    if (!stored && !forwarded) throw new Error("Không lưu và không forward được thư");
  },
} satisfies ExportedHandler<Env>;
