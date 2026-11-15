#!/usr/bin/env python3
"""Find Telnyx/Telegram/Discord credentials on this host and run read-only checks.

Prints file paths, credential fingerprints (sha256 prefix) and API metadata only;
never credential values or SMS text. Phone numbers are partially masked except
the relay's own number.
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

OUR_NUMBER = "+12015785620"
SINCE = "2026-11-14T00:00:00Z"
SKIP_DIRS = {".git", "node_modules", ".cache", "venv", ".venv", "site-packages", "dist-packages",
             "huggingface", ".npm", ".rustup", ".cargo", "go", "snap", "proc", "sys", ".local/lib",
             "__pycache__", "_work", "ollama", "models", "checkpoints"}
ROOTS = [os.path.expanduser("~"), "/opt", "/etc/environment", "/srv", "/root", "/home"]
PATTERNS = {
    "telnyx_api_key": re.compile(r"\bKEY0[0-9A-F]{20,}_[A-Za-z0-9]{10,}\b"),
    "telegram_bot_token": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,40}\b"),
    "discord_webhook": re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"),
}
NAME_HINT = re.compile(r"(TELNYX[A-Z_]*|TELEGRAM[A-Z_]*|DISCORD[A-Z_]*|CLOUDFLARE_API_TOKEN)")


def fp(v):
    return hashlib.sha256(v.encode()).hexdigest()[:10]


def mask(num):
    if not isinstance(num, str) or num == OUR_NUMBER or len(num) < 6:
        return num
    return num[:4] + "…" + num[-3:]


def scan():
    found = {k: {} for k in PATTERNS}
    hints = {}
    seen_files = 0
    for root in ROOTS:
        if os.path.isfile(root):
            walk = [(os.path.dirname(root), [], [os.path.basename(root)])]
        elif os.path.isdir(root):
            walk = os.walk(root, onerror=lambda e: None)
        else:
            continue
        base_depth = root.rstrip("/").count("/")
        for d, dirs, files in walk:
            if d.count("/") - base_depth >= 6:
                dirs[:] = []
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in files:
                p = os.path.join(d, f)
                try:
                    if os.path.islink(p) or os.path.getsize(p) > 1_000_000:
                        continue
                    with open(p, "rb") as fh:
                        data = fh.read()
                except Exception:
                    continue
                if b"\0" in data[:4096]:
                    continue
                seen_files += 1
                text = data.decode(errors="ignore")
                for kind, rx in PATTERNS.items():
                    for v in set(rx.findall(text)):
                        found[kind].setdefault(v, set()).add(p)
                for n in set(NAME_HINT.findall(text)):
                    hints.setdefault(n, set()).add(p)
    for env_name in ("TELNYX_API_KEY_GH", "TELEGRAM_BOT_TOKEN_GH", "DISCORD_WEBHOOK_URL_GH"):
        v = os.environ.get(env_name, "").strip()
        if v:
            for kind, rx in PATTERNS.items():
                if rx.fullmatch(v):
                    found[kind].setdefault(v, set()).add("github-secret:" + env_name[:-3])
    return found, hints, seen_files


def http(method, url, headers=None, body=None):
    r = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": type(e).__name__}


def telnyx(key, path, params=None):
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    return http("GET", "https://api.telnyx.com/v2" + path + q, {"Authorization": "Bearer " + key})


def check_telnyx(key):
    s, j = telnyx(key, "/phone_numbers", {"filter[phone_number]": OUR_NUMBER})
    print("  phone_numbers:", s, [e.get("title") for e in j.get("errors", [])] if s != 200 else "")
    nums = j.get("data") or []
    for n in nums:
        print("   number", n.get("phone_number"), "status", n.get("status"), "messaging_profile_id",
              n.get("messaging_profile_id"), "connection", n.get("connection_name") or n.get("connection_id"))
        s2, m = telnyx(key, "/phone_numbers/%s/messaging" % n.get("id"))
        md = m.get("data") or {}
        print("   messaging settings:", s2, json.dumps({k: md.get(k) for k in (
            "messaging_profile_id", "features", "eligible_messaging_products", "messaging_product",
            "health", "traffic_type", "type", "country_code")}))
    s, j = telnyx(key, "/messaging_profiles", {"page[size]": "50"})
    print("  messaging_profiles:", s)
    for p in j.get("data") or []:
        print("   profile", json.dumps({k: p.get(k) for k in (
            "id", "name", "enabled", "webhook_url", "webhook_failover_url", "webhook_api_version",
            "whitelisted_destinations", "number_pool_settings", "updated_at")}))
    s, j = telnyx(key, "/webhook_deliveries", {"page[size]": "100"})
    print("  webhook_deliveries:", s, [e.get("title") for e in j.get("errors", [])] if s != 200 else "")
    for d in j.get("data") or []:
        w = d.get("webhook") or {}
        if (w.get("occurred_at") or d.get("started_at") or "") < SINCE:
            continue
        print("   delivery", d.get("status"), "event", w.get("event_type"), "occurred", w.get("occurred_at"))
        for a in d.get("attempts") or []:
            h = a.get("http") or {}
            resp = h.get("response") or {}
            body = resp.get("body") or ""
            print("     attempt", a.get("started_at"), a.get("status"), "url", (h.get("request") or {}).get("url"),
                  "->", resp.get("status"), repr(body[:40]) if isinstance(body, str) else "",
                  "errors", [e.get("title") if isinstance(e, dict) else e for e in a.get("errors") or []])
    s, j = telnyx(key, "/detail_records", {"filter[record_type]": "messaging", "filter[created_at][gte]": SINCE,
                                          "page[size]": "50", "sort": "-created_at"})
    print("  messaging detail_records:", s, [e.get("title") for e in j.get("errors", [])] if s != 200 else "")
    for r in j.get("data") or []:
        print("   mdr", r.get("created_at"), r.get("direction"), r.get("message_type"), "status", r.get("status"),
              "from", mask(r.get("cli")), "to", mask(r.get("cld")), "profile", r.get("profile_name") or r.get("messaging_profile_id"),
              "errors", r.get("errors"), "parts", r.get("parts"))


def main():
    found, hints, n = scan()
    print("scanned text files:", n)
    print("\n=== env/var name hints (name -> files)")
    for name, files in sorted(hints.items()):
        print(" ", name, sorted(files)[:6])
    print("\n=== credentials found (fingerprint -> files)")
    for kind, vals in found.items():
        print(" ", kind, len(vals))
        for v, files in vals.items():
            print("    ", fp(v), sorted(files)[:6])
    print("\n=== telegram getMe")
    for v in found["telegram_bot_token"]:
        s, j = http("GET", "https://api.telegram.org/bot%s/getMe" % v)
        r = j.get("result") or {}
        print("  ", fp(v), s, "@" + str(r.get("username")), "id", r.get("id"))
    print("\n=== discord webhook metadata")
    for v in found["discord_webhook"]:
        s, j = http("GET", v)
        print("  ", fp(v), s, "name", j.get("name"), "channel", j.get("channel_id"), "guild", j.get("guild_id"))
    print("\n=== telnyx")
    for v in found["telnyx_api_key"]:
        print(" key", fp(v))
        check_telnyx(v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
