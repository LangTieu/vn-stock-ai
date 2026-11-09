#!/usr/bin/env python3
"""Dua Workers AI len dau chuoi vn-stock, FOSTA (Codex) xuong du phong.
- Doi model `vn-stock` thanh Workers AI (@cf/openai/gpt-oss-120b).
- Fallback cua `vn-stock` sap lai: Cerebras -> FOSTA key1 -> FOSTA key2
  -> BeatAPI (DeepSeek/GLM). Workers AI khong nam trong fallback nua
  vi `vn-stock` chinh la Workers AI.
- Chi doi neu chua dung thu tu (idempotent). Backup config cu.
- Khoi dong lai LiteLLM + test `vn-stock` (phai dung Workers AI).
Dung: <venv python> reorder_workersai_first.py <DIR_LITELLM> [START_CMD...]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ACCOUNT_ID = "e6e3dca05591f48f9bc8a58767c3ee01"
API_BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1"

WORKERSAI_PARAMS = {
    "model": "openai/@cf/openai/gpt-oss-120b",
    "api_base": API_BASE,
    "api_key": "os.environ/CLOUDFLARE_API_TOKEN",
    "timeout": 60,
}

# Thu tu fallback mong muon (sau Workers AI — vi vn-stock chinh la Workers AI).
DESIRED_FALLBACK = [
    "vn-stock-cerebras",
    "vn-stock-fosta-sol", "vn-stock-fosta-astra", "vn-stock-fosta-luna",
    "vn-stock-fosta2-sol", "vn-stock-fosta2-astra", "vn-stock-fosta2-luna",
    "vn-stock-deepseek", "vn-stock-glm",
]


def main():
    import yaml
    d = sys.argv[1]
    start_args = sys.argv[2:] or ["bash", os.path.join(d, "start.sh")]
    cfg = os.path.join(d, "config.yaml")
    data = yaml.safe_load(open(cfg))
    models = {m["model_name"]: m for m in data.get("model_list", [])}
    changed = False

    # 1. vn-stock -> Workers AI.
    vn = models.get("vn-stock")
    if vn is not None:
        cur = vn.get("litellm_params", {})
        if cur.get("model") != WORKERSAI_PARAMS["model"] or \
                cur.get("api_base") != API_BASE:
            import shutil
            shutil.copy(cfg, cfg + ".pre-reorder-wai")
            vn["litellm_params"] = dict(WORKERSAI_PARAMS)
            changed = True
            print("da doi vn-stock -> Workers AI")
        else:
            print("vn-stock da la Workers AI")
    else:
        print("WARN: khong thay model vn-stock trong config")
        return 1

    # 2. Sap lai fallback cua vn-stock.
    rs = data.setdefault("router_settings", {})
    fb = rs.setdefault("fallbacks", [])
    have = set(models.keys())
    want = [m for m in DESIRED_FALLBACK if m in have]
    for rule in fb:
        if isinstance(rule, dict) and "vn-stock" in rule:
            if rule["vn-stock"] != want:
                rule["vn-stock"] = want
                changed = True
                print("da sap lai fallback vn-stock:", want)
            else:
                print("fallback vn-stock da dung thu tu")
            break
    else:
        fb.append({"vn-stock": want})
        changed = True
        print("da them fallback vn-stock:", want)

    if changed:
        with open(cfg, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    else:
        print("khong co thay doi nao")

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
    body = json.dumps({"model": "vn-stock",
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
        print("vn-stock tra loi:", txt[:60])
        print("model dung:", out.get("model"))
        print("TEST OK")
    except Exception as e:
        print("WARN: goi vn-stock loi:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
