import csv
import gzip
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_finfo_adclose_audit import audit, fetch_symbol


def p1_row(day):
    return {
        'input': f'BRIEF: mã AAA tại {day.isoformat()}\nVERIFIED_DATA\n'
                 + json.dumps({'ticker': 'AAA', 'as_of': day.isoformat(),
                               'source': {'ohlcv': 'daily_HOSE'}}),
        'metadata': {'kind': 'bulk', 'exchange': 'HOSE',
                     'label': {'future_direction_120': 'UP'}},
    }


class FinfoAdCloseAuditTests(unittest.TestCase):
    def test_api_pagination_and_adclose_schema(self):
        replies = [
            {'data': [{'date': '2014-01-02', 'adClose': 8.0}], 'totalPages': 2},
            {'data': [{'date': '2014-01-03', 'adClose': 8.2}], 'totalPages': 2},
        ]

        class Response:
            def __init__(self, body):
                self.body = json.dumps(body).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return self.body

        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return Response(replies.pop(0))

        rows = fetch_symbol('AAA', request_interval=0, opener=opener)
        self.assertEqual(len(rows), 2)
        self.assertIn('adClose', rows[0])
        self.assertEqual(len(calls), 2)
        self.assertIn('page=2', calls[1][0])

    def test_reports_exact_adjusted_endpoint_coverage_without_labeling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            p1 = root / 'p1_train.jsonl'
            start = date(2024, 1, 1)
            p1.write_text(json.dumps(p1_row(start)) + '\n', encoding='utf-8')
            sessions = root / 'sessions.csv'
            with sessions.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=['exchange', 'date'])
                writer.writeheader()
                for offset in range(121):
                    writer.writerow({'exchange': 'HOSE',
                                     'date': (start + timedelta(days=offset)).isoformat()})

            def fake_fetch(symbol):
                self.assertEqual(symbol, 'AAA')
                return [
                    {'date': start.isoformat(), 'floor': 'HOSE', 'close': 10, 'adClose': 5},
                    {'date': (start + timedelta(days=120)).isoformat(),
                     'floor': 'HOSE', 'close': 11, 'adClose': 5.5},
                ]

            report = audit([p1], sessions, root / 'out', fetcher=fake_fetch, workers=1)
            result = report['p1_reports']['p1_train.jsonl']
            self.assertEqual(result['counts']['adjusted_price_endpoints_available'], 1)
            self.assertEqual(result['adClose_return_bands_diagnostic_only'], {'UP': 1})
            self.assertFalse(report['labels_generated'])
            self.assertFalse(report['passes'])
            with gzip.open(root / 'out/finfo-adclose-endpoints.csv.gz', 'rt') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['adClose'], '5.0')


if __name__ == '__main__':
    unittest.main()
