"""Universe chung cho cac script refresh StockApp."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnstock import Reference  # noqa: E402

RETRY_WAIT = 70
MAX_RETRY = 3

# vnstock 6 bat buoc chon nguon. Tam thoi dung Finhay (FHSC), chi can FHSC_API_KEY.
# FHSC khong co index.members() (chi ssi co) -> dung index(idx).constituents().
SOURCE = "fhsc"

# FHSC khong co VN100 (404 INDEX_NOT_FOUND) -> doc list VN100 da cache. KHONG tu che list.
VN100_CACHE_PATH = os.environ.get(
    "VN100_CACHE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "vn100_cache.json"))

# Ghi nhan (khong sua): ro VN30 cua FHSC lech 5 ma so voi ro chinh thuc.
FHSC_VN30_DEVIATION = {
    "missing": ["BSR", "LPB", "MCH", "TCX", "VPL"],
    "extra": ["BCM", "BVH", "PLX", "POW", "TPB"],
}


def vn_call(fn, label):
    for att in range(MAX_RETRY + 1):
        try:
            return fn()
        except SystemExit:
            if att >= MAX_RETRY:
                raise
            print(f"{label}: rate limit, nghi {RETRY_WAIT}s (lan {att+1})", flush=True)
            time.sleep(RETRY_WAIT)


def _symbols_of(m):
    # vnstock 5.x/6.x tra DataFrame (cot symbol); 4.x tra Series/list.
    # list(DataFrame) se ra TEN COT -> phai xu ly DataFrame truoc.
    # (pandas 2.3: Series.to_dict() KHONG con kwarg 'orient' nen
    # Series phai di nhanh tolist(), khong duoc dung hasattr to_dict.)
    if hasattr(m, "columns") and hasattr(m, "to_dict"):
        return {str(r["symbol"]).strip()
                for r in m.to_dict(orient="records")
                if str(r.get("symbol") or "").strip()}
    if hasattr(m, "tolist"):
        return set(m.tolist())
    return set(list(m))


def _load_vn100_cache(path=None):
    """List VN100 da cache (JSON list hoac {"symbols": [...]}); thieu -> set rong."""
    path = path or VN100_CACHE_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"VN100 cache KHONG doc duoc ({path}): {e}", flush=True)
        return set()
    if isinstance(data, dict):
        data = data.get("symbols") or []
    return {str(s).strip() for s in data if str(s).strip()}


def get_universe(full=False):
    """full=False: VN100+VN30 (~100 ma). full=True: toan bo stock HOSE/HNX/UPCoM."""
    if full:
        # Qua router (TUCHU-95 2A); tam thoi nguon vnstock (Dot 2).
        from scripts.source_router import listing
        recs, _src = vn_call(lambda: listing(), "list_by_exchange")
        # 4.x co cot 'type' (loc type=='stock'); 5.x bo cot type (loc bo DELISTED)
        if recs and "type" in recs[0]:
            syms = sorted({str(r["symbol"]).strip() for r in recs
                           if r.get("type") == "stock" and str(r.get("symbol")).strip()})
        else:
            syms = sorted({str(r["symbol"]).strip() for r in recs
                           if str(r.get("exchange", "")).upper() != "DELISTED"
                           and str(r.get("symbol")).strip()})
        return syms
    uni = set()
    for idx in ("VN100", "VN30"):
        got = set()
        try:
            m = vn_call(lambda: Reference(SOURCE).index(idx).constituents(),
                        f"constituents {idx}")
            got = _symbols_of(m)
        except Exception as e:  # noqa: BLE001
            print(f"constituents {idx} FAIL: {e}", flush=True)
        if idx == "VN100" and not got:
            got = _load_vn100_cache()
            print(f"VN100: {SOURCE} khong co -> dung cache ({len(got)} ma)", flush=True)
        if idx == "VN30" and got:
            print(f"VN30 ({SOURCE}) lech ro chinh thuc: {FHSC_VN30_DEVIATION}", flush=True)
        uni.update(got)
    return sorted(uni)
