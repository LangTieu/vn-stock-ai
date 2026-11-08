#!/usr/bin/env python3
"""Drive a Colab notebook from InstaBox via CDP — no browser task, no tokens.

Prereq: the InstaBox desktop Chromium profile (~/.config/chromium) must hold
a Google session (one-time sign-in on the InstaBox desktop). Drive mount auth
is skipped: the P0 notebooks embed their data, and training notebooks will
checkpoint to Drive via the folder the account already sees.

Usage: python3 colab_driver.py <notebook-url> <result-json-path> [timeout_s]
Prints progress lines; writes {"ok": bool, "cells": [...], "outputs": {...}}
to the result path. Read it back with: ibctl exec <machine> --cmd "cat <path>"
"""
import json
import os
import pwd
import subprocess
import sys
import time
import urllib.request

import websocket

# Home that: passwd entry, NOT $HOME — ibctl exec sets HOME=/home/hatch
# while the real home (and the desktop Chromium profile) is /data/home.
PROFILE = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".config/chromium")
PORT = 9333  # 9222 is taken by ZCode's Electron DevTools on this machine


def get_ws_url():
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"http://localhost:{PORT}/json/list", timeout=2) as r:
                targets = json.load(r)
            for t in targets:
                if t.get("type") == "page":
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(1)
    return None


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=60)
        self.mid = 0

    def send(self, method, params=None):
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg

    def js(self, expr):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True})
        return r.get("result", {}).get("result", {}).get("value")


def main():
    url, out_path = sys.argv[1], sys.argv[2]
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 1800
    proc = subprocess.Popen(
        ["chromium", "--headless=new", f"--remote-debugging-port={PORT}",
         "--remote-allow-origins=*",
         "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
         f"--user-data-dir={PROFILE}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = {"ok": False, "cells": [], "outputs": {}, "error": ""}
    try:
        ws_url = get_ws_url()
        if not ws_url:
            result["error"] = "no CDP target (desktop Chromium may hold the profile)"
            return result
        c = CDP(ws_url)
        c.send("Page.enable")
        c.send("Runtime.enable")
        c.send("Page.navigate", {"url": url})
        # Wait for the Colab app (not the sign-in page)
        signed_in = False
        for _ in range(12):
            time.sleep(5)
            body = c.js("document.body ? document.body.innerText.slice(0, 300) : ''") or ""
            if "Sign in" in body or "Đăng nhập" in body:
                result["error"] = "Google sign-in required in the InstaBox Chromium profile"
                return result
            if "Run all" in body or "Runtime" in body:
                signed_in = True
                break
        if not signed_in:
            result["error"] = "Colab UI did not appear"
            return result
        # Click Runtime menu -> Run all
        clicked = c.js("""(() => {
          const btns = [...document.querySelectorAll('button, [role=button]')];
          const runtime = btns.find(b => (b.innerText || '').trim() === 'Runtime');
          if (!runtime) return 'no-runtime-menu';
          runtime.click();
          return 'runtime-clicked';
        })()""")
        time.sleep(2)
        ran = c.js("""(() => {
          const items = [...document.querySelectorAll('[role=menuitem], [role=menuitemradio], li, div')];
          const runAll = items.find(el => (el.innerText || '').trim().startsWith('Run all'));
          if (!runAll) return 'no-run-all-item';
          runAll.click();
          return 'run-all-clicked';
        })()""")
        # Confirm "Run anyway" if it appears (GitHub notebook warning)
        time.sleep(2)
        c.js("""(() => {
          const btns = [...document.querySelectorAll('button')];
          const ok = btns.find(b => (b.innerText || '').trim() === 'Run anyway');
          if (ok) ok.click();
          return ok ? 'confirmed' : 'no-confirm';
        })()""")
        print(f"runtime={clicked} runall={ran}", flush=True)
        # Poll until no cell is executing
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(15)
            state = c.js("""(() => {
              const running = document.querySelectorAll('.cell-executing, [class*=executing]').length;
              const outputs = [...document.querySelectorAll('.output')].map(o => o.innerText);
              return {running, nOutputs: outputs.length};
            })()""") or {}
            print(f"poll running={state.get('running')} outputs={state.get('nOutputs')}", flush=True)
            if state.get("running") == 0 and state.get("nOutputs", 0) > 0:
                break
        # Extract outputs per cell
        data = c.js("""(() => {
          const cells = [...document.querySelectorAll('.cell')];
          return cells.map((cell, i) => {
            const out = cell.querySelector('.output');
            const err = cell.querySelector('.output-error, .error');
            return {i, output: out ? out.innerText : '', error: err ? err.innerText : ''};
          });
        })()""") or []
        result["cells"] = data
        result["outputs"] = {str(d["i"]): d["output"] for d in data if d.get("output")}
        result["ok"] = any(d.get("output") for d in data)
        return result
    finally:
        with open(out_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: colab_driver.py <notebook-url> <result-json-path> [timeout_s]")
        sys.exit(2)
    res = main()
    print(json.dumps({"ok": res["ok"], "error": res.get("error", ""),
                      "n_cells": len(res["cells"])}, ensure_ascii=False))
    sys.exit(0 if res["ok"] else 1)
