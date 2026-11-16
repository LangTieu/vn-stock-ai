import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_build_session_calendar import build


class SessionCalendarBuildTests(unittest.TestCase):
    def test_only_observed_price_and_index_dates_become_sessions(self):
        root = Path(__file__).resolve().parents[1]
        closures = root / 'data/p2a-label-v2/market_closures_2014_2016.csv'
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / 'index.csv.gz'
            with gzip.open(index_path, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['exchange', 'date', 'source_index'])
                writer.writeheader()
                for exchange, index in [('HOSE', 'VNINDEX'), ('HNX', 'HNXINDEX'),
                                        ('UPCOM', 'UPCOMINDEX')]:
                    writer.writerow({'exchange': exchange, 'date': '2017-01-03', 'source_index': index})
                    writer.writerow({'exchange': exchange, 'date': '2017-01-04', 'source_index': index})
            prices_path = Path(directory) / 'prices.csv.gz'
            with gzip.open(prices_path, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['exchange', 'date', 'open', 'high', 'low', 'close'])
                writer.writeheader()
                writer.writerow({'exchange': 'HOSE', 'date': '2017-01-05',
                                 'open': 10, 'high': 9, 'low': 8, 'close': 10})
                writer.writerow({'exchange': 'HOSE', 'date': '2017-01-06',
                                 'open': 0, 'high': 0, 'low': 0, 'close': 0})
            output, manifest = Path(directory) / 'sessions.csv.gz', Path(directory) / 'manifest.json'
            report = build(closures, index_path, output, manifest, prices_path)
            with gzip.open(output, 'rt', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({(row['exchange'], row['date']) for row in rows}, {
                ('HOSE', '2017-01-03'), ('HOSE', '2017-01-04'),
                ('HOSE', '2017-01-05'), ('HNX', '2017-01-03'),
                ('HNX', '2017-01-04'), ('UPCOM', '2017-01-03'),
                ('UPCOM', '2017-01-04')})
            self.assertFalse(any(row['date'] < '2017-01-01' for row in rows))
            self.assertEqual(report['rows_by_exchange_year']['HOSE:2017'], 3)
            self.assertEqual(report['sourced_closures_used_as_sessions'], 0)
            self.assertEqual(report['new_sessions_added_from_stock_prices'], 1)
            self.assertEqual(report['rejected_stock_price_rows_without_valid_close_or_date'], 1)
            self.assertIn('Finhay stock OHLCV bar',
                          next(row['source_index'] for row in rows
                               if row['exchange'] == 'HOSE' and row['date'] == '2017-01-05'))


if __name__ == '__main__':
    unittest.main()
