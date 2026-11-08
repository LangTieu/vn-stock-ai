#!/usr/bin/env python3
"""vncolab — CLI cua minh de chay code tren Google Colab T4 (free), khong can trinh duyet.

Kien truc mo theo CLI chinh thuc cua Google (googlecolab/google-colab-cli,
Apache-2.0) — cung endpoint assign, cung giao thuc kernel — nhung sua lai cho
hop voi minh:
  * Auth: remote copy-paste flow (mo link bang dien thoai, paste code). Token
    cat vao file 0600 (~/.config/vncolab/token.json), KHONG dung OS keyring
    (may headless khong co keyring nen CLI goc hoi lai moi lan).
  * Auth tach 2 buoc (auth-url / auth-code) de chay duoc tren may remote
    (InstaBox) noi khong go truc tiep duoc stdin.
  * POST assign gui kem Content-Length: 0 + retry ca loi transport
    (ProxyError/ConnectionError) — CLI goc chi retry ReadTimeout/502-504.
  * Chay notebook: bo qua cell drive.mount (can tuong tac) vi du lieu cua
    minh da nhung san trong notebook.

Dung:
  vncolab auth-url                  in URL phe duyet, luu flow tam
  vncolab auth-code <code>          doi code lay token, luu file 0600
  vncolab auth                      1 tien trinh: in URL, doc code tu stdin
  vncolab usage                     so du compute units (GET, khong cap may)
  vncolab sessions                  liet ke runtime dang chay
  vncolab new [--gpu T4]            cap runtime moi, in endpoint
  vncolab run <file.py|nb.ipynb> [--gpu T4] [--keep]
                                    cap may moi, chay file, lay output, tat may
  vncolab stop [name]               tat runtime (giai phong may)

Bien moi truong: VNCOLAB_HOME (mac dinh ~/.config/vncolab).
"""
import argparse
import json
import os
import sys
import time
import uuid
from urllib.parse import urljoin

# OAuth client cong khai kem theo CLI chinh thuc (googlecolab/google-colab-cli,
# Apache-2.0, file src/colab_cli/oauth_config.json). Day la client public cua
# Google Cloud SDK — khong phai secret rieng. Redirect URI
# https://sdk.cloud.google.com/applicationdefaultauthcode.html chi dang ky cho
# client nay, client khac se bi redirect_uri_mismatch.
CLIENT_CONFIG = {
    "installed": {
        "client_id": "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
        "project_id": "colab-cli",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "d-FL95Q19q7MQmFpd7hHD0Ty",
        "redirect_uris": ["http://localhost"],
    }
}
REMOTE_REDIRECT_URI = "https://sdk.cloud.google.com/applicationdefaultauthcode.html"
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/colaboratory",
    "https://www.googleapis.com/auth/drive.file",
]

COLAB_DOMAIN = "https://colab.research.google.com"
TUN = "/tun/m"


def _home():
    return os.environ.get("VNCOLAB_HOME") or os.path.expanduser("~/.config/vncolab")


def _token_path():
    return os.path.join(_home(), "token.json")


def _flow_path():
    return os.path.join(_home(), "flow.json")


def _sessions_path():
    return os.path.join(_home(), "sessions.json")


def _ensure_home():
    os.makedirs(_home(), exist_ok=True)


def _save_0600(path, data):
    _ensure_home()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)


# ---------------------------------------------------------------- auth
def _make_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
    flow.redirect_uri = REMOTE_REDIRECT_URI
    return flow


def cmd_auth_url(args):
    flow = _make_flow()
    auth_url, _ = flow.authorization_url(
        prompt="consent", token_usage="remote", access_type="offline")
    _save_0600(_flow_path(), {
        "state": flow.state,
        "code_verifier": getattr(flow, "code_verifier", None),
    })
    print(auth_url)
    print("Mo link tren dien thoai, chon tai khoan Google, phe duyet, "
          "roi chay: vncolab auth-code <code>", file=sys.stderr)
    return 0


