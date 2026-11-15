import csv
import gzip
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_label_coverage import coverage_report


class LabelCoverageTests(unittest.TestCase):
    def test_raw_prices_do_not_count_as_adjusted_label_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions_path, prices_path, p1_path = (root / name for name in
                                                   ('sessions.csv.gz', 'prices.csv.gz', 'p1.jsonl'))
            dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(125)]
            with gzip.open(sessions_path, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['exchange', 'date'])
                writer.writeheader(); writer.writerows({'exchange': 'HOSE', 'date': d} for d in dates)
            with gzip.open(prices_path, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['ticker', 'exchange', 'date', 'close',
                                                             'adjusted_total_return_close'])
                writer.writeheader()
                writer.writerows({'ticker': 'AAA', 'exchange': 'HOSE', 'date': d,
                                  'close': '100', 'adjusted_total_return_close': ''} for d in dates)
            row = {'input': 'BRIEF: Phân tích mã AAA tại 2024-01-01.\nVERIFIED_DATA\n'
                            + json.dumps({'ticker': 'AAA', 'as_of': '2024-01-01',
                                          'source': {'ohlcv': 'data/train_HOSE.json'}}),
                   'metadata': {'kind': 'bulk', 'label': {'future_direction_120': 'UP'}}}
            p1_path.write_text(json.dumps(row) + '\n')
            report = coverage_report([p1_path], prices_path, sessions_path)
        counts = report['p1_reports'][0]['rows']
        self.assertEqual(counts['raw_price_endpoints_available'], 1)
        self.assertEqual(counts.get('adjusted_price_endpoints_available', 0), 0)
        self.assertIn('ZERO', report['p1_reports'][0]['raw_price_only_return_diagnostic_not_a_final_label'])
        self.assertFalse(report['passes'])


if __name__ == '__main__':
    unittest.main()
