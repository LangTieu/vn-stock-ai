#!/usr/bin/env python3
"""Read-only Cloudflare diagnostics for the telnyx-sms-relay worker.

Prints metadata only (names, timestamps, counts, HTTP statuses); never secret
values or message content. Env: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID.
"""
import difflib
import json
import os
import re
import urllib.error
import urllib.request

BASE = "https://api.cloudflare.com/client/v4"
SCRIPT = "telnyx-sms-relay"
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
ACC = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "e6e3dca05591f48f9bc8a58767c3ee01"
SINCE = "2026-11-14T00:00:00Z"
HERE = os.path.dirname(os.path.abspath(__file__))

SECRETISH = re.compile(
    r"(\d{8,10}:[A-Za-z0-9_-]{30,})"            # telegram bot token
    r"|(discord(?:app)?\.com/api/webhooks/\S+)"  # discord webhook
    r"|(KEY[0-9A-F]{20,}_\S+)"                   # telnyx api key
    r"|([A-Za-z0-9+/=_-]{40,})")                 # long opaque strings


def redact(s):
    return SECRETISH.sub("<redacted>", s)


def req(method, url, body=None, headers=None, auth=True, raw=False):
    h = dict(headers or {})
    if auth:
        h["Authorization"] = "Bearer " + TOKEN
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            data = resp.read()
            return resp.status, (data if raw else _json(data))
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (data if raw else _json(data))
    except Exception as e:  # network errors
        return 0, {"error": type(e).__name__}


def _json(data):
    try:
        return json.loads(data)
    except Exception:
        return {"_text": redact(data.decode(errors="replace")[:300])}


def cf(method, path, body=None, raw=False):
    return req(method, BASE + path, body, raw=raw)


def errs(j):
    if isinstance(j, dict):
        return redact(json.dumps(j.get("errors") or j.get("_text") or "")[:400])
    return ""


def section(t):
    print("\n=== " + t)


