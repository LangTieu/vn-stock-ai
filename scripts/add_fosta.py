#!/usr/bin/env python3
"""Them leg FOSTA (tam) vao config LiteLLM tren may.
- Them 3 model: vn-stock-fosta-sol (gpt-6.1-sol), vn-stock-fosta-astra
  (gpt-6-astra, manh nhat), vn-stock-fosta-luna (gpt-6-luna, re nhat).
- api_base https://codex.fosta.app/v1, key tu os.environ/FOSTA_API_KEY.
- Them FOSTA vao fallback cua vn-stock (sau cerebras, truoc deepseek).
- Cap nhat start.sh de export FOSTA_API_KEY (tu file 0600).
- Chi them neu chua co (idempotent). Backup config cu.
- Khoi dong lai LiteLLM + test leg sol.
Dung: <venv python> add_fosta.py <DIR_LITELLM> [START_CMD...]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

API_BASE = "https://codex.fosta.app/v1"

FOSTA_MODELS = [
    {"model_name": "vn-stock-fosta-sol",
     "litellm_params": {"model": "openai/gpt-6.1-sol",
                        "api_base": API_BASE,
                        "api_key": "os.environ/FOSTA_API_KEY", "timeout": 60}},
    {"model_name": "vn-stock-fosta-astra",
     "litellm_params": {"model": "openai/gpt-6-astra",
                        "api_base": API_BASE,
                        "api_key": "os.environ/FOSTA_API_KEY", "timeout": 60}},
    {"model_name": "vn-stock-fosta-luna",
     "litellm_params": {"model": "openai/gpt-6-luna",
                        "api_base": API_BASE,
                        "api_key": "os.environ/FOSTA_API_KEY", "timeout": 60}},
]


def update_start_sh(d):
    p = os.path.join(d, "start.sh")
    txt = open(p).read()
    if "FOSTA_API_KEY" in txt:
        print("start.sh da co FOSTA, khong sua")
        return
    lines = txt.splitlines()
    out = []
    inserted = False
    for ln in lines:
        if (not inserted) and ln.strip().startswith("nohup"):
            out.append('f="$DIR/.fosta_api_key"')
            out.append('[ -f "$f" ] && export FOSTA_API_KEY="$(cat "$f")"')
            inserted = True
        out.append(ln)
    if not inserted:
        # start.sh kieu moi (vong for): them FOSTA_API_KEY vao danh sach.
        if "FOSTA_API_KEY" not in txt:
            txt = txt.replace(
                "CLOUDFLARE_API_TOKEN",
                "CLOUDFLARE_API_TOKEN FOSTA_API_KEY")
        open(p, "w").write(txt)
        print("start.sh (kieu moi) da them FOSTA_API_KEY vao vong for")
        return
    open(p, "w").write("\n".join(out) + "\n")
    print("start.sh da them FOSTA export")


def main():
    import yaml
    d = sys.argv[1]
    start_args = sys.argv[2:] or ["bash", os.path.join(d, "start.sh")]
    cfg = os.path.join(d, "config.yaml")
    data = yaml.safe_load(open(cfg))
    have = {m["model_name"] for m in data.get("model_list", [])}
    added = [m for m in FOSTA_MODELS if m["model_name"] not in have]
    if added:
        import shutil
        shutil.copy(cfg, cfg + ".pre-fosta")
        data.setdefault("model_list", []).extend(added)
        rs = data.setdefault("router_settings", {})
        fb = rs.setdefault("fallbacks", [])
        for rule in fb:
            if isinstance(rule, dict) and "vn-stock" in rule:
                chain = rule["vn-stock"]
                # Chen FOSTA sau cerebras (neu co), khong thi chen dau.
                for name in ["vn-stock-fosta-sol", "vn-stock-fosta-astra",
                             "vn-stock-fosta-luna"]:
                    if name not in chain:
                        try:
                            i = chain.index("vn-stock-cerebras") + 1
                        except ValueError:
                            i = 0
                        chain.insert(i, name)
                        i += 1
        with open(cfg, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        print(f"da them {len(added)} model FOSTA + fallback")
    else:
        print("FOSTA da co trong config")
    update_start_sh(d)

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
    body = json.dumps({"model": "vn-stock-fosta-sol",
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
        print("fosta-sol tra loi:", txt[:60])
        print("TEST OK")
    except Exception as e:
        print("WARN: goi fosta-sol loi:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
