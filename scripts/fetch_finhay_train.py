#!/usr/bin/env python3
"""Lay du lieu train tu Finhay (FHSC) Open API cho VN30.

Nguon: Finhay Open API (Tier 1, chi can X-FH-APIKEY).
Key doc tu ~/.finhay/credentials/.env (0600) — KHONG ghi gia tri vao file/log.
Endpoints (da verify live 08/11):
  - GET /market/price-histories-chart?symbol=..&from=<unix>&to=<unix>
      -> data {time[], open[], close[], high[], low[], volume[], symbol, resolution}
  - GET /market/foreign-trading?symbol=..  -> data[] 20 dong gan nhat
      {symbol, trading_date, buy_value, sell_value, buy_volume, sell_volume,
       net_value, net_volume}
  - GET /market/proprietary-trading?symbol=.. -> data[] 20 dong (cung shape)
Output: datasets/finhay_train_vn30.json
  {ticker: {ohlcv: [...], foreign: [...], proprietary: [...], fetched_at, ...}}
Chi luu du lieu tho — chi so P1a (RSI/MA/MACD/...) tinh sau bang Python (P1).
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

VN30 = ["ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
        "LPB", "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI",
        "STB", "TCB", "TPB", "VCB", "VHM", "VIC", "VIB", "VJC", "VNM", "VPB"]

FROM_TS = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
TO_TS = int(datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp())

ENV_PATH = os.path.expanduser("~/.finhay/credentials/.env")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "datasets", "finhay_train_vn30.json")


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


def get_json(url, api_key, timeout=30):
    req = urllib.request.Request(url)
    req.add_header("X-FH-APIKEY", api_key)
    req.add_header("User-Agent", "finhay-skill/1.0")
    req.add_header("X-FH-OPENAPI-AGENT", "hermes-agent")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_ticker(base, api_key, symbol):
    out = {"symbol": symbol}
    # OHLCV
    url = (f"{base}/market/price-histories-chart?symbol={symbol}"
           f"&from={FROM_TS}&to={TO_TS}")
    d = get_json(url, api_key)
    if d.get("error_code") not in (0, "0"):
        raise RuntimeError(f"ohlcv: {d.get('message')}")
    data = d["data"]
    n = len(data["time"])
    ohlcv = [{"date": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
              "open": data["open"][i], "high": data["high"][i],
              "low": data["low"][i], "close": data["close"][i],
              "volume": data["volume"][i]}
             for i, t in enumerate(data["time"])]
    out["ohlcv"] = ohlcv
    out["ohlcv_rows"] = n
    # foreign + proprietary (20 dong gan nhat)
    for kind in ("foreign-trading", "proprietary-trading"):
        d = get_json(f"{base}/market/{kind}?symbol={symbol}", api_key)
        if d.get("error_code") not in (0, "0"):
            raise RuntimeError(f"{kind}: {d.get('message')}")
        rows = d["data"] if isinstance(d.get("data"), list) else []
        key = "foreign" if kind.startswith("foreign") else "proprietary"
        out[key] = rows
        out[key + "_rows"] = len(rows)
    return out


def main():
    env = load_env(ENV_PATH)
    base = env["FINHAY_BASE_URL"].rstrip("/")
    api_key = env["FINHAY_API_KEY"]
    result = {"source": "finhay-fhsc-openapi",
              "universe": "VN30",
              "from": "2025-01-01", "to": "2026-11-08",
              "fetched_at": datetime.now(timezone.utc).isoformat(),
              "tickers": {}}
    ok, fail = 0, []
    for sym in VN30:
        for attempt in range(3):
            try:
                result["tickers"][sym] = fetch_ticker(base, api_key, sym)
                ok += 1
                print(f"OK {sym}: ohlcv={result['tickers'][sym]['ohlcv_rows']} "
                      f"foreign={result['tickers'][sym]['foreign_rows']} "
                      f"prop={result['tickers'][sym]['proprietary_rows']}")
                break
            except Exception as e:
                if attempt == 2:
                    fail.append((sym, str(e)))
                    print(f"FAIL {sym}: {e}")
                else:
                    time.sleep(3)
        time.sleep(0.5)
    result["ok"] = ok
    result["failed"] = fail
    os.makedirs(os.path.dirname(os.path.abspath(OUT_PATH)), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\nSaved {OUT_PATH}: {ok}/{len(VN30)} tickers OK, {len(fail)} failed")
    if fail:
        print("Failed:", fail)
        sys.exit(1)


if __name__ == "__main__":
    main()
