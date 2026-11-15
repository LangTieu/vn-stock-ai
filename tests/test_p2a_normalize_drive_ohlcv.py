import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_normalize_drive_ohlcv import normalize


class DriveOHLCVNormalizeTests(unittest.TestCase):
    def test_normalizes_only_observed_dates_and_keeps_adjustment_blank(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'train_2014_2026_HOSE.json'
            source.write_text(json.dumps({
                'source': 'raw-observed', 'from': '2014-01-01', 'to': '2026-11-06',
                'tickers': {'AAA': {'ohlcv': [
                    {'date': '2014-01-02', 'open': 10, 'high': 11, 'low': 9,
                     'close': 10, 'volume': 100},
                    {'date': '2014-01-03', 'open': 0, 'high': 0, 'low': 0,
                     'close': 0, 'volume': 0},
                    {'date': '2014-01-06', 'open': 11, 'high': 10, 'low': 9,
                     'close': 10, 'volume': 100},
                ]}},
            }))
            output = root / 'normalized'
            report = normalize({'HOSE': source, 'HNX': source, 'UPCOM': source,
                                'OTC': source}, output)
            with gzip.open(output / 'exchange_sessions.csv.gz', 'rt', newline='') as stream:
                sessions = list(csv.DictReader(stream))
            with gzip.open(output / 'daily_prices.csv.gz', 'rt', newline='') as stream:
                prices = list(csv.DictReader(stream))
        hose = [row for row in sessions if row['exchange'] == 'HOSE']
        self.assertEqual([row['date'] for row in hose], ['2014-01-02', '2014-01-06'])
        self.assertEqual(len(prices), 8)
        self.assertTrue(all(row['adjusted_total_return_close'] == '' for row in prices))
        self.assertIn('ohlc_order_mismatch', prices[1]['data_quality_flag'])
        self.assertEqual(report['row_counts_by_exchange']['HOSE:removed_all_zero_ohlc'], 1)

    def test_refuses_output_inside_repository(self):
        root = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(ValueError, 'outside the repository'):
            normalize({}, root / 'data/p2a-label-v2/normalized')


if __name__ == '__main__':
    unittest.main()
