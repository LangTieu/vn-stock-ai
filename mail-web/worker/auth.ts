const enc = new TextEncoder();
const dec = new TextDecoder();

export function b64urlEncode(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function b64urlDecode(s: string): Uint8Array {
  const pad = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export type Jwks = { keys: (JsonWebKey & { kid?: string })[] };

export const GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs";
const GOOGLE_ISSUERS = new Set(["accounts.google.com", "https://accounts.google.com"]);

export async function fetchGoogleJwks(): Promise<Jwks> {
  const res = await fetch(GOOGLE_JWKS_URL, { cf: { cacheTtl: 3600 } } as RequestInit);
  if (!res.ok) throw new Error(`jwks ${res.status}`);
  return res.json();
}

/** Xác minh Google ID token (RS256) phía server; trả về email nếu hợp lệ. */
export async function verifyGoogleIdToken(
  token: string,
  clientId: string,
  getJwks: () => Promise<Jwks> = fetchGoogleJwks,
  nowSec: number = Math.floor(Date.now() / 1000),
): Promise<{ email: string; name?: string }> {
  if (!clientId) throw new Error("GOOGLE_CLIENT_ID chưa cấu hình");
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("token sai định dạng");
  const header = JSON.parse(dec.decode(b64urlDecode(parts[0])));
  const payload = JSON.parse(dec.decode(b64urlDecode(parts[1])));
  if (header.alg !== "RS256") throw new Error("alg không hợp lệ");
  const jwk = (await getJwks()).keys.find((k) => k.kid === header.kid);
  if (!jwk) throw new Error("không tìm thấy khóa ký");
  const key = await crypto.subtle.importKey(
    "jwk",
    { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    b64urlDecode(parts[2]),
    enc.encode(`${parts[0]}.${parts[1]}`),
  );
  if (!ok) throw new Error("chữ ký không hợp lệ");
  if (!GOOGLE_ISSUERS.has(payload.iss)) throw new Error("iss không hợp lệ");
  if (payload.aud !== clientId) throw new Error("aud không hợp lệ");
  if (typeof payload.exp !== "number" || payload.exp < nowSec) throw new Error("token hết hạn");
  if (payload.email_verified !== true || typeof payload.email !== "string")
    throw new Error("email chưa xác minh");
  return { email: payload.email.toLowerCase(), name: payload.name };
}

export function isAllowed(email: string, allowed: string): boolean {
  return allowed
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
    .includes(email.toLowerCase());
}

async function hmacKey(secret: string) {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

export const SESSION_COOKIE = "mail_session";
export const SESSION_TTL_SEC = 30 * 24 * 3600;

export async function signSession(email: string, secret: string, nowSec = Math.floor(Date.now() / 1000)) {
  if (!secret || secret.length < 32) throw new Error("SESSION_SECRET thiếu hoặc quá ngắn");
  const body = b64urlEncode(enc.encode(JSON.stringify({ e: email, x: nowSec + SESSION_TTL_SEC })));
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(body)));
  return `${body}.${b64urlEncode(sig)}`;
}

export async function verifySession(
  token: string | null,
  secret: string,
  allowed: string,
  nowSec = Math.floor(Date.now() / 1000),
): Promise<string | null> {
  if (!token || !secret || secret.length < 32) return null;
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  try {
    const ok = await crypto.subtle.verify("HMAC", await hmacKey(secret), b64urlDecode(sig), enc.encode(body));
    if (!ok) return null;
    const { e, x } = JSON.parse(dec.decode(b64urlDecode(body)));
    if (typeof x !== "number" || x < nowSec) return null;
    // Kiểm lại allowlist để gỡ quyền có hiệu lực ngay khi đổi cấu hình.
    return isAllowed(e, allowed) ? e : null;
  } catch {
    return null;
  }
}

export function readCookie(req: Request, name: string): string | null {
  const h = req.headers.get("Cookie") || "";
  for (const part of h.split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return null;
}

export function sessionCookie(value: string, secure: boolean, maxAge = SESSION_TTL_SEC) {
  return `${SESSION_COOKIE}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${secure ? "; Secure" : ""}`;
}