def main():
    if not TOKEN:
        print("CLOUDFLARE_API_TOKEN missing")
        return 0
    section("token")
    for p in ("/user/tokens/verify", "/accounts/%s/tokens/verify" % ACC):
        s, j = cf("GET", p)
        print(p, s, (j.get("result") or {}).get("status") if isinstance(j, dict) else "", errs(j) if s != 200 else "")

    section("worker scripts in account")
    s, j = cf("GET", "/accounts/%s/workers/scripts" % ACC)
    print("status", s, errs(j) if s != 200 else "")
    for w in (j.get("result") or []) if isinstance(j, dict) else []:
        print(" ", w.get("id"), "modified", w.get("modified_on"), "created", w.get("created_on"))

    section("subdomain")
    s, j = cf("GET", "/accounts/%s/workers/subdomain" % ACC)
    print(s, (j.get("result") or {}) if s == 200 else errs(j))

    if os.environ.get("ENABLE_LOGS") == "1":
        section("enable Workers Logs (settings only; code and secrets untouched)")
        s, j = cf("PATCH", "/accounts/%s/workers/scripts/%s/script-settings" % (ACC, SCRIPT),
                  {"observability": {"enabled": True, "head_sampling_rate": 1}})
        print("status", s, json.dumps((j.get("result") or {}).get("observability")) if s == 200 else errs(j))

    section("telnyx-sms-relay settings (binding names/types only)")
    s, j = cf("GET", "/accounts/%s/workers/scripts/%s/settings" % (ACC, SCRIPT))
    print("status", s, errs(j) if s != 200 else "")
    r = (j.get("result") or {}) if isinstance(j, dict) else {}
    for b in r.get("bindings") or []:
        print("  binding", b.get("type"), b.get("name"))
    for k in ("compatibility_date", "compatibility_flags", "observability", "logpush", "tail_consumers", "usage_model"):
        if k in r:
            print(" ", k, json.dumps(r.get(k)))

    section("secrets (names)")
    s, j = cf("GET", "/accounts/%s/workers/scripts/%s/secrets" % (ACC, SCRIPT))
    print("status", s, sorted(x.get("name") for x in (j.get("result") or [])) if s == 200 else errs(j))

    section("deployments / versions")
    s, j = cf("GET", "/accounts/%s/workers/scripts/%s/deployments" % (ACC, SCRIPT))
    print("deployments status", s, errs(j) if s != 200 else "")
    for d in ((j.get("result") or {}).get("deployments") or [])[:10] if isinstance(j, dict) else []:
        print("  ", d.get("created_on"), d.get("source"), d.get("strategy"),
              [(v.get("version_id"), v.get("percentage")) for v in d.get("versions") or []])
    s, j = cf("GET", "/accounts/%s/workers/scripts/%s/versions" % (ACC, SCRIPT))
    for v in ((j.get("result") or {}).get("items") or [])[:15] if isinstance(j, dict) else []:
        m = v.get("metadata") or {}
        print("   version", v.get("id"), m.get("created_on"), m.get("source"), m.get("author_email", "")[:3] + "…")

    section("deployed code vs repo worker.js")
    s, data = cf("GET", "/accounts/%s/workers/scripts/%s/content/v2" % (ACC, SCRIPT), raw=True)
    print("content status", s, "bytes", len(data) if isinstance(data, bytes) else 0)
    if s == 200 and isinstance(data, bytes):
        deployed = data.decode(errors="replace")
        local = open(os.path.join(HERE, "..", "worker.js")).read()
        diff = list(difflib.unified_diff(local.splitlines(), deployed.splitlines(),
                                         "repo/worker.js", "deployed", lineterm="", n=1))
        print("identical" if not diff else "DIFF (%d lines):" % len(diff))
        for line in diff[:400]:
            print(redact(line))

    section("invocation analytics since " + SINCE + " (UTC; ICT = UTC+7)")
    gql = """query($a:String!,$s:String!,$since:Time!,$until:Time!){viewer{accounts(filter:{accountTag:$a}){
      workersInvocationsAdaptive(limit:2000,filter:{scriptName:$s,datetime_geq:$since,datetime_leq:$until},
        orderBy:[datetimeMinute_ASC]){sum{requests errors subrequests}dimensions{datetimeMinute status %s}}}}}"""
    variables = {"a": ACC, "s": SCRIPT, "since": SINCE, "until": "2026-11-16T00:00:00Z"}
    for extra in ("httpResponseStatus", ""):
        s, j = req("POST", BASE + "/graphql", {"query": gql % extra, "variables": variables})
        if isinstance(j, dict) and j.get("errors"):
            print("graphql (%s) errors:" % (extra or "base"), redact(json.dumps(j["errors"])[:300]))
            continue
        rows = (((j.get("data") or {}).get("viewer") or {}).get("accounts") or [{}])[0].get(
            "workersInvocationsAdaptive") or []
        print("rows", len(rows), "(dims: minute,status%s)" % ("," + extra if extra else ""))
        for row in rows:
            d, su = row["dimensions"], row["sum"]
            print("  %s %-22s %s req=%s err=%s subreq=%s" % (
                d.get("datetimeMinute"), d.get("status"), d.get(extra, "") if extra else "",
                su.get("requests"), su.get("errors"), su.get("subrequests")))
        break

    section("observability events (if Workers Logs enabled)")
    body = {
        "queryId": "telnyx-diag",
        "timeframe": {"from": 1763078400000, "to": 1763251200000},
        "view": "events",
        "limit": 200,
        "parameters": {"filters": [{"key": "$workers.scriptName", "operation": "eq",
                                    "type": "string", "value": SCRIPT}]},
    }
    s, j = cf("POST", "/accounts/%s/workers/observability/telemetry/query" % ACC, body)
    print("status", s, errs(j) if s != 200 else "")
    events = (((j.get("result") or {}).get("events") or {}).get("events") or []) if isinstance(j, dict) else []
    for e in events:
        md = e.get("$metadata") or {}
        wk = e.get("$workers") or {}
        print("  ", e.get("timestamp"), wk.get("outcome"), (wk.get("event") or {}).get("response", {}).get("status") if isinstance(wk.get("event"), dict) else "",
              redact(str(md.get("message") or "")[:200]))

    section("live probes")
    sub = "vn-stock-ai"
    # Cloudflare edge rules (e.g. error 1010) block by User-Agent before the worker runs.
    for ua in (None, "curl/8.5.0", "telnyx-webhooks", "Telnyx-Webhooks/1.0", "Go-http-client/1.1",
               "Ruby", "Mozilla/5.0", ""):
        for m, path in (("GET", "/"), ("POST", "/telnyx")):
            h = {} if ua is None else {"User-Agent": ua}
            s, j = req(m, "https://%s.%s.workers.dev%s" % (SCRIPT, sub, path),
                       body=b"{}" if m == "POST" else None, headers=h, auth=False, raw=True)
            print("  UA=%-22r %-4s %-7s -> %s %r" % (ua if ua is not None else "python-urllib(default)",
                  m, path, s, (j[:30] if isinstance(j, bytes) else j)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
