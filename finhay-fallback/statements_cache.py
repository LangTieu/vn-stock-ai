#!/usr/bin/env python3
"""Cache so lieu tho BCTC — Tang B "tu chu du lieu" (Chot 18/10/2026).

BCTC chi thay doi khi co bao cao quy moi (~4 lan/nam) nen khong can fetch
API moi ngay. Logic:
  - statements_meta luu last_check cho moi ma.
  - Neu last_check cach hom nay < MAX_AGE_DAYS (7) -> dung cache 100%,
    0 API call.
  - Nguoc lai -> fetch tu API (income, balance, overview), luu raw + meta.

Tra ve DataFrames dung format long (period/id/name/value) + issued_share
de compute_ratios.compute_ratios() dung truc tiep duoc.

Hieu qua: 1500 ma x 3 calls/ngay -> ~4 lan/thang; run full tu 4-5h
con ~15 phut vao ngay dung cache.
"""
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

os.environ.setdefault("VNSTOCK_TELEMETRY", "off")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db  # noqa: E402

MAX_AGE_DAYS = 7
FETCH_GAP = 2
# vnstock 6 bat buoc chon nguon. Tam thoi dung Finhay (FHSC), chi can FHSC_API_KEY.
SOURCE = "fhsc"


def _df_from_rows(rows):
    """Dung lai DataFrame long-format tu rows [(period, field_id, name, value)]."""
    return pd.DataFrame(
        [{"period": p, "id": fid, "name": name, "value": v}
         for p, fid, name, v in rows])


def _save_statements(symbol, income_df, balance_df, cash_df=None):
    now = db.now_iso()
    rows = []
    for df in (income_df, balance_df, cash_df):
        if df is None:
            continue
        for _, r in df.iterrows():
            try:
                v = float(r["value"])
            except (ValueError, TypeError):
                continue
            rows.append((str(r["period"]), str(r["id"]),
                         str(r.get("name", "")), v))
    if rows:
        db.statements_save(symbol, rows, now)
    return rows


def get_statements(symbol, gap=FETCH_GAP, max_age_days=MAX_AGE_DAYS):
    """Lay (income_df, balance_df, cash_df, issued_share, from_cache).

    Uu tien cache; chi fetch API khi cache qua han hoac chua co.
    """
    today = datetime.now(timezone.utc).date()
    meta = db.statements_meta_get(symbol)
    if meta and meta.get("last_check"):
        try:
            last = datetime.fromisoformat(meta["last_check"]).date()
        except ValueError:
            last = None
        if last and (today - last).days < max_age_days:
            rows = db.statements_load(symbol)
            if rows:
                # tach income/balance/cash theo prefix field_id (IS_*/BS_*/CF_*)
                inc = _df_from_rows([r for r in rows if r[1].startswith("IS_")])
                bal = _df_from_rows([r for r in rows if r[1].startswith("BS_")])
                csh = _df_from_rows([r for r in rows if r[1].startswith("CF_")])
                if not inc.empty and not bal.empty:
                    return inc, bal, csh, meta.get("issued_share"), True
    # cache miss / het han -> fetch tu API
    from vnstock import Fundamental, Reference
    e = Fundamental(SOURCE).equity(symbol=symbol)
    income_df = e.income_statement()
    time.sleep(gap)
    balance_df = e.balance_sheet()
    time.sleep(gap)
    cash_df = e.cash_flow()
    time.sleep(gap)
    issued = None
    try:
        # FHSC overview (= company.info) khong co cot issued_share -> issued thuong la None.
        ov = Reference(SOURCE).company(symbol=symbol).overview()
        if "issued_share" in ov.columns and not ov.empty:
            issued = float(ov["issued_share"].iloc[0])
    except Exception:
        issued = None
    _save_statements(symbol, income_df, balance_df, cash_df)
    latest = None
    try:
        latest = str(sorted(income_df["period"].dropna().unique())[-1])
    except IndexError:
        pass
    db.statements_meta_save(symbol, latest, issued, db.now_iso())
    return income_df, balance_df, cash_df, issued, False


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "FPT"
    db.init_db()
    for i in range(2):
        t0 = time.time()
        inc, bal, csh, issued, cached = get_statements(sym)
        print(f"lan {i+1}: cached={cached}, {len(inc)} IS rows, "
              f"{len(bal)} BS rows, {len(csh)} CF rows, "
              f"issued={issued:.0f}, {time.time()-t0:.1f}s")
