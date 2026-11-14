import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.p2a_relabel import relabel_file


def make_row(as_of='2024-01-01'):
    return {'input': f'BRIEF: Phân tích mã AAA tại {as_of}.\nVERIFIED_DATA\n'
                      + json.dumps({'ticker': 'AAA', 'as_of': as_of,
                                    'source': {'ohlcv': 'data/train_HOSE.json'}}),
            'metadata': {'kind': 'bulk', 'split': 'train', 'label': {'future_direction_120': 'UP'}}}


class RelabelTests(unittest.TestCase):
    def test_horizon_uses_120_exchange_sessions_and_flat_deadband(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / 'calendar.csv'
            prices = root / 'prices.csv'
            source, output, manifest = (root / name for name in ('in.jsonl', 'out.jsonl', 'manifest.json'))
            days = [f'2024-01-{i:02d}' for i in range(1, 29)] + [f'2024-02-{i:02d}' for i in range(1, 29)] + [f'2024-03-{i:02d}' for i in range(1, 29)] + [f'2024-04-{i:02d}' for i in range(1, 29)] + [f'2024-05-{i:02d}' for i in range(1, 11)]
            with calendar.open('w', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(['exchange', 'date'])
                writer.writerows([['HOSE', day] for day in days])
            with prices.open('w', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(['ticker', 'exchange', 'date', 'adjusted_total_return_close'])
                for i, day in enumerate(days): writer.writerow(['AAA', 'HOSE', day, 100 if i < 120 else 101.5])
            source.write_text(json.dumps(make_row(days[0])) + '\n')
            result = relabel_file(source, output, manifest, calendar, prices)
            row = json.loads(output.read_text())
            label = row['metadata']['label']
            self.assertEqual(label['future_direction_120'], 'FLAT')
            self.assertEqual(label['future_outcomes']['120']['endpoint_date'], days[120])
            self.assertEqual(result['counts']['class_FLAT'], 1)

    def test_missing_endpoint_is_censored_not_shifted_to_later_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); calendar = root / 'calendar.csv'; prices = root / 'prices.csv'
            source, output, manifest = (root / name for name in ('in.jsonl', 'out.jsonl', 'manifest.json'))
            from datetime import date, timedelta
            days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(125)]
            with calendar.open('w', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(['exchange', 'date']); writer.writerows([['HOSE', d] for d in days])
            with prices.open('w', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(['ticker', 'exchange', 'date', 'adjusted_total_return_close'])
                for i, day in enumerate(days): writer.writerow(['AAA', 'HOSE', day, '' if i == 120 else 100])
            source.write_text(json.dumps(make_row(days[0])) + '\n')
            result = relabel_file(source, output, manifest, calendar, prices)
            row = json.loads(output.read_text()); label = row['metadata']['label']
            self.assertIsNone(label['future_direction_120'])
            self.assertEqual(row['metadata']['p2a_label_status'], 'censored')
            self.assertEqual(result['counts']['censored_missing_endpoint_adjusted_close'], 1)


if __name__ == '__main__':
    unittest.main()
