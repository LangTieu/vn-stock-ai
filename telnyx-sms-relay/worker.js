// telnyx-sms-relay: forwards inbound Telnyx SMS (message.received) to
// Telegram, Discord and WhatsApp. Stateless; never logs message content.

const MAX_SKEW_SECONDS = 300;
const WHATSAPP_API_VERSION = "v21.0";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "GET" && path === "/") {
      return new Response("ok", { status: 200 });
    }
    if (path !== "/" && path !== "/telnyx") {
      return new Response("not found", { status: 404 });
    }
    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405, headers: { allow: "GET, POST" } });
    }

    const rawBody = await request.text();

    if (env.TELNYX_PUBLIC_KEY) {
      const ok = await verifyTelnyxSignature(
        env.TELNYX_PUBLIC_KEY,
        request.headers.get("telnyx-signature-ed25519"),
        request.headers.get("telnyx-timestamp"),
        rawBody,
      );
      if (!ok) {
        console.log("relay: rejected request with invalid signature or timestamp");
        return new Response("invalid signature", { status: 401 });
      }
    }

    let event;
    try {
      event = JSON.parse(rawBody);
    } catch {
      return new Response("invalid json", { status: 400 });
    }

    const data = event && event.data;
    if (!data || data.event_type !== "message.received") {
      return new Response("ignored", { status: 200 });
    }

    const message = formatMessage(data.payload || {});
    const targets = forwardTargets(env);
    if (targets.length === 0) {
      console.log("relay: message received, no forwarding targets configured");
      return new Response("ok", { status: 200 });
    }

    // Answer Telnyx immediately; forwarding continues in the background.
    ctx.waitUntil(forwardAll(targets, message));
    return new Response("ok", { status: 200 });
  },
};

async function verifyTelnyxSignature(publicKeyB64, signatureB64, timestamp, rawBody) {
  if (!signatureB64 || !timestamp || !/^\d+$/.test(timestamp)) return false;

  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - Number(timestamp)) > MAX_SKEW_SECONDS) return false;

  try {
    const key = await crypto.subtle.importKey(
      "raw",
      base64ToBytes(publicKeyB64),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const signed = new TextEncoder().encode(`${timestamp}|${rawBody}`);
    return await crypto.subtle.verify("Ed25519", key, base64ToBytes(signatureB64), signed);
  } catch (err) {
    console.log(`relay: signature verification error: ${err && err.name}`);
    return false;
  }
}

function base64ToBytes(b64) {
  const bin = atob(b64.trim());
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function phoneOf(value) {
  if (!value) return "unknown";
  if (typeof value === "string") return value;
  return value.phone_number || "unknown";
}

function formatMessage(payload) {
  const from = phoneOf(payload.from);
  const toList = Array.isArray(payload.to) ? payload.to : [payload.to];
  const to = toList.map(phoneOf).join(", ");
  const text = typeof payload.text === "string" ? payload.text : "";
  const media = Array.isArray(payload.media) ? payload.media.length : 0;
  const mediaNote = media > 0 ? `\n[${media} media attachment(s) not forwarded]` : "";
  return `SMS from ${from} to ${to}\n\n${text}${mediaNote}`;
}

function forwardTargets(env) {
  const targets = [];
  if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
    targets.push({ name: "telegram", send: (msg) => sendTelegram(env, msg) });
  }
  if (env.DISCORD_WEBHOOK_URL) {
    targets.push({ name: "discord", send: (msg) => sendDiscord(env, msg) });
  }
  if (env.WHATSAPP_PHONE_NUMBER_ID && env.WHATSAPP_TOKEN && env.WHATSAPP_RECIPIENT) {
    targets.push({ name: "whatsapp", send: (msg) => sendWhatsApp(env, msg) });
  }
  return targets;
}

async function forwardAll(targets, message) {
  const results = await Promise.allSettled(targets.map((t) => t.send(message)));
  let ok = 0;
  results.forEach((r, i) => {
    if (r.status === "fulfilled") ok++;
    // Log only the target and a status/error name; never response bodies, which may echo content.
    else console.log(`relay: ${targets[i].name} forward failed: ${r.reason && r.reason.message}`);
  });
  console.log(`relay: forwarded 1 message, ${ok}/${targets.length} targets ok`);
}

async function postJson(url, body, headers = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

function truncate(text, max) {
  return text.length <= max ? text : text.slice(0, max - 1) + "…";
}

function sendTelegram(env, message) {
  return postJson(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    chat_id: env.TELEGRAM_CHAT_ID,
    text: truncate(message, 4096),
    disable_web_page_preview: true,
  });
}

function sendDiscord(env, message) {
  return postJson(env.DISCORD_WEBHOOK_URL, {
    content: truncate(message, 2000),
    allowed_mentions: { parse: [] },
  });
}

function sendWhatsApp(env, message) {
  return postJson(
    `https://graph.facebook.com/${WHATSAPP_API_VERSION}/${env.WHATSAPP_PHONE_NUMBER_ID}/messages`,
    {
      messaging_product: "whatsapp",
      to: env.WHATSAPP_RECIPIENT,
      type: "text",
      text: { body: truncate(message, 4096), preview_url: false },
    },
    { authorization: `Bearer ${env.WHATSAPP_TOKEN}` },
  );
}
