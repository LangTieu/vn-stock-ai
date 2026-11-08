#!/usr/bin/env python3
"""colabctl — CLI bam Run tren Google Colab tu terminal.

Khong dung API (Colab khong co), khong dung Playwright: lai Chromium san co
tren may bang CDP (Chrome DevTools Protocol), bam nut Run all tren giao dien
Colab giong nhu nguoi dung. Chi can dang nhap Google 1 lan trong profile
Chromium cua may (desktop) — session giu lai, cac lan sau chay khong can tay.

Yeu cau: python3 + module `websocket` + binary `chromium`.
Tren InstaBox: ca 3 deu co san; cong CDP 9333 (9222 da bi ZCode chiem).

Usage:
  colabctl probe [--json]
      Kiem tra Colab co thay tai khoan Google dang nhap khong.
  colabctl run <notebook-url> [--timeout 1800] [--out result.json] [--json]
      Mo notebook, bam Run all, doi chay xong, ghi output tung cell ra file
      JSON. Tra 0 neu co output, 1 neu loi (kem ly do trong file ket qua).

Vi du:
  colabctl probe
  colabctl run https://colab.research.google.com/github/LangTieu/vn-stock-ai/blob/main/notebooks/p0_qwen15b_vcb_real.ipynb
"""
import argparse
import json
import os
import pwd
import subprocess
import sys
import time
import urllib.request

# `websocket` is imported lazily inside CDP so `--help` works on machines
# without websocket-client installed (the CLI runs on InstaBox, where it is).

# Home that: passwd entry, NOT $HOME — ibctl exec sets HOME=/home/hatch
# while the real home (and the desktop Chromium profile) is /data/home.
PROFILE = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".config/chromium")
PORT = 9333  # 9222 is taken by ZCode's Electron DevTools on this machine
COLAB_HOME = "https://colab.research.google.com/"


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
    """Minimal CDP client over websocket."""

    def __init__(self, ws_url):
        import websocket  # noqa: PLC0415 — lazy: only needed when driving a browser

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

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


class Browser:
    """Headless Chromium on the desktop profile, driven over CDP."""

    def __enter__(self):
        self.proc = subprocess.Popen(
            ["chromium", "--headless=new", f"--remote-debugging-port={PORT}",
             "--remote-allow-origins=*",
             "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
             f"--user-data-dir={PROFILE}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = get_ws_url()
        if not ws_url:
            self.proc.terminate()
            raise RuntimeError("no CDP target (desktop Chromium may hold the profile)")
        self.cdp = CDP(ws_url)
        self.cdp.send("Page.enable")
        self.cdp.send("Runtime.enable")
        return self.cdp

    def __exit__(self, *exc):
        try:
            self.cdp.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def _body_text(cdp):
    return cdp.js("document.body ? document.body.innerText.slice(0, 400) : ''") or ""


def _signed_in(cdp):
    body = _body_text(cdp)
    return "Sign in" not in body and "Đăng nhập" not in body


def cmd_probe(args):
    with Browser() as cdp:
        cdp.send("Page.navigate", {"url": COLAB_HOME})
        time.sleep(15)
        title = cdp.js("document.title") or ""
        body = _body_text(cdp)
        result = {"signed_in": _signed_in(cdp), "title": title,
                  "note": "body[:400]: " + body.replace("\n", " | ")[:400]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"signed_in: {result['signed_in']} | title: {result['title']}")
        if not result["signed_in"]:
            print("Chua dang nhap Google trong profile Chromium cua may — "
                  "dang nhap 1 lan tren desktop roi chay lai.")
    return 0 if result["signed_in"] else 1


def cmd_run(args):
    result = {"ok": False, "url": args.url, "cells": [], "outputs": {}, "error": ""}
    try:
        with Browser() as cdp:
            cdp.send("Page.navigate", {"url": args.url})
            # Wait for the Colab app (not the sign-in page)
            ready = False
            for _ in range(12):
                time.sleep(5)
                body = _body_text(cdp)
                if not _signed_in(cdp):
                    result["error"] = ("Google sign-in required in the Chromium profile "
                                       "(dang nhap 1 lan tren desktop roi chay lai)")
                    break
                if "Run all" in body or "Runtime" in body:
                    ready = True
                    break
            if result["error"]:
                return _finish(args, result)
            if not ready:
                result["error"] = "Colab UI did not appear"
                return _finish(args, result)
            # Runtime menu -> Run all
            cdp.js("""(() => {
              const btns = [...document.querySelectorAll('button, [role=button]')];
              const runtime = btns.find(b => (b.innerText || '').trim() === 'Runtime');
              if (runtime) runtime.click();
              return true;
            })()""")
            time.sleep(2)
            cdp.js("""(() => {
              const items = [...document.querySelectorAll('[role=menuitem], [role=menuitemradio], li, div')];
              const runAll = items.find(el => (el.innerText || '').trim().startsWith('Run all'));
              if (runAll) runAll.click();
              return true;
            })()""")
            # Confirm "Run anyway" if it appears (GitHub notebook warning)
            time.sleep(2)
            cdp.js("""(() => {
              const btns = [...document.querySelectorAll('button')];
              const ok = btns.find(b => (b.innerText || '').trim() === 'Run anyway');
              if (ok) ok.click();
              return true;
            })()""")
            print("Run all clicked, waiting for cells to finish...", flush=True)
            start = time.time()
            while time.time() - start < args.timeout:
                time.sleep(15)
                state = cdp.js("""(() => {
                  const running = document.querySelectorAll('.cell-executing, [class*=executing]').length;
                  const outputs = [...document.querySelectorAll('.output')].map(o => o.innerText);
                  return {running, nOutputs: outputs.length};
                })()""") or {}
                print(f"  running={state.get('running')} outputs={state.get('nOutputs')}", flush=True)
                if state.get("running") == 0 and state.get("nOutputs", 0) > 0:
                    break
            cells = cdp.js("""(() => {
              const cells = [...document.querySelectorAll('.cell')];
              return cells.map((cell, i) => {
                const out = cell.querySelector('.output');
                const err = cell.querySelector('.output-error, .error');
                return {i, output: out ? out.innerText : '', error: err ? err.innerText : ''};
              });
            })()""") or []
            result["cells"] = cells
            result["outputs"] = {str(d["i"]): d["output"] for d in cells if d.get("output")}
            result["ok"] = any(d.get("output") for d in cells)
            if not result["ok"]:
                result["error"] = "no cell output captured (timeout or all cells failed)"
    except Exception as e:  # noqa: BLE001 — report as result, not traceback
        result["error"] = f"{type(e).__name__}: {e}"
    return _finish(args, result)


def _finish(args, result):
    with open(args.out, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    if args.json:
        print(json.dumps({"ok": result["ok"], "error": result.get("error", ""),
                          "out": args.out}, ensure_ascii=False))
    else:
        print(f"ok={result['ok']} | out={args.out}")
        if result.get("error"):
            print(f"error: {result['error']}")
        elif result["outputs"]:
            print("--- outputs ---")
            for i, text in result["outputs"].items():
                print(f"[cell {i}]\n{text}\n")
    return 0 if result["ok"] else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="colabctl", description="CLI bam Run tren Google Colab.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("probe", help="kiem tra dang nhap Google tren Colab")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_probe)
    pr = sub.add_parser("run", help="mo notebook, bam Run all, gom output")
    pr.add_argument("url", help="URL notebook Colab (dang github)")
    pr.add_argument("--timeout", type=int, default=1800, help="cho toi da (giay)")
    pr.add_argument("--out", default="colab_result.json", help="file ket qua JSON")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_run)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
