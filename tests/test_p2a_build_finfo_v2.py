import csv
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_build_finfo_v2 import build


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sample_row(day):
    payload = {'ticker': 'AAA', 'as_of': day.isoformat(),
               'source': {'ohlcv': 'daily_HOSE'}}
    return {'input': f'BRIEF: mã AAA tại {day.isoformat()}\nVERIFIED_DATA\n'
                     + json.dumps(payload),
            'metadata': {'kind': 'bulk', 'exchange': 'HOSE',
                         'label': {'future_direction_120': 'UP'}}}


class FinfoV2BuildTests(unittest.TestCase):
    def test_builds_v2_labels_censors_missing_endpoint_and_exports_no_prices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            start = date(2024, 1, 1)
            train = root / 'p1_train.jsonl.gz'
            with gzip.open(train, 'wt', encoding='utf-8') as stream:
                stream.write(json.dumps(sample_row(start)) + '\n')
            holdout = root / 'p1_holdout.jsonl'
            holdout.write_text(json.dumps(sample_row(start)) + '\n', encoding='utf-8')
            sessions = root / 'sessions.csv.gz'
            with gzip.open(sessions, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['exchange', 'date'])
                writer.writeheader()
                for offset in range(121):
                    writer.writerow({'exchange': 'HOSE',
                                     'date': (start + timedelta(days=offset)).isoformat()})
            endpoints = root / 'endpoints.csv.gz'
            with gzip.open(endpoints, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['ticker','exchange','date','close','adClose'])
                writer.writeheader()
                writer.writerow({'ticker':'AAA','exchange':'HOSE','date':start.isoformat(),
                                 'close':'10','adClose':'5'})
                writer.writerow({'ticker':'AAA','exchange':'HOSE',
                                 'date':(start+timedelta(days=120)).isoformat(),
                                 'close':'','adClose':''})
            audit = root / 'audit.json'
            audit.write_text(json.dumps({
                'fetch_errors_by_type': {},
                'p1_sha256': {train.name:digest(train), holdout.name:digest(holdout)},
                'sessions_sha256': digest(sessions),
                'endpoint_prices_sha256': digest(endpoints),
            }), encoding='utf-8')

            out = root / 'labels'
            summary = build(train, holdout, sessions, endpoints, audit, out)
            row = json.loads((out / 'p1_train_v2.jsonl').read_text().splitlines()[0])
            self.assertEqual(row['metadata']['p2a_label_version'], 2)
            self.assertEqual(row['metadata']['p2a_label_status'], 'censored')
            self.assertEqual(summary['splits']['train']['counts']['censored_missing_endpoint_adjusted_close'], 1)
            self.assertFalse(summary['passes'])
            self.assertFalse(summary['adclose_endpoint_prices_in_artifact'])
            self.assertFalse((out / 'adjusted_prices.csv').exists())

    def test_rejects_fetch_errors_and_input_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train = root / 'p1_train.jsonl'
            holdout = root / 'p1_holdout.jsonl'
            train.write_text('{}\n'); holdout.write_text('{}\n')
            sessions = root / 'sessions.csv'; sessions.write_text('exchange,date\nHOSE,2024-01-01\n')
            endpoints = root / 'endpoints.csv.gz'
            with gzip.open(endpoints, 'wt', newline='') as stream:
                csv.writer(stream).writerow(['ticker','exchange','date','close','adClose'])
            audit = root / 'audit.json'
            audit.write_text(json.dumps({'fetch_errors_by_type': {'TimeoutError': 1}}))
            with self.assertRaisesRegex(ValueError, 'Finfo fetch errors'):
                build(train, holdout, sessions, endpoints, audit, root / 'out')
            audit.write_text(json.dumps({'fetch_errors_by_type': {}, 'p1_sha256': {}}))
            with self.assertRaisesRegex(ValueError, 'P1 input hash'):
                build(train, holdout, sessions, endpoints, audit, root / 'out')


if __name__ == '__main__':
    unittest.main()
