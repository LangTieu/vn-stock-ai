#!/usr/bin/env python3
"""Backfill OHLCV 2014-2016 tu finfo (VNDirect) — phan Finhay KHONG co.

Finhay chi co du lieu tu 2017-01-03 (do that VCB 08/11). finfo co du lieu tu
2014 (VCB: 746 dong, 2014-01-02 -> 2016-12-30). Script nay lay OHLCV
2014-01-01 -> 2016-12-31 cho toan bo 1564 ma, chuan hoa ve cung dinh dang
Finhay ({date, open, high, low, close, volume}), luu tung ma vao
datasets/finfo_backfill_1416_raw/<SYMBOL>.json (resumable — chay lai bo qua
ma da co file). Sau khi ca Finhay (2017+) va finfo (2014-2016) xong, gop bang
scripts/merge_2014_2026.py.
finfo la API public (khong key). Chua ro rate limit — dung 2 worker + delay
0.5s, co retry.
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

BASE = "https://api-finfo.vndirect.com.vn/v4/stock_prices"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASETS_DIR = os.path.join(BASE_DIR, "..", "datasets")
TICKERS_PATH = os.path.join(DATASETS_DIR, "market_tickers.json")
RAW_DIR = os.path.join(DATASETS_DIR, "finfo_backfill_1416_raw")
WORKERS = 2
DELAY = 0.5


def fetch_ticker(symbol):
    url = (f"{BASE}?q=code:{symbol}~date:gte:2014-01-01~date:lte:2016-12-31"
           f"&size=5000&sort=date")
    for attempt in range(3):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.loads(r.read().decode())
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)
    rows = d.get("data", [])
    # finfo tra sort=date giam dan (moi -> cu); sap lai tang dan cho khop Finhay
    rows.sort(key=lambda r: r["date"])
    ohlcv = [{"date": r["date"], "open": r["open"], "high": r["high"],
              "low": r["low"], "close": r["close"],
              "volume": r.get("nmVolume")}
             for r in rows]
    return {"symbol": symbol, "source": "finfo-vndirect",
            "from": "2014-01-01", "to": "2016-12-31",
            "ohlcv": ohlcv, "ohlcv_rows": len(ohlcv)}


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    tickers = json.load(open(TICKERS_PATH))
    by_floor = tickers["by_floor"]
    jobs = [sym for syms in by_floor.values() for sym in syms]
    pending = [s for s in jobs
               if not os.path.exists(os.path.join(RAW_DIR, s + ".json"))]
    done_before = len(jobs) - len(pending)
    print(f"Total tickers: {len(jobs)} | da co: {done_before} | can lay: {len(pending)}")
    if not pending:
        print("Tat ca da lay xong.")
        return

    failed = []
    lock = threading.Lock()
    done = [0]

    def work(sym):
        for attempt in range(3):
            try:
                r = fetch_ticker(sym)
                with open(os.path.join(RAW_DIR, sym + ".json"), "w") as f:
                    json.dump(r, f, ensure_ascii=False)
                time.sleep(DELAY)
                with lock:
                    done[0] += 1
                    if done[0] % 100 == 0:
                        print(f"[{done_before + done[0]}/{len(jobs)}] {sym} OK "
                              f"({r['ohlcv_rows']} rows)")
                return
            except Exception as e:
                if attempt == 2:
                    with lock:
                        failed.append((sym, str(e)[:120]))
                        done[0] += 1
                    return
                time.sleep(3)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, pending))

    print(f"\nDONE: {done_before + done[0] - len(failed)}/{len(jobs)} OK, "
          f"{len(failed)} failed")
    if failed:
        print("Failed (first 20):", failed[:20])
        json.dump(failed, open(os.path.join(DATASETS_DIR,
                                            "finfo_backfill_1416_failed.json"), "w"))
        sys.exit(1)


if __name__ == "__main__":
    main()
