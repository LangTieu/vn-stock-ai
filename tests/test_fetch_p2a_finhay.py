import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fetch_p2a_finhay import api_data, get_events, seed_from_p1


class FinhayCollectorTests(unittest.TestCase):
    def test_api_envelope_and_p1_seed_extraction(self):
        self.assertEqual(api_data(200, {'error_code': 0, 'data': [1]}), [1])
        self.assertIsNone(api_data(401, {'error_code': '1', 'data': []}))
        row = {'input': 'BRIEF: Phân tích mã AAA tại 2021-01-04.\nVERIFIED_DATA\n'
                         + json.dumps({'ticker': 'AAA', 'as_of': '2021-01-04',
                                       'source': {'ohlcv': 'data/train_2014_2026_HOSE.json'}}),
               'metadata': {'kind': 'bulk', 'label': {'future_direction_120': 'UP'}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'seed.jsonl'
            path.write_text(json.dumps(row) + '\n')
            symbols, rows = seed_from_p1(path, path)
        self.assertEqual(rows, 2)
        self.assertEqual(symbols['AAA']['exchanges'], {'HOSE'})
        self.assertEqual(symbols['AAA']['as_of'], ['2021-01-04', '2021-01-04'])

    def test_nonzero_api_error_is_not_reported_as_success(self):
        class ErrorClient:
            def get(self, *args, **kwargs):
                return 200, {'error_code': 'E_TEST', 'message': 'unavailable'}

        events, status = get_events(ErrorClient(), 'AAA', date(2020, 1, 1), date(2021, 1, 1))
        self.assertEqual(events, [])
        self.assertEqual(status, 'api_error')


if __name__ == '__main__':
    unittest.main()
