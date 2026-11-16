import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_clean_finhay_prices import clean


class FinhayPriceCleaningTests(unittest.TestCase):
    def test_drops_zero_placeholders_and_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, manifest = (root / name for name in ('raw.csv.gz', 'clean.csv.gz', 'manifest.json'))
            columns = ['security_id', 'ticker', 'exchange', 'date', 'open', 'high', 'low',
                       'close', 'volume', 'adjusted_total_return_close']
            rows = [
                dict(zip(columns, ['AAA', 'AAA', 'HOSE', '2024-01-02', '10', '12', '9', '11', '100', ''])),
                dict(zip(columns, ['ZZZ', 'ZZZ', 'UPCOM', '2024-01-02', '0', '0', '0', '0', '', ''])),
                dict(zip(columns, ['BBB', 'BBB', 'HNX', '2024-01-03', '100', '100', '100', '95', '20', ''])),
            ]
            with gzip.open(source, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            source_bytes = source.read_bytes()
            result = clean(source, output, manifest)
            with gzip.open(output, 'rt', encoding='utf-8', newline='') as stream:
                kept = list(csv.DictReader(stream))
            self.assertEqual(len(kept), 2)
            self.assertEqual(kept[1]['close'], '95')
            self.assertEqual(kept[1]['data_quality_flag'], 'ohlc_order_mismatch')
            self.assertEqual(result['counts']['removed_all_zero_ohlc'], 1)
            self.assertEqual(result['counts']['ohlc_order_mismatch_rows'], 1)
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertEqual(json.loads(manifest.read_text())['output_sha256'], result['output_sha256'])


if __name__ == '__main__':
    unittest.main()
