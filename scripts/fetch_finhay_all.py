#!/usr/bin/env python3
"""Lay du lieu train tu Finhay (FHSC) Open API cho TOAN BO thi truong — BAN RESUMABLE.

Doc danh sach ma tu datasets/market_tickers.json (1564 ma: HOSE 432, HNX 299,
UPCOM 809, OTC 24 — lay tu finfo stock_prices ngay 06/11/2026).
Key doc tu ~/.finhay/credentials/.env (0600) — KHONG ghi gia tri vao file/log.
Endpoints (da verify live 08/11):
  - GET /market/price-histories-chart?symbol=..&from=<unix>&to=<unix>
  - GET /market/foreign-trading?symbol=..
  - GET /market/proprietary-trading?symbol=..

Gioi han toc do Finhay (do that 08/11):
  - 60 goi/phut (1 giay/goi) AN TOAN — 60/60 OK, 0 lan 429.
  - 5 worker (~150 goi/phut) BI 429. 2 worker + rate-limit 1 goi/giay la an toan.
  - get_json van backoff 429 (15s, 30s...) phong khi API siet them.

Resumable: moi ma luu ngay vao datasets/finhay_all_raw/<SYMBOL>.json sau khi
lay xong. Chay lai thi bo qua ma da co file (VM thay the giua chung cung khong
mat tien do). Xong het thi gop thanh file theo san (finhay_train_<FLOOR>.json).
"""
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

FROM_TS = int(datetime(2014, 1, 1, tzinfo=timezone.utc).timestamp())
TO_TS = int(datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp())
# LUU Y: Finhay chi co du lieu tu 2017-01-03 (do that VCB: 2456 dong, som nhat
# 2017-01-03). 2014-2016 lay them tu finfo (VNDirect) roi gop — xem
# scripts/fetch_finfo_backfill_1416.py. FROM=2014 de ro y dinh; Finhay tu
# tra ve tu 2017.
ENV_PATH = os.path.expanduser("~/.finhay/credentials/.env")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASETS_DIR = os.path.join(BASE_DIR, "..", "datasets")
TICKERS_PATH = os.path.join(DATASETS_DIR, "market_tickers.json")
RAW_DIR = os.path.join(DATASETS_DIR, "finhay_all_raw")
WORKERS = 2
MIN_INTERVAL = 1.0  # giay giua 2 lan goi API (toan cuc) — cap 60 goi/phut

_rate_lock = threading.Lock()
_last_call = [0.0]


def rate_limit():
    """Dam bao >= MIN_INTERVAL giay giua 2 lan goi API (toan cuc)."""
    with _rate_lock:
        now = time.monotonic()
        wait = MIN_INTERVAL - (now - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_json(url, api_key, timeout=30, max_retries=4):
    for attempt in range(max_retries):
        rate_limit()
        req = urllib.request.Request(url)
        req.add_header("X-FH-APIKEY", api_key)
        req.add_header("User-Agent", "finhay-skill/1.0")
        req.add_header("X-FH-OPENAPI-AGENT", "hermes-agent")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                time.sleep(15 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise
    raise RuntimeError("get_json: het luot retry")


def fetch_ticker(base, api_key, symbol):
    out = {"symbol": symbol}
    url = (f"{base}/market/price-histories-chart?symbol={symbol}"
           f"&from={FROM_TS}&to={TO_TS}")
    d = get_json(url, api_key)
    if d.get("error_code") not in (0, "0"):
        raise RuntimeError(f"ohlcv: {d.get('message')}")
    data = d["data"]
    ohlcv = [{"date": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
              "open": data["open"][i], "high": data["high"][i],
              "low": data["low"][i], "close": data["close"][i],
              "volume": data["volume"][i]}
             for i, t in enumerate(data["time"])]
    out["ohlcv"] = ohlcv
    out["ohlcv_rows"] = len(ohlcv)
    for kind in ("foreign-trading", "proprietary-trading"):
        d = get_json(f"{base}/market/{kind}?symbol={symbol}", api_key)
        if d.get("error_code") not in (0, "0"):
            raise RuntimeError(f"{kind}: {d.get('message')}")
        rows = d["data"] if isinstance(d.get("data"), list) else []
        key = "foreign" if kind.startswith("foreign") else "proprietary"
        out[key] = rows
        out[key + "_rows"] = len(rows)
    return out


def combine():
    """Gop cac file raw thanh file theo san."""
    tickers = json.load(open(TICKERS_PATH))
    by_floor = tickers["by_floor"]
    fetched_at = datetime.now(timezone.utc).isoformat()
    total_ok = 0
    for fl, syms in by_floor.items():
        tick = {}
        for sym in syms:
            p = os.path.join(RAW_DIR, sym + ".json")
            if os.path.exists(p):
                tick[sym] = json.load(open(p))
        out = {"source": "finhay-fhsc-openapi", "universe": "ALL-MARKET",
               "floor": fl, "from": "2014-01-01 (finhay tu 2017-01-03)",
               "to": "2026-11-08",
               "fetched_at": fetched_at, "tickers": tick, "ok": len(tick)}
        path = os.path.join(DATASETS_DIR, f"finhay_train_{fl}.json")
        with open(path, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"Combined {path}: {len(tick)}/{len(syms)} tickers")
        total_ok += len(tick)
    return total_ok


def main():
    env = load_env(ENV_PATH)
    base = env["FINHAY_BASE_URL"].rstrip("/")
    api_key = env["FINHAY_API_KEY"]
    os.makedirs(RAW_DIR, exist_ok=True)
    tickers = json.load(open(TICKERS_PATH))
    by_floor = tickers["by_floor"]
    jobs = [(sym, fl) for fl, syms in by_floor.items() for sym in syms]
    # bo qua ma da co file raw (resume)
    pending = [(s, f) for s, f in jobs
               if not os.path.exists(os.path.join(RAW_DIR, s + ".json"))]
    done_before = len(jobs) - len(pending)
    print(f"Total tickers: {len(jobs)} | da co: {done_before} | can lay: {len(pending)}")
    if not pending:
        print("Tat ca da lay xong — chi gop file.")
        total = combine()
        print(f"DONE: {total}/{len(jobs)}")
        return

    failed = []
    lock = threading.Lock()
    done = [0]

    def work(job):
        sym, fl = job
        for attempt in range(3):
            try:
                r = fetch_ticker(base, api_key, sym)
                with open(os.path.join(RAW_DIR, sym + ".json"), "w") as f:
                    json.dump(r, f, ensure_ascii=False)
                with lock:
                    done[0] += 1
                    if done[0] % 50 == 0:
                        print(f"[{done_before + done[0]}/{len(jobs)}] {sym} OK")
                return
            except Exception as e:
                if attempt == 2:
                    with lock:
                        failed.append((sym, fl, str(e)[:120]))
                        done[0] += 1
                    return
                time.sleep(2)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, pending))

    total = combine()
    print(f"\nDONE: {total}/{len(jobs)} OK, {len(failed)} failed")
    if failed:
        print("Failed (first 20):", failed[:20])
        json.dump(failed, open(os.path.join(DATASETS_DIR,
                                            "finhay_train_failed.json"), "w"))
        sys.exit(1)


if __name__ == "__main__":
    main()
