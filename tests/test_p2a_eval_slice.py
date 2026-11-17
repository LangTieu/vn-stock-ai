import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from p2a_validation import create_slice


class EvaluationSliceTests(unittest.TestCase):
    def test_default_slice_is_256_rows_and_identical_for_each_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'validation.jsonl'
            rows = []
            start = date(2024, 1, 2)
            for label, prefix in (('UP', 'U'), ('DOWN', 'D')):
                for index in range(140):
                    as_of = (start + timedelta(days=index)).isoformat()
                    rows.append({
                        'input': f'BRIEF: mã {prefix}{index:03} tại {as_of}\nVERIFIED_DATA\n{{}}',
                        'metadata': {
                            'kind': 'bulk',
                            'market_as_of': as_of,
                            'label': {'future_direction_120': label},
                        },
                    })
            source.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

            first = create_slice(source, root / 'step-250.jsonl', root / 'step-250.manifest.json')
            second = create_slice(source, root / 'step-300.jsonl', root / 'step-300.manifest.json')

            self.assertEqual(first['per_class'], 128)
            self.assertEqual(first['selected_count'], 256)
            self.assertEqual(first['class_counts'], {'UP': 128, 'DOWN': 128})
            self.assertEqual(first['selected_row_hashes'], second['selected_row_hashes'])
            self.assertEqual(first['slice_sha256'], second['slice_sha256'])


if __name__ == '__main__':
    unittest.main()
