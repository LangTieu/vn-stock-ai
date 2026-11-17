import { describe, expect, it } from "vitest";
import { b64urlEncode, isAllowed, signSession, verifyGoogleIdToken, verifySession } from "./auth";
import { htmlToText, parseRecipients } from "./mail";

const enc = new TextEncoder();
const SECRET = "x".repeat(40);
const CLIENT = "client-123.apps.googleusercontent.com";

async function makeToken(payload: Record<string, unknown>, opts: { kid?: string } = {}) {
  const kp = (await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"],
  )) as CryptoKeyPair;
  const jwk = (await crypto.subtle.exportKey("jwk", kp.publicKey)) as JsonWebKey;
  const h = b64urlEncode(enc.encode(JSON.stringify({ alg: "RS256", kid: opts.kid ?? "k1" })));
  const p = b64urlEncode(enc.encode(JSON.stringify(payload)));
  const sig = new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", kp.privateKey, enc.encode(`${h}.${p}`)));
  return { token: `${h}.${p}.${b64urlEncode(sig)}`, jwks: async () => ({ keys: [{ ...jwk, kid: "k1" }] }) };
}

const good = { iss: "https://accounts.google.com", aud: CLIENT, exp: 2_000_000_000, email: "Admin@aistockvn.com", email_verified: true };

describe("verifyGoogleIdToken", () => {
  it("chấp nhận token hợp lệ và chuẩn hóa email", async () => {
    const { token, jwks } = await makeToken(good);
    expect(await verifyGoogleIdToken(token, CLIENT, jwks, 1_900_000_000)).toMatchObject({ email: "admin@aistockvn.com" });
  });
  it.each([
    ["sai aud", { ...good, aud: "other" }],
    ["hết hạn", { ...good, exp: 1 }],
    ["sai iss", { ...good, iss: "evil.com" }],
    ["email chưa xác minh", { ...good, email_verified: false }],
  ])("từ chối %s", async (_n, payload) => {
    const { token, jwks } = await makeToken(payload);
    await expect(verifyGoogleIdToken(token, CLIENT, jwks, 1_900_000_000)).rejects.toThrow();
  });
  it("từ chối chữ ký bị sửa", async () => {
    const { token, jwks } = await makeToken(good);
    const [h, , s] = token.split(".");
    const forged = b64urlEncode(enc.encode(JSON.stringify({ ...good, email: "attacker@gmail.com" })));
    await expect(verifyGoogleIdToken(`${h}.${forged}.${s}`, CLIENT, jwks, 1_900_000_000)).rejects.toThrow("chữ ký");
  });
  it("từ chối khi chưa cấu hình client id", async () => {
    const { token, jwks } = await makeToken(good);
    await expect(verifyGoogleIdToken(token, "", jwks)).rejects.toThrow();
  });
});

describe("session", () => {
  it("ký và xác minh", async () => {
    const t = await signSession("admin@aistockvn.com", SECRET, 1000);
    expect(await verifySession(t, SECRET, "admin@aistockvn.com", 2000)).toBe("admin@aistockvn.com");
  });
  it("từ chối secret khác, hết hạn, bị gỡ khỏi allowlist, hoặc bị sửa", async () => {
    const t = await signSession("admin@aistockvn.com", SECRET, 1000);
    expect(await verifySession(t, "y".repeat(40), "admin@aistockvn.com", 2000)).toBeNull();
    expect(await verifySession(t, SECRET, "admin@aistockvn.com", 1000 + 31 * 86400)).toBeNull();
    expect(await verifySession(t, SECRET, "other@aistockvn.com", 2000)).toBeNull();
    const [, sig] = t.split(".");
    const body = b64urlEncode(enc.encode(JSON.stringify({ e: "admin@aistockvn.com", x: 9e9 })));
    expect(await verifySession(`${body}.${sig}`, SECRET, "admin@aistockvn.com", 2000)).toBeNull();
  });
  it("không ký khi secret quá ngắn", async () => {
    await expect(signSession("a@b.c", "short")).rejects.toThrow();
  });
  it("allowlist không phân biệt hoa thường", () => {
    expect(isAllowed("ADMIN@aistockvn.com", " admin@aistockvn.com ,x@y.z")).toBe(true);
    expect(isAllowed("admin@aistockvn.com.evil", "admin@aistockvn.com")).toBe(false);
  });
});

describe("mail utils", () => {
  it("parseRecipients tách và kiểm tra", () => {
    expect(parseRecipients("A@x.com, b@y.vn; <c@z.org>")).toEqual(["a@x.com", "b@y.vn", "c@z.org"]);
    expect(parseRecipients("")).toEqual([]);
    expect(() => parseRecipients("khong-phai-email")).toThrow();
  });
  it("htmlToText bỏ thẻ và script", () => {
    expect(htmlToText("<p>Xin&nbsp;chào</p><script>x()</script><b>bạn</b>")).toBe("Xin chào\n bạn");
  });
});
