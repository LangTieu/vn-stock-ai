import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_drive_inventory import _inspect_json


class DriveInventoryTests(unittest.TestCase):
    def test_extracts_structure_and_ranges_without_symbol_or_price_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.json'
            path.write_text(json.dumps({'AAA': [
                {'date': '2020-01-02', 'open': 10, 'high': 12, 'low': 9,
                 'close': 11, 'volume': 100},
                {'date': '2020-01-03', 'open': 11, 'high': 13, 'low': 10,
                 'close': 12, 'volume': 120},
            ]}))
            result = _inspect_json(path)
        self.assertEqual(result['ohlcv_objects'], 2)
        self.assertEqual(result['row_objects_with_date_and_ohlc'], 2)
        self.assertEqual(result['date_ranges']['date'], ['2020-01-02', '2020-01-03'])
        self.assertNotIn('sample_rows', result)
        self.assertNotIn('AAA', json.dumps(result))
        serialized = json.dumps(result)
        self.assertNotIn('"open": 10', serialized)
        self.assertNotIn('"close": 11', serialized)


if __name__ == '__main__':
    unittest.main()
