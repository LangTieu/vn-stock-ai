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
    def test_official_closures_and_observed_index_sessions_are_combined(self):
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
            output, manifest = Path(directory) / 'sessions.csv.gz', Path(directory) / 'manifest.json'
            report = build(closures, index_path, output, manifest)
            self.assertEqual(report['rows_by_exchange_year']['HOSE:2014'], 247)
            self.assertEqual(report['rows_by_exchange_year']['HNX:2014'], 246)
            self.assertEqual(report['rows_by_exchange_year']['UPCOM:2014'], 246)
            self.assertEqual(report['rows_by_exchange_year']['HOSE:2015'], 248)
            self.assertEqual(report['rows_by_exchange_year']['HOSE:2016'], 251)
            with gzip.open(output, 'rt', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            hose_2015 = {row['date'] for row in rows
                         if row['exchange'] == 'HOSE' and row['date'].startswith('2015-')}
            self.assertNotIn('2015-04-29', hose_2015)
            self.assertIn('2015-04-27', hose_2015)
            self.assertIn('2017-01-03', {row['date'] for row in rows})


if __name__ == '__main__':
    unittest.main()