def _exchange_and_save(code):
    flow = _make_flow()
    if os.path.exists(_flow_path()):
        with open(_flow_path()) as f:
            saved = json.load(f)
        # Khoi phuc PKCE verifier + state de doi code (2 tien trinh rieng).
        if saved.get("state"):
            flow.state = saved["state"]
        if saved.get("code_verifier"):
            flow.code_verifier = saved["code_verifier"]
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_0600(_token_path(), json.loads(creds.to_json()))
    try:
        os.remove(_flow_path())
    except OSError:
        pass
    print("token saved to " + _token_path(), file=sys.stderr)
    return creds


def cmd_auth_code(args):
    _exchange_and_save(args.code)
    return 0


def cmd_auth(args):
    # 1 tien trinh (khi stdin go truc tiep duoc): in URL, doc code, doi token.
    flow = _make_flow()
    auth_url, _ = flow.authorization_url(
        prompt="consent", token_usage="remote", access_type="offline")
    print("Mo link nay tren bat ky trinh duyet nao:\n", file=sys.stderr)
    print("  " + auth_url + "\n", file=sys.stderr)
    code = input("Nhap code phe duyet: ").strip()
    _exchange_and_save(code)
    return 0


def load_credentials():
    """Doc token file, refresh neu het han. Tra google.auth Credentials."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    path = _token_path()
    if not os.path.exists(path):
        print("Chua co token. Chay: vncolab auth-url  roi  vncolab auth-code <code>",
              file=sys.stderr)
        sys.exit(2)
    with open(path) as f:
        info = json.load(f)
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_0600(path, json.loads(creds.to_json()))
        else:
            print("Token het han va khong refresh duoc. Chay lai auth.",
                  file=sys.stderr)
            sys.exit(2)
    return creds


def authorized_session():
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(load_credentials())


# ---------------------------------------------------------------- client
def uuid_to_web_safe_base64(uuid_val):
    s = str(uuid_val).replace("-", "_")
    return s + "." * (44 - len(s))


class ColabRequestError(Exception):
    pass


class TooManyAssignmentsError(Exception):
    pass


class Client:
    def __init__(self, session):
        self.session = session

    def _req(self, method, url, headers=None, data=None, timeout=120):
        h = {"Accept": "application/json",
             "X-Colab-Client-Agent": "vncolab"}
        if headers:
            h.update(headers)
        # POST khong body van gui Content-Length: 0 (mot so proxy/server
        # tra 411 Length Required neu thieu).
        kwargs = {"headers": h, "timeout": timeout}
        if method == "POST":
            kwargs["data"] = b"" if data is None else data
        import requests as _rq

        last_err = None
        for attempt in range(4):
            try:
                resp = self.session.request(method, url, **kwargs)
            except (_rq.exceptions.ProxyError, _rq.exceptions.ConnectionError,
                    _rq.exceptions.ReadTimeout) as e:
                last_err = e
                time.sleep(5 * (2 ** attempt))
                continue
            if resp.status_code in (502, 503, 504) and attempt < 3:
                time.sleep(5 * (2 ** attempt))
                continue
            if not resp.ok:
                raise ColabRequestError(
                    f"{method} {url} -> {resp.status_code} {resp.reason}: "
                    f"{resp.text[:300]}")
            return resp
        raise ColabRequestError(f"{method} {url} failed after retries: {last_err}")

    def _assign_url(self, nbh, variant=None, accelerator=None, shape=None):
        url = urljoin(COLAB_DOMAIN, f"{TUN}/assign")
        params = {"nbh": uuid_to_web_safe_base64(nbh), "authuser": "0"}
        if variant:
            params["variant"] = variant
        if accelerator:
            params["accelerator"] = accelerator
        if shape == "hm":
            params["shape"] = "hm"
        from urllib.parse import urlencode

        return url + "?" + urlencode(params)

    def assign(self, accelerator=None, variant=None, shape=None):
        nbh = uuid.uuid4()
        url = self._assign_url(nbh, variant, accelerator, shape)
        # GET: lay token XSRF, hoac tra ve assignment co san.
        resp = self._req("GET", url)
        body = resp.text
        if body.startswith(")]}'\n"):
            body = body[5:]
        data = json.loads(body) if body.strip() else {}
        if "endpoint" in data and "runtimeProxyInfo" in data:
            return data
        token = data.get("token")
        if not token:
            raise ColabRequestError(f"GET assign tra ve khong co token: {body[:200]}")
        # POST: cap may that.
        resp = self._req("POST", url,
                         headers={"X-Goog-Colab-Token": token})
        body = resp.text
        if body.startswith(")]}'\n"):
            body = body[5:]
        return json.loads(body)

    def list_assignments(self):
        resp = self._req("GET", urljoin(COLAB_DOMAIN, f"{TUN}/assignments")
                         + "?authuser=0")
        body = resp.text
        if body.startswith(")]}'\n"):
            body = body[5:]
        return json.loads(body).get("assignments", [])

    def unassign(self, endpoint):
        url = (urljoin(COLAB_DOMAIN, f"{TUN}/unassign/{endpoint}")
               + "?authuser=0")
        resp = self._req("GET", url)
        body = resp.text
        if body.startswith(")]}'\n"):
            body = body[5:]
        token = json.loads(body).get("token", "")
        self._req("POST", url, headers={"X-Goog-Colab-Token": token})

    def ccu_info(self):
        resp = self._req("GET", urljoin(COLAB_DOMAIN, f"{TUN}/ccu-info")
                         + "?authuser=0")
        body = resp.text
        if body.startswith(")]}'\n"):
            body = body[5:]
        return json.loads(body)


# ---------------------------------------------------------------- runtime
def _kernel_client(url, token):
    import jupyter_kernel_client

    if hasattr(jupyter_kernel_client, "ColabKernelClient"):
        cls, kw = jupyter_kernel_client.ColabKernelClient, "proxy_token"
    elif hasattr(jupyter_kernel_client, "KernelClient"):
        cls, kw = jupyter_kernel_client.KernelClient, "token"
    else:
        cls, kw = jupyter_kernel_client.JupyterKernelClient, "token"
    client = cls(
        server_url=url, **{kw: token},
        client_kwargs={
            "subprotocol": jupyter_kernel_client.JupyterSubprotocol.DEFAULT,
            "extra_params": {"colab-runtime-proxy-token": token},
        },
        headers={"X-Colab-Client-Agent": "vncolab",
                 "X-Colab-Runtime-Proxy-Token": token},
    )
    client._own_kernel = False
    client.start()
    return client


def execute_code(url, token, code, timeout=1800):
    """Chay 1 doan code tren kernel, tra list outputs (dicts kieu Jupyter)."""
    import queue

    kc = _kernel_client(url, token)
    try:
        mgr = kc._manager.client
        msg_id = mgr.execute(code, allow_stdin=False)
        outputs = []
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("khong co message nao tu kernel qua timeout")
            try:
                msg = mgr.get_iopub_msg(timeout=min(1.0, left))
            except queue.Empty:
                continue
            if msg["parent_header"].get("msg_id") != msg_id:
                continue
            mtype = msg["header"]["msg_type"]
            if mtype == "status" and msg["content"].get("execution_state") == "idle":
                break
            outputs.append(msg)
        reply = mgr.get_shell_msg(timeout=30)
        return outputs, reply
    finally:
        try:
            mgr.stop_channels()
            if mgr.kernel_socket:
                mgr.kernel_socket.close()
        except Exception:
            pass


def outputs_to_text(outputs):
    parts = []
    for msg in outputs:
        mtype = msg["header"]["msg_type"]
        c = msg["content"]
        if mtype == "stream":
            parts.append(c.get("text", ""))
        elif mtype in ("execute_result", "display_data"):
            data = c.get("data", {})
            if "text/plain" in data:
                parts.append(data["text/plain"])
            elif "text/html" in data:
                parts.append("[html output]")
            if "image/png" in data:
                parts.append("[image output]")
        elif mtype == "error":
            parts.append("".join(c.get("traceback", []))
                         or f"{c.get('ename')}: {c.get('evalue')}")
    return "".join(parts)


# ---------------------------------------------------------------- sessions
def _load_sessions():
    try:
        with open(_sessions_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_sessions(s):
    _ensure_home()
    with open(_sessions_path(), "w") as f:
        json.dump(s, f, indent=2)


# ---------------------------------------------------------------- commands
def cmd_usage(args):
    info = Client(authorized_session()).ccu_info()
    print(f"So du compute units: {info.get('currentBalance')}")
    print(f"Toc do tieu thu: {info.get('consumptionRateHourly')}/gio")
    print(f"Runtime dang chay: {info.get('assignmentsCount')}")
    return 0


def cmd_sessions(args):
    assigns = Client(authorized_session()).list_assignments()
    if not assigns:
        print("Khong co runtime nao dang chay.")
        return 0
    for a in assigns:
        rpi = a.get("runtimeProxyInfo", {})
        print(f"{a.get('endpoint')} | {a.get('accelerator')} | "
              f"shape={a.get('machineShape')} | proxy={rpi.get('url')}")
    return 0


def _variant_for(accelerator):
    if accelerator in ("T4", "L4", "A100", "H100", "G4"):
        return "GPU"
    if accelerator in ("V5E1", "V6E1"):
        return "TPU"
    return "DEFAULT"


def cmd_new(args):
    client = Client(authorized_session())
    res = client.assign(accelerator=args.gpu or None,
                        variant=_variant_for(args.gpu) if args.gpu else None)
    try:
        rpi = res["runtimeProxyInfo"]
        name = args.name or ("s-" + uuid.uuid4().hex[:6])
        sessions = _load_sessions()
        sessions[name] = {"endpoint": res["endpoint"],
                          "url": rpi["url"],
                          "token": rpi["token"],
                          "accelerator": res.get("accelerator")}
        _save_sessions(sessions)
    except Exception:
        # Phan hoi lac: may da cap nhung khong luu duoc session -> tat ngay.
        try:
            client.unassign(res["endpoint"])
        except Exception:
            pass
        raise
    print(f"session: {name}")
    print(f"endpoint: {res['endpoint']}")
    print(f"accelerator: {res.get('accelerator')}")
    print(f"proxy: {res['runtimeProxyInfo']['url']}")
    return 0


def _get_session(name):
    sessions = _load_sessions()
    if name:
        s = sessions.get(name)
        if not s:
            print(f"Khong co session '{name}'.", file=sys.stderr)
            sys.exit(2)
        return s
    if len(sessions) == 1:
        return next(iter(sessions.values()))
    print("Nhieu session, hay chon 1 bang -s NAME.", file=sys.stderr)
    sys.exit(2)


def cmd_stop(args):
    client = Client(authorized_session())
    sessions = _load_sessions()
    if args.name:
        names = [args.name]
    else:
        names = list(sessions.keys())
    for name in names:
        s = sessions.get(name)
        if not s:
            continue
        try:
            client.unassign(s["endpoint"])
            print(f"stopped {name} ({s['endpoint']})")
        except Exception as e:  # noqa: BLE001 — bao loi roi tiep tuc don dep
            print(f"khong tat duoc {name}: {e}", file=sys.stderr)
        sessions.pop(name, None)
    _save_sessions(sessions)
    return 0


def cmd_run(args):
    """Cap may moi, chay file .py hoac .ipynb, in output, tat may."""
    client = Client(authorized_session())
    accel = args.gpu or None
    res = client.assign(accelerator=accel,
                        variant=_variant_for(accel) if accel else None)
    # Moi thu sau assign() deu nam trong try/finally: crash o bat ky cho
    # nao cung tat may, khong de runtime mo coi chiem slot (free chi 1 may).
    endpoint = name = url = token = None
    ok = True
    result = {"ok": False, "accelerator": res.get("accelerator"), "cells": []}
    try:
        url = res["runtimeProxyInfo"]["url"]
        token = res["runtimeProxyInfo"]["token"]
        endpoint = res["endpoint"]
        print(f"runtime: {res.get('accelerator')} endpoint={endpoint}",
              file=sys.stderr)
        name = "run-" + uuid.uuid4().hex[:6]
        sessions = _load_sessions()
        sessions[name] = {"endpoint": endpoint, "url": url, "token": token,
                          "accelerator": res.get("accelerator")}
        _save_sessions(sessions)
        if args.file.endswith(".ipynb"):
            import nbformat

            nb = nbformat.read(args.file, as_version=4)
            for i, cell in enumerate(nb.cells):
                if cell.cell_type != "code":
                    continue
                src = "".join(cell.source)
                if "drive.mount" in src:
                    print(f"[cell {i}] skipped: drive.mount can tuong tac",
                          file=sys.stderr)
                    result["cells"].append({"i": i, "skipped": "drive.mount",
                                           "output": "", "error": ""})
                    continue
                print(f"[cell {i}] running...", file=sys.stderr)
                outputs, reply = execute_code(url, token, src,
                                              timeout=args.timeout)
                text = outputs_to_text(outputs)
                err = ""
                if reply.get("content", {}).get("status") == "error":
                    err = (reply["content"].get("ename", "")
                           + ": " + reply["content"].get("evalue", ""))
                    ok = False
                result["cells"].append({"i": i, "output": text, "error": err})
                print(text)
        else:
            with open(args.file) as f:
                code = f.read()
            outputs, reply = execute_code(url, token, code,
                                          timeout=args.timeout)
            text = outputs_to_text(outputs)
            if reply.get("content", {}).get("status") == "error":
                ok = False
            result["cells"].append({"i": 0, "output": text, "error": ""})
            print(text)
        result["ok"] = ok
    except Exception as e:  # noqa: BLE001 — ghi loi vao ket qua, roi don dep
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"error: {e}", file=sys.stderr)
        ok = False
    finally:
        if args.out:
            with open(args.out, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        if not args.keep and endpoint:
            try:
                client.unassign(endpoint)
                print(f"stopped {endpoint}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001 — may da tat hoac loi mang
                print(f"khong tat duoc runtime: {e}", file=sys.stderr)
            sessions = _load_sessions()
            if name:
                sessions.pop(name, None)
            _save_sessions(sessions)
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="vncolab",
                                description="CLI cua minh chay code tren Colab T4.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_text in [
            ("auth-url", "in URL phe duyet Google (mo bang dien thoai)"),
            ("auth-code", "doi code phe duyet lay token"),
            ("auth", "1 tien trinh: in URL, doc code tu stdin"),
            ("usage", "so du compute units"),
            ("sessions", "liet ke runtime dang chay"),
            ("new", "cap runtime moi"),
            ("run", "cap may, chay file, tat may"),
            ("stop", "tat runtime")]:
        sp = sub.add_parser(name, help=help_text)
        if name == "auth-code":
            sp.add_argument("code", help="code Google hien sau khi phe duyet")
            sp.set_defaults(func=cmd_auth_code)
        elif name == "auth-url":
            sp.set_defaults(func=cmd_auth_url)
        elif name == "auth":
            sp.set_defaults(func=cmd_auth)
        elif name == "usage":
            sp.set_defaults(func=cmd_usage)
        elif name == "sessions":
            sp.set_defaults(func=cmd_sessions)
        elif name == "new":
            sp.add_argument("--gpu", default=None, help="T4, L4, A100...")
            sp.add_argument("-s", "--name", default=None)
            sp.set_defaults(func=cmd_new)
        elif name == "run":
            sp.add_argument("file", help=".py hoac .ipynb")
            sp.add_argument("--gpu", default="T4")
            sp.add_argument("--timeout", type=int, default=1800)
            sp.add_argument("--out", default="vncolab_result.json")
            sp.add_argument("--keep", action="store_true",
                            help="giu runtime sau khi chay xong")
            sp.set_defaults(func=cmd_run)
        elif name == "stop":
            sp.add_argument("name", nargs="?", default=None)
            sp.set_defaults(func=cmd_stop)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
