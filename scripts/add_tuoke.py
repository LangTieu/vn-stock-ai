#!/usr/bin/env python3
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

FALLBACKS = [
    "vn-stock-tuoke-6.1-sol", "vn-stock-tuoke-6-sol", "vn-stock-cerebras",
    "vn-stock-fosta-sol", "vn-stock-fosta-astra", "vn-stock-fosta-luna",
    "vn-stock-fosta2-sol", "vn-stock-fosta2-astra", "vn-stock-fosta2-luna",
    "vn-stock-deepseek", "vn-stock-glm", "vn-stock-itera-qwen",
]
LEGS = [
    ("vn-stock-tuoke-6.1-sol", "openai/gpt-6.1-sol"),
    ("vn-stock-tuoke-6-sol", "openai/gpt-6-sol"),
]


def update_config(config_path):
    config_path = Path(config_path)
    config = yaml.safe_load(config_path.read_text())
    models = config.setdefault("model_list", [])
    for name, model in LEGS:
        entry = {
            "model_name": name,
            "litellm_params": {
                "model": model,
                "api_base": "https://tuokeapi.com/v1",
                "api_key": "os.environ/TUOKE_API_KEY",
                "timeout": 300,
            },
        }
        for i, old in enumerate(models):
            if old.get("model_name") == name:
                models[i] = entry
                break
        else:
            models.append(entry)
    fallbacks = config.setdefault("router_settings", {}).setdefault("fallbacks", [])
    fallbacks[:] = [row for row in fallbacks if not any(k in ("vn-stock", *[x[0] for x in LEGS]) for k in row)]
    fallbacks.insert(0, {"vn-stock": FALLBACKS})
    fallbacks.extend([
        {"vn-stock-tuoke-6.1-sol": ["vn-stock-tuoke-6-sol"]},
        {"vn-stock-tuoke-6-sol": ["vn-stock-tuoke-6.1-sol"]},
    ])
    temp = config_path.with_suffix(config_path.suffix + ".tuoke-tmp")
    temp.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    os.chmod(temp, config_path.stat().st_mode & 0o777)
    temp.replace(config_path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("litellm_dir")
    p.add_argument("--config", default="")
    p.add_argument("--restart", action="store_true")
    a = p.parse_args()
    root = Path(a.litellm_dir).resolve()
    cfg = Path(a.config).resolve() if a.config else root / "config.yaml"
    key_file = root / ".tuoke_api_key"
    if not key_file.is_file():
        raise SystemExit(f"missing key file: {key_file}")
    update_config(cfg)
    start = root / "start.sh"
    text = start.read_text()
    export_line = 'f="$DIR/.tuoke_api_key"\n[ -f "$f" ] && export TUOKE_API_KEY="$(cat "$f")"\n'
    if 'export TUOKE_API_KEY=' not in text:
        anchor = 'f="$DIR/.fosta_api_key"\n'
        if anchor not in text:
            raise SystemExit("start.sh FOSTA export anchor not found")
        text = text.replace(anchor, export_line + anchor, 1)
        start.write_text(text)
    if a.restart:
        proc = subprocess.run(["ss", "-ltnp", "sport", "=", ":4000"], capture_output=True, text=True)
        # Identify only LiteLLM PIDs from process listing and terminate the process bound to this proxy.
        ps = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, check=True).stdout
        pids = []
        for line in ps.splitlines()[1:]:
            fields = line.strip().split(None, 1)
            if len(fields) == 2 and "litellm" in fields[1] and str(cfg) in fields[1]:
                pids.append(int(fields[0]))
        for pid in pids:
            os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 20
        while time.time() < deadline and any(Path(f"/proc/{pid}").exists() for pid in pids):
            time.sleep(0.5)
        subprocess.run(["bash", str(start), str(root)], check=True)
        print("restart: started via start.sh")
    print(f"updated config: {cfg}")
    print(f"updated startup export: {start}")


if __name__ == "__main__":
    main()
