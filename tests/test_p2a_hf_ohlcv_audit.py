import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_hf_ohlcv_audit import _candidate_paths, _price_columns, _row_date


class HFSourceAuditHelperTests(unittest.TestCase):
    def test_selects_silver_symbol_and_preferred_index_rows(self):
        paths = {
            'ohlcv/silver/AAA/ohlcv_daily.parquet',
            'ohlcv/silver/VNINDEX/ohlcv_daily.parquet',
            'vn30/ohlcv/silver/HNXINDEX/ohlcv_daily.parquet',
            'vnx50/ohlcv/silver/UPCOMINDEX/ohlcv_daily.parquet',
        }
        symbols, indexes = _candidate_paths(paths, {'AAA', 'BBB'})
        self.assertEqual(symbols, {'AAA': 'ohlcv/silver/AAA/ohlcv_daily.parquet'})
        self.assertEqual(indexes, {
            'VNINDEX': 'ohlcv/silver/VNINDEX/ohlcv_daily.parquet',
            'HNXINDEX': 'vn30/ohlcv/silver/HNXINDEX/ohlcv_daily.parquet',
            'UPCOMINDEX': 'vnx50/ohlcv/silver/UPCOMINDEX/ohlcv_daily.parquet',
        })

    def test_detects_raw_and_adjusted_close_columns(self):
        self.assertEqual(_price_columns([
            'date', 'open_raw', 'close_raw', 'close_adj', 'exchange']),
            ('date', 'close_raw', 'close_adj', 'exchange'))

    def test_parses_observed_dates_only(self):
        self.assertEqual(_row_date('2014-01-02T00:00:00'), __import__('datetime').date(2014, 1, 2))
        self.assertIsNone(_row_date('not-a-date'))


if __name__ == '__main__':
    unittest.main()
