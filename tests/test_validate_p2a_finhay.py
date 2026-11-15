import csv
import gzip
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate_p2a_finhay import (has_observed_index_source, has_observed_session_source,
                                  validate)


def write_gz(path, columns, rows):
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class FinhayArtifactValidationTests(unittest.TestCase):
    def test_combined_source_names_retain_index_provenance(self):
        self.assertTrue(has_observed_index_source({'UPCOMINDEX+Finhay stock OHLCV bar': 1}))
        self.assertFalse(has_observed_index_source({'Finhay stock OHLCV bar': 1}))

    def test_only_observed_records_count_as_session_provenance(self):
        self.assertTrue(has_observed_session_source({'VNINDEX': 3}))
        self.assertTrue(has_observed_session_source({'Finhay stock OHLCV bar': 1}))
        self.assertFalse(has_observed_session_source(
            {'weekday_calendar_minus_cited_exchange_closures': 20}))

    def test_checks_schemas_and_never_passes_unsupported_adjustments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_gz(root / 'exchange_sessions.csv.gz', ['exchange', 'date', 'source_index'], [
                {'exchange': 'HOSE', 'date': '2021-01-04', 'source_index': 'VNINDEX'}])
            write_gz(root / 'daily_prices.csv.gz', [
                'security_id', 'ticker', 'exchange', 'date', 'open', 'high', 'low',
                'close', 'volume', 'adjusted_total_return_close'], [{
                    'security_id': 'AAA', 'ticker': 'AAA', 'exchange': 'HOSE',
                    'date': '2021-01-04', 'open': 10, 'high': 11, 'low': 9,
                    'close': 10, 'volume': 100, 'adjusted_total_return_close': ''}])
            write_gz(root / 'corporate_actions.csv.gz', [
                'security_id', 'ticker', 'exchange', 'ex_date', 'record_date', 'action_type',
                'details_json'], [])
            write_gz(root / 'security_history.csv.gz', [
                'security_id', 'ticker', 'exchange', 'listing_date', 'delisting_date',
                'sector_code', 'sector_valid_from', 'sector_valid_to'], [{
                    'security_id': 'AAA', 'ticker': 'AAA', 'exchange': 'HOSE',
                    'listing_date': '2020-01-01', 'delisting_date': '', 'sector_code': 'finance',
                    'sector_valid_from': '', 'sector_valid_to': ''}])
            report = validate(root, {'AAA'})
            self.assertTrue(report['gate']['source_artifacts_schema_valid'])
            self.assertFalse(report['gate']['documented_adjusted_total_return_price'])
            self.assertFalse(report['gate']['official_exchange_session_calendar'])
            self.assertFalse(report['gate']['historical_sector_membership_point_in_time'])
            self.assertFalse(report['gate']['passes'])


if __name__ == '__main__':
    unittest.main()
