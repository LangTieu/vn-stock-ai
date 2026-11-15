import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_audit_drive_ohlcv import coverage


class DriveOHLCVAuditTests(unittest.TestCase):
    def test_reports_real_row_endpoint_diagnostics_without_relabeling(self):
        sessions = {'HOSE': [date(2024, 1, 1) + timedelta(days=i) for i in range(121)]}
        prices = {('AAA', 'HOSE', sessions['HOSE'][0]): {'close': 100},
                  ('AAA', 'HOSE', sessions['HOSE'][120]): {'close': 96}}
        reports = coverage([('p1_train.jsonl', 'AAA', 'HOSE', sessions['HOSE'][0], 'UP')],
                           prices, sessions)
        report = reports[0]
        self.assertEqual(report['counts']['raw_exact_120_session_endpoints'], 1)
        self.assertEqual(report['raw_close_120_session_labels_deadband_2pct_diagnostic_only'],
                         {'DOWN': 1})
        self.assertEqual(report['raw_vs_v1_label_transition_counts_not_a_final_metric'],
                         {'UP->DOWN': 1})

    def test_separately_counts_missing_start_and_endpoint_quotes(self):
        sessions = {'HOSE': [date(2024, 1, 1) + timedelta(days=i) for i in range(121)]}
        p1 = [('p1_train.jsonl', 'AAA', 'HOSE', sessions['HOSE'][0], 'UP')]
        report = coverage(p1, {}, sessions)[0]
        self.assertEqual(report['counts']['missing_start_raw_close'], 1)
        self.assertEqual(report['counts']['missing_endpoint_raw_close'], 1)
        self.assertEqual(report['counts'].get('raw_exact_120_session_endpoints', 0), 0)


if __name__ == '__main__':
    unittest.main()
