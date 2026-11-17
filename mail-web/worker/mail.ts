import PostalMime, { type Email } from "postal-mime";

export interface Env {
  DB: D1Database;
  RAW: R2Bucket;
  ASSETS: Fetcher;
  MAILBOX_ADDRESS: string;
  FROM_NAME: string;
  ALLOWED_EMAILS: string;
  GOOGLE_CLIENT_ID: string;
  FORWARD_TO: string;
  RESEND_API_KEY?: string;
  SESSION_SECRET?: string;
  /** Chỉ đặt trong .dev.vars khi chạy local; production không bao giờ có. */
  DEV_LOGIN?: string;
}

export type AttachmentMeta = { index: number; filename: string; mimeType: string; size: number; inline: boolean };

const MAX_TEXT = 200_000;

export function htmlToText(html: string): string {
  return html
    .replace(/<(style|script|head)[^>]*>[\s\S]*?<\/\1>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|tr|li|h\d)>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n\s*\n\s*\n+/g, "\n\n")
    .trim();
}

export function makeSnippet(text: string): string {
  return text.replace(/\s+/g, " ").trim().slice(0, 160);
}

function addrList(list: Email["to"]): { address: string; name: string }[] {
  const out: { address: string; name: string }[] = [];
  for (const a of list || []) {
    if ("group" in a && a.group) for (const g of a.group) out.push({ address: g.address || "", name: g.name || "" });
    else out.push({ address: (a as any).address || "", name: a.name || "" });
  }
  return out;
}

export function attachmentMeta(email: Email): AttachmentMeta[] {
  return email.attachments.map((a, index) => ({
    index,
    filename: a.filename || `tep-${index + 1}`,
    mimeType: a.mimeType,
    size: typeof a.content === "string" ? a.content.length : (a.content as ArrayBuffer).byteLength,
    inline: a.disposition === "inline" && !!a.contentId,
  }));
}

/** Lưu một thư đến: bản gốc vào R2, siêu dữ liệu + text vào D1. Trả về id (hoặc id cũ nếu trùng). */
export async function ingestInbound(
  env: Env,
  raw: ArrayBuffer,
  envelope: { from: string; to: string },
  now = Date.now(),
): Promise<{ id: string; duplicate: boolean }> {
  const email = await PostalMime.parse(raw);
  const messageId = email.messageId?.trim() || null;
  if (messageId) {
    const dup = await env.DB.prepare("SELECT id FROM messages WHERE folder='inbox' AND message_id=?")
      .bind(messageId)
      .first<{ id: string }>();
    if (dup) return { id: dup.id, duplicate: true };
  }
  const id = crypto.randomUUID();
  const d = new Date(now);
  const rawKey = `raw/${d.getUTCFullYear()}/${String(d.getUTCMonth() + 1).padStart(2, "0")}/${id}.eml`;
  await env.RAW.put(rawKey, raw, { httpMetadata: { contentType: "message/rfc822" } });

  const text = (email.text || (email.html ? htmlToText(email.html) : "")).slice(0, MAX_TEXT);
  const parsedDate = email.date ? Date.parse(email.date) : NaN;
  const from = email.from && "address" in email.from ? email.from : { address: envelope.from, name: "" };
  await env.DB.prepare(
    `INSERT OR IGNORE INTO messages (id, folder, message_id, in_reply_to, references_hdr, envelope_from, envelope_to,
      from_addr, from_name, to_addrs, cc_addrs, reply_to, subject, snippet, text_body, date, is_read, raw_key, size, attachments)
     VALUES (?, 'inbox', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)`,
  )
    .bind(
      id,
      messageId,
      email.inReplyTo || null,
      email.references || null,
      envelope.from,
      envelope.to,
      (from.address || envelope.from || "").toLowerCase(),
      from.name || "",
      JSON.stringify(addrList(email.to)),
      JSON.stringify(addrList(email.cc)),
      email.replyTo?.length ? JSON.stringify(addrList(email.replyTo)) : null,
      email.subject || "",
      makeSnippet(text),
      text,
      // Ngày nhận thực tế dùng khi header Date thiếu/lệch xa tương lai.
      Number.isFinite(parsedDate) && parsedDate < now + 86_400_000 ? parsedDate : now,
      rawKey,
      raw.byteLength,
      JSON.stringify(attachmentMeta(email)),
    )
    .run();
  return { id, duplicate: false };
}

/** Thay `cid:` trong HTML bằng data URL của ảnh nhúng để hiển thị offline. */
export function inlineCidImages(html: string, email: Email): string {
  let out = html;
  for (const a of email.attachments) {
    if (!a.contentId) continue;
    const cid = a.contentId.replace(/^<|>$/g, "");
    const bytes = typeof a.content === "string" ? new TextEncoder().encode(a.content) : new Uint8Array(a.content);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    out = out.split(`cid:${cid}`).join(`data:${a.mimeType};base64,${btoa(bin)}`);
  }
  return out;
}

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function textToHtml(text: string): string {
  return `<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;white-space:pre-wrap">${escapeHtml(text)}</div>`;
}

const EMAIL_RE = /^[^\s@<>(),;:"]+@[^\s@<>(),;:"]+\.[^\s@<>(),;:"]+$/;

export function parseRecipients(input: string | string[] | undefined): string[] {
  const parts = (Array.isArray(input) ? input.join(",") : input || "")
    .split(/[,;\s]+/)
    .map((s) => s.trim().replace(/^<|>$/g, ""))
    .filter(Boolean);
  for (const p of parts) if (!EMAIL_RE.test(p)) throw new Error(`Địa chỉ không hợp lệ: ${p}`);
  return [...new Set(parts.map((p) => p.toLowerCase()))];
}
