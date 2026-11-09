#!/usr/bin/env python3
"""Them model vn-stock vao config LiteLLM dang chay tren may (port 4000).
- Doc config.yaml hien tai, them 4 model vn-stock (cerebras/deepseek/glm/vn-stock)
  vao model_list + them fallback rules vao router_settings.fallbacks.
- Chi them neu chua co (idempotent — chay lai khong trung).
- Backup config cu thanh config.yaml.pre-vnstock.
- Khoi dong lai LiteLLM bang start.sh cua may (de no doc config moi).
- Kiem tra /health/liveliness + goi thu model vn-stock (nho, max_tokens=5).
Dung: python3 add_vnstock.py <DIR_LITELLM> (vd /home/agentuser/litellm)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

VN_MODELS = [
    {"model_name": "vn-stock-cerebras",
     "litellm_params": {"model": "openai/gpt-oss-120b",
                        "api_base": "https://api.cerebras.ai/v1",
                        "api_key": "os.environ/CEREBRAS_API_KEY", "timeout": 60}},
    {"model_name": "vn-stock-deepseek",
     "litellm_params": {"model": "openai/deepseek-v4.1-flash-free",
                        "api_base": "https://direct.beatapi.io/v1",
                        "api_key": "os.environ/BEATAPI_API_KEY", "timeout": 60}},
    {"model_name": "vn-stock-glm",
     "litellm_params": {"model": "openai/glm-5.3-flash-free",
                        "api_base": "https://direct.beatapi.io/v1",
                        "api_key": "os.environ/BEATAPI_API_KEY", "timeout": 60}},
    {"model_name": "vn-stock",
     "litellm_params": {"model": "openai/gpt-oss-120b",
                        "api_base": "https://api.cerebras.ai/v1",
                        "api_key": "os.environ/CEREBRAS_API_KEY", "timeout": 60}},
]
VN_FALLBACKS = [
    {"vn-stock": ["vn-stock-cerebras", "vn-stock-deepseek", "vn-stock-glm"]},
    {"vn-stock-cerebras": ["vn-stock-deepseek", "vn-stock-glm"]},
    {"vn-stock-deepseek": ["vn-stock-glm", "vn-stock-cerebras"]},
    {"vn-stock-glm": ["vn-stock-cerebras", "vn-stock-deepseek"]},
]


def main():
    import yaml
    d = sys.argv[1]
    cfg = os.path.join(d, "config.yaml")
    data = yaml.safe_load(open(cfg))
    have = {m["model_name"] for m in data.get("model_list", [])}
    added = [m for m in VN_MODELS if m["model_name"] not in have]
    if added:
        import shutil
        shutil.copy(cfg, cfg + ".pre-vnstock")
        data.setdefault("model_list", []).extend(added)
        rs = data.setdefault("router_settings", {})
        fb = rs.setdefault("fallbacks", [])
        have_fb = {list(x.keys())[0] for x in fb if isinstance(x, dict)}
        for rule in VN_FALLBACKS:
            if list(rule.keys())[0] not in have_fb:
                fb.append(rule)
        with open(cfg, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        print(f"them {len(added)} model vn-stock + fallback; backup .pre-vnstock")
    else:
        print("vn-stock da co trong config, khong them nua")

    # Khoi dong lai LiteLLM.
    subprocess.run(["bash", os.path.join(d, "start.sh")],
                   cwd=d, capture_output=True, timeout=60)
    print("da goi start.sh (litellm dang khoi dong lai)")
    for _ in range(12):
        time.sleep(5)
        try:
            with urllib.request.urlopen(
                    "http://localhost:4000/health/liveliness", timeout=5) as r:
                if r.status == 200:
                    print("health OK — litellm da len")
                    break
        except Exception:
            pass
    else:
        print("WARN: health chua len sau 60s — kiem tra proxy.log")
        return 1
    # Goi thu model vn-stock (nho).
    master = open(os.path.join(d, ".master_key")).read().strip()
    body = json.dumps({"model": "vn-stock",
                       "messages": [{"role": "user", "content": "Tra loi dung 1 tu: ok"}],
                       "max_tokens": 5}).encode()
    req = urllib.request.Request(
        "http://localhost:4000/v1/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + master)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out = json.load(r)
        txt = out["choices"][0]["message"]["content"]
        print("vn-stock tra loi:", txt[:80])
        print("TEST OK")
    except Exception as e:
        print("WARN: goi vn-stock loi:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
