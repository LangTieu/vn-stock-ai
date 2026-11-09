#!/usr/bin/env python3
"""Them leg Workers AI (vn-stock-workersai) vao config LiteLLM tren may.
- Them model vn-stock-workersai (Cloudflare Workers AI, gpt-oss-120b)
  vao model_list + them vao fallback cua vn-stock (cuoi chuoi).
- Cap nhat start.sh de export CLOUDFLARE_API_TOKEN (tu file 0600)
  + CLOUDFLARE_ACCOUNT_ID (khong phai secret).
- Chi them neu chua co (idempotent). Backup config cu.
- Khoi dong lai LiteLLM (kill process cu roi start.sh) + test leg.
Dung: <venv python> add_workersai.py <DIR_LITELLM> [START_CMD...]
  START_CMD mac dinh: bash start.sh (LV1/LV2); IB1 can: bash start.sh <DIR>
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ACCOUNT_ID = "e6e3dca05591f48f9bc8a58767c3ee01"
API_BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1"

WORKERSAI_MODEL = {
    "model_name": "vn-stock-workersai",
    "litellm_params": {
        "model": "openai/@cf/openai/gpt-oss-120b",
        "api_base": API_BASE,
        "api_key": "os.environ/CLOUDFLARE_API_TOKEN",
        "timeout": 60,
    },
}


def update_start_sh(d):
    p = os.path.join(d, "start.sh")
    txt = open(p).read()
    if "CLOUDFLARE_API_TOKEN" in txt and "CLOUDFLARE_ACCOUNT_ID" in txt:
        print("start.sh da co Cloudflare, khong sua")
        return
    # Chen export Cloudflare truoc dong nohup litellm.
    lines = txt.splitlines()
    out = []
    inserted = False
    for ln in lines:
        if (not inserted) and ln.strip().startswith("nohup"):
            out.append('f="$DIR/.cloudflare_api_token"')
            out.append('[ -f "$f" ] && export CLOUDFLARE_API_TOKEN="$(cat "$f")"')
            out.append(f'export CLOUDFLARE_ACCOUNT_ID="{ACCOUNT_ID}"')
            inserted = True
        out.append(ln)
    if not inserted:
        # start.sh kieu moi (vong for) — them vao vong for neu chua co.
        txt2 = txt.replace(
            "CEREBRAS_API_KEY LLM7_API_KEY GEMINI_API_KEY RADOX_API_KEY CLOUDFLARE_API_TOKEN",
            "CEREBRAS_API_KEY LLM7_API_KEY GEMINI_API_KEY RADOX_API_KEY CLOUDFLARE_API_TOKEN")
        # Dam bao account id duoc export (them dong cuoi truoc nohup).
        if "CLOUDFLARE_ACCOUNT_ID" not in txt2:
            txt2 = txt2.replace(
                'nohup "$DIR/venv/bin/litellm"',
                f'export CLOUDFLARE_ACCOUNT_ID="{ACCOUNT_ID}"\nnohup "$DIR/venv/bin/litellm"')
        open(p, "w").write(txt2)
        print("start.sh (kieu moi) da them CLOUDFLARE_ACCOUNT_ID")
        return
    open(p, "w").write("\n".join(out) + "\n")
    print("start.sh da them Cloudflare export")


def main():
    import yaml
    d = sys.argv[1]
    start_args = sys.argv[2:] or ["bash", os.path.join(d, "start.sh")]
    cfg = os.path.join(d, "config.yaml")
    data = yaml.safe_load(open(cfg))
    have = {m["model_name"] for m in data.get("model_list", [])}
    if "vn-stock-workersai" not in have:
        import shutil
        shutil.copy(cfg, cfg + ".pre-workersai")
        data.setdefault("model_list", []).append(WORKERSAI_MODEL)
        rs = data.setdefault("router_settings", {})
        fb = rs.setdefault("fallbacks", [])
        # Them workersai vao cuoi fallback cua vn-stock.
        for rule in fb:
            if isinstance(rule, dict) and "vn-stock" in rule:
                if "vn-stock-workersai" not in rule["vn-stock"]:
                    rule["vn-stock"].append("vn-stock-workersai")
        with open(cfg, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        print("da them vn-stock-workersai + fallback")
    else:
        print("vn-stock-workersai da co trong config")
    update_start_sh(d)

    # Kill process cu + start lai.
    for p in subprocess.run(
            ["pgrep", "-f", "litellm --port"], capture_output=True,
            text=True).stdout.split():
        try:
            subprocess.run(["kill", p], timeout=5)
        except Exception:
            pass
    time.sleep(4)
    subprocess.run(["bash", "-c", " ".join(start_args)],
                   cwd=d, capture_output=True, timeout=60)
    print("da goi start.sh")
    for _ in range(12):
        time.sleep(5)
        try:
            with urllib.request.urlopen(
                    "http://localhost:4000/health/liveliness", timeout=5) as r:
                if r.status == 200:
                    print("health OK")
                    break
        except Exception:
            pass
    else:
        print("WARN: health chua len sau 60s")
        return 1
    master = open(os.path.join(d, ".master_key")).read().strip()
    body = json.dumps({"model": "vn-stock-workersai",
                       "messages": [{"role": "user", "content": "Tra loi dung 1 tu: ok"}],
                       "max_tokens": 80}).encode()
    req = urllib.request.Request(
        "http://localhost:4000/v1/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + master)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.load(r)
        txt = out["choices"][0]["message"].get("content") or ""
        print("workersai tra loi:", txt[:60])
        print("TEST OK")
    except Exception as e:
        print("WARN: goi workersai loi:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
