import gzip
import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fetch_p2a_finhay_universe as collector


class FakeClient:
    def __init__(self, key):
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        if path == '/market/quotes/stocks':
            return 200, {'error_code': '0', 'data': [{'symbol': 'AAA', 'name': 'A'}]}
        if path == '/market/sectors':
            return 200, {'error_code': '0', 'data': {'items': [{'sector': 'finance', 'name': 'Finance'}]}}
        page = int((params or {}).get('page', 1))
        if page == 1:
            items = [{'symbol': f'S{i:02d}', 'exchange': 'HOSE'} for i in range(50)]
            return 200, {'error_code': '0', 'data': {'items': items, 'page': 1,
                         'page_size': 50, 'total': 51, 'updated_at': '2026-11-15T00:00:00Z'}}
        return 200, {'error_code': '0', 'data': {'items': [{'symbol': 'S50', 'exchange': 'HNX'}],
                     'page': 2, 'page_size': 50, 'total': 51, 'updated_at': '2026-11-15T00:00:00Z'}}


class UniverseCollectorTests(unittest.TestCase):
    def test_collects_all_pages_and_labels_snapshot_as_current(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'FINHAY_API_KEY': 'dummy-test-key'}), \
                patch.object(collector, 'Client', FakeClient):
            collector.collect(directory)
            path = Path(directory) / 'finhay_current_sector_constituents.csv.gz'
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                sector_rows = list(csv.DictReader(stream))
            self.assertEqual(len(sector_rows), 51)
            manifest = json.loads((Path(directory) / 'finhay-current-universe-manifest.json').read_text())
            self.assertEqual(manifest['current_sector_constituent_rows'], 51)
            self.assertIn('current snapshot', manifest['files_temporal_scope'])


if __name__ == '__main__':
    unittest.main()
