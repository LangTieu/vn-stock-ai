#!/usr/bin/env python3
"""Redeploy the P3 Workers gateway script via the Cloudflare API (surrogate).
Secrets are already set; this only uploads index.js (ES module) with the
secret bindings. Never prints secret values.
"""
import json
import os
import sys
import urllib.request
import uuid

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

BASE = "https://api.cloudflare.com/client/v4"
CONNECTION = "custom.cloudflare-vnstockai"
ALLOWED_HOSTS = ["api.cloudflare.com"]
ACCOUNT_ID = "e6e3dca05591f48f9bc8a58767c3ee01"
SCRIPT = "vn-stock-ai-gateway"
WORKERS_DIR = os.path.expanduser("~/workspace/vn-stock-ai-model/workers")

LITELLM_URLS = (
    # Thu tu theo latency do lai tu IB1 luc 12:2x 10/11 (401, giay):
    # IB1 0.118, IB4 0.266, IB3 0.325, IB2 0.385.
    # LightVela them lai 22:09 ICT 11/11 sau khi sua tunnel DNS: hostname
    # lv1/lv2.aistockvn.com (CNAME -> <uuid>.cfargotunnel.com, ingress
    # config v2) verify song ca 2: /health/liveliness 200 "I'm alive!",
    # /v1/models 401 LiteLLM (da toi tunnel). Dat cuoi (qua tunnel, cham
    # hon IB truc tiep: ~0.3-0.7s tu IB4).
    "https://4000-agq2ln7pkiptkjif5rapg6ajeu.instabox.tech,"
    "https://4000-agq34ej3bbchwgwxejqglzikme.instabox.tech,"
    "https://4000-agq332yzdd6xkookjmi6sr2mba.instabox.tech,"
    "https://4000-agqzelppmu4se45k5tscmuxije.instabox.tech,"
    "https://lv1.aistockvn.com,"
    "https://lv2.aistockvn.com"
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused")


def call(method, path, body=None, content_type=None):
    req = urllib.request.Request(BASE + path, data=body, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    add_surrogate_to_request(req, CONNECTION, allowed_hosts=ALLOWED_HOSTS)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=120) as r:
            return read_json_response(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")[:600]
        print("HTTP %d on %s %s: %s" % (e.code, method, path, raw))
        return {"success": False, "errors": [{"code": e.code, "message": raw}]}


def encode_multipart(fields, files):
    boundary = "----cf-" + uuid.uuid4().hex
    body = b""
    for name, value, mime in fields:
        body += ("--" + boundary + "\r\n").encode()
        body += ('Content-Disposition: form-data; name="%s"\r\n' % name).encode()
        if mime:
            body += ("Content-Type: %s\r\n" % mime).encode()
        body += b"\r\n"
        body += value.encode() + b"\r\n"
    for name, filename, data, mime in files:
        body += ("--" + boundary + "\r\n").encode()
        body += ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (name, filename)).encode()
        body += ("Content-Type: %s\r\n\r\n" % mime).encode()
        body += data + b"\r\n"
    body += ("--" + boundary + "--\r\n").encode()
    return body, "multipart/form-data; boundary=" + boundary


def main():
    gw = open("/tmp/gateway_api_key").read().strip()
    mk = open(os.path.expanduser("~/.litellm_shared_master_key")).read().strip()
    if not gw or not mk:
        print("ERR: secret file empty")
        return 1
    script = open(os.path.join(WORKERS_DIR, "index.js"), "rb").read()
    meta = json.dumps({
        "main_module": "index.js",
        "compatibility_date": "2026-11-09",
        "bindings": [
            {"type": "secret_text", "name": "LITELLM_URLS", "text": LITELLM_URLS},
            {"type": "secret_text", "name": "GATEWAY_API_KEY", "text": gw},
            {"type": "secret_text", "name": "LITELLM_MASTER_KEY", "text": mk},
        ],
    })
    body, ct = encode_multipart(
        [("metadata", meta, "application/json")],
        [("index.js", "index.js", script, "application/javascript+module")])
    res = call("PUT", "/accounts/%s/workers/scripts/%s" % (ACCOUNT_ID, SCRIPT),
               body=body, content_type=ct)
    if not res.get("success"):
        print("ERR deploy")
        return 1
    print("deploy OK, script id:", res.get("result", {}).get("id"))
    res = call("GET", "/accounts/%s/workers/scripts/%s/secrets" % (ACCOUNT_ID, SCRIPT))
    names = sorted(s.get("name") for s in res.get("result", []))
    print("secrets on worker:", names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
