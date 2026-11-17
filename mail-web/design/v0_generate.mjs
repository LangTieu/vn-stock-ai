#!/usr/bin/env node
// Gửi design/v0-prompt.md lên v0 Platform API (POST https://api.v0.dev/v1/chats) và lưu mã sinh ra
// vào design/v0-output/. Key chỉ đọc từ file (mặc định ~/.v0_api_key, 0600) — không bao giờ in ra.
// Dùng: node design/v0_generate.mjs [đường-dẫn-file-key]
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const keyPath = process.argv[2] || join(homedir(), ".v0_api_key");
const key = readFileSync(keyPath, "utf8").trim();
const prompt = readFileSync(join(here, "v0-prompt.md"), "utf8").split("---").slice(1).join("---").trim();

const res = await fetch("https://api.v0.dev/v1/chats", {
  method: "POST",
  headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
  body: JSON.stringify({ message: prompt, responseMode: "sync" }),
});
const data = await res.json().catch(() => ({}));
if (!res.ok) {
  console.error(`v0 API lỗi HTTP ${res.status}: ${JSON.stringify(data).slice(0, 500)}`);
  process.exit(1);
}

const out = join(here, "v0-output");
mkdirSync(out, { recursive: true });
const files = data.latestVersion?.files || data.files || [];
for (const f of files) {
  const p = join(out, f.name);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, f.content);
}
writeFileSync(
  join(out, "chat.json"),
  JSON.stringify({ id: data.id, webUrl: data.webUrl, demo: data.latestVersion?.demoUrl, files: files.map((f) => f.name) }, null, 2),
);
console.log(`v0 chat: ${data.webUrl || data.id}`);
console.log(`demo: ${data.latestVersion?.demoUrl || "(chưa có)"}`);
console.log(`${files.length} tệp → ${out}`);
