import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_data_audit import audit


class DatasetAuditTests(unittest.TestCase):
    def test_flags_future_prompt_dates_and_split_duplicates(self):
        row = {'input': 'BRIEF: Phân tích mã AAA tại 2024-01-01.\nVERIFIED_DATA\n'
                         + json.dumps({'ticker': 'AAA', 'as_of': '2024-01-01',
                                       'source': {'ohlcv': 'data/train_HOSE.json'},
                                       'event_date': '2024-08-01'}),
               'metadata': {'kind': 'bulk', 'label': {'future_direction_120': 'UP',
                             'future_outcomes': {'120': {'endpoint_date': '2024-08-01',
                                                         'return_pct': 3.0}}}}}
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'train.jsonl', Path(directory) / 'holdout.jsonl'
            payload = json.dumps(row) + '\n'
            first.write_text(payload); second.write_text(payload)
            report = audit([first, second])
            self.assertEqual(report['reports'][0]['rows']['rows_with_future_prompt_dates'], 1)
            self.assertEqual(report['reports'][0]['exchange_counts']['HOSE']['gap_gt_200'], 1)
            self.assertEqual(report['cross_split_overlaps']['0:1']['ticker_asof'], 1)
            self.assertEqual(report['cross_split_overlaps']['0:1']['prompt_hash'], 1)
            self.assertEqual(report['cross_split_overlaps']['0:1']['temporal_target_overlap'][
                'left_targets_at_or_after_right_as_of_start'], 1)
            self.assertFalse(report['cross_split_overlaps']['0:1']['temporal_target_overlap'][
                'passes_no_forward_target_overlap'])

    def test_chronological_split_with_nonoverlapping_target_endpoints_passes(self):
        def row(as_of, endpoint):
            return {'input': 'BRIEF: Mã AAA tại ' + as_of + '\nVERIFIED_DATA\n'
                             + json.dumps({'ticker': 'AAA', 'as_of': as_of,
                                           'source': {'ohlcv': 'data/train_HOSE.json'}}),
                    'metadata': {'kind': 'bulk', 'label': {'future_direction_120': 'UP',
                                  'future_outcomes': {'120': {'endpoint_date': endpoint}}}}}

        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'train.jsonl', Path(directory) / 'holdout.jsonl'
            first.write_text(json.dumps(row('2024-07-12', '2024-12-31')) + '\n')
            second.write_text(json.dumps(row('2025-01-02', '2025-07-02')) + '\n')
            report = audit([first, second])
            temporal = report['cross_split_overlaps']['0:1']['temporal_target_overlap']
            self.assertEqual(temporal['left_target_endpoint_range'], ['2024-12-31', '2024-12-31'])
            self.assertEqual(temporal['right_as_of_start'], '2025-01-02')
            self.assertTrue(temporal['passes_no_forward_target_overlap'])


if __name__ == '__main__':
    unittest.main()
