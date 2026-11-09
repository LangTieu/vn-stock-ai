#!/usr/bin/env python3
"""Doi master key LiteLLM thanh key chung (doc tu file, khong ghi gia tri ra log).
- Backup .master_key cu -> .master_key.<timestamp>.bak
- Chep key moi tu file nguon (arg 2) -> .master_key (0600)
- Kill process litellm cu, chay start.sh <DIR>, doi health, test /v1/models
  bang key moi.
Dung: <venv python> swap_master_key.py <DIR_LITELLM> <KEY_FILE> [START_CMD...]
"""
import os
import subprocess
import sys
import time
import urllib.request

def main():
    d = sys.argv[1]
    key_file = sys.argv[2]
    start_args = sys.argv[3:] or ["bash", os.path.join(d, "start.sh"), d]
    key = open(key_file).read().strip()
    if not key:
        print("ERR: key file rong")
        return 1
    import shutil
    old = os.path.join(d, ".master_key")
    if os.path.exists(old):
        bak = old + ".%d.bak" % int(time.time())
        shutil.copy(old, bak)
        print("da backup key cu:", bak)
    with open(old, "w") as f:
        f.write(key + "\n")
    os.chmod(old, 0o600)
    print("da ghi key moi (0600), do dai:", len(key))
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
    req = urllib.request.Request("http://localhost:4000/v1/models")
    req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            import json
            data = json.load(r)
        print("models:", len(data.get("data", [])))
        print("TEST OK (key moi xac thuc duoc)")
    except Exception as e:
        print("WARN: /v1/models voi key moi loi:", e)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
