"""Unit test: FHSC source selection + VN100 cache fallback, no network.

Uses the REAL installed vnstock 6 classes; only vnstock._fetch.run (the single
network path of every declared route) is replaced by a recorder.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# statements_cache imports backend.db at module load; stub it.
_db = types.ModuleType("backend.db")
_db.now_iso = lambda: "2026-11-14T00:00:00+00:00"
_db.statements_meta_get = lambda s: None
_db.statements_load = lambda s: []
_db.saved = []
_db.statements_save = lambda s, rows, now: _db.saved.append((s, rows))
_db.meta = []
_db.statements_meta_save = lambda *a: _db.meta.append(a)
_backend = types.ModuleType("backend")
_backend.db = _db
sys.modules.setdefault("backend", _backend)
sys.modules.setdefault("backend.db", _db)

import universe  # noqa: E402
import statements_cache  # noqa: E402
from vnstock import _fetch  # noqa: E402

VN30_FHSC = ["ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
             "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
             "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"]


class IndexNotFound(Exception):
    pass


def fake_run(calls):
    def run(route, source, symbol, **kw):
        calls.append((route, source, symbol))
        if route == "reference.index.constituents":
            if symbol == "VN100":
                raise IndexNotFound("404 INDEX_NOT_FOUND")
            return pd.DataFrame({"symbol": VN30_FHSC, "weight_percent": [1.0] * 30})
        if route.startswith("fundamental.equity."):
            prefix = {"income_statement": "IS_", "balance_sheet": "BS_",
                      "cash_flow": "CF_"}[route.rsplit(".", 1)[1]]
            return pd.DataFrame({"period": ["2025", "2026Q2"], "id": [prefix + "X"] * 2,
                                 "name": ["x", "x"], "value": [1.0, 2.0]})
        if route == "reference.company.info":
            return pd.DataFrame({"symbol": [symbol], "name": ["n"]})
        raise AssertionError(f"unexpected route {route}")
    return run


class TestUniverse(unittest.TestCase):
    def test_fhsc_selected_and_vn100_falls_back_to_cache(self):
        cached = ["AAA", "VCB"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"symbols": cached}, f)
        calls = []
        with mock.patch.object(_fetch, "run", fake_run(calls)), \
                mock.patch.object(universe, "VN100_CACHE_PATH", f.name):
            out = universe.get_universe()
        os.unlink(f.name)
        self.assertEqual(calls, [("reference.index.constituents", "fhsc", "VN100"),
                                 ("reference.index.constituents", "fhsc", "VN30")])
        self.assertEqual(out, sorted(set(VN30_FHSC) | set(cached)))

    def test_vn100_missing_cache_is_never_invented(self):
        calls = []
        with mock.patch.object(_fetch, "run", fake_run(calls)), \
                mock.patch.object(universe, "VN100_CACHE_PATH", "/nonexistent/vn100.json"):
            out = universe.get_universe()
        self.assertEqual(out, sorted(VN30_FHSC))  # VN30 only, nothing made up

    def test_vn30_deviation_recorded_not_fixed(self):
        dev = universe.FHSC_VN30_DEVIATION
        self.assertTrue(set(dev["extra"]) <= set(VN30_FHSC))
        self.assertFalse(set(dev["missing"]) & set(VN30_FHSC))


class TestStatements(unittest.TestCase):
    def test_fhsc_selected_for_fundamental_and_overview(self):
        calls = []
        with mock.patch.object(_fetch, "run", fake_run(calls)):
            inc, bal, csh, issued, cached = statements_cache.get_statements("FPT", gap=0)
        self.assertEqual(calls, [
            ("fundamental.equity.income_statement", "fhsc", "FPT"),
            ("fundamental.equity.balance_sheet", "fhsc", "FPT"),
            ("fundamental.equity.cash_flow", "fhsc", "FPT"),
            ("reference.company.info", "fhsc", "FPT"),
        ])
        self.assertFalse(cached)
        self.assertIsNone(issued)
        self.assertEqual(len(_db.saved[-1][1]), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
