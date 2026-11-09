#!/usr/bin/env python3
"""Chat completion qua OpenAI-compatible API (Cerebras / LLM7) dung credential
da dang ky. Khong ghi key vao file/log/doi so. Dung de nho model free viet
code (P3) thay Perch khi Perch hong.

Usage:
  freechat.py <cerebras|llm7> <model> <prompt-file> [max_tokens]
In ra noi dung tra loi (response text) ra stdout.
"""
import json
import sys
import urllib.request

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

HOSTS = {
    "cerebras": ("custom.cerebras", "https://api.cerebras.ai/v1"),
    "llm7": ("custom.llm7", "https://api.llm7.io/v1"),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    provider, model, prompt_file = sys.argv[1], sys.argv[2], sys.argv[3]
    max_tokens = int(sys.argv[4]) if len(sys.argv) > 4 else 4000
    if provider not in HOSTS:
        print("provider phai la cerebras hoac llm7")
        return 2
    conn, base = HOSTS[provider]
    host = base.split("//")[1].split("/")[0]  # chi hostname, khong lay path
    with open(prompt_file) as f:
        prompt = f.read()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "curl/8.5.0")
    add_surrogate_to_request(req, conn, allowed_hosts=[host])
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=120) as r:
            payload = read_json_response(r)
    except urllib.error.HTTPError as e:
        try:
            detail = read_json_response(e)
        except Exception:
            detail = {"raw": e.read().decode(errors="replace")[:500]}
        print(json.dumps({"error": e.code, "detail": detail}, ensure_ascii=False))
        return 1
    choices = payload.get("choices", [])
    if not choices:
        print(json.dumps({"error": "no choices", "payload": payload}, ensure_ascii=False))
        return 1
    print(choices[0]["message"]["content"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
