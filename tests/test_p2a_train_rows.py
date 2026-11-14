import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_train import (dataset_label_spec, dataset_label_version, make_training_manifest, rows,
                       validate_resume_manifest)


class TrainingRowFilterTests(unittest.TestCase):
    def test_excludes_flat_and_censored_but_keeps_directions(self):
        values = [
            {'metadata': {'kind': 'bulk', 'label': {'future_direction_120': 'UP'}}},
            {'metadata': {'kind': 'bulk', 'label': {'future_direction_120': 'DOWN'}}},
            {'metadata': {'kind': 'bulk', 'label': {'future_direction_120': 'FLAT'}}},
            {'metadata': {'kind': 'bulk', 'p2a_label_status': 'censored',
                          'label': {'future_direction_120': None}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.jsonl'
            path.write_text(''.join(json.dumps(value) + '\n' for value in values))
            stats = {'flat': 0, 'censored': 0}
            result = list(rows(path, stats=stats))
        self.assertEqual([row['metadata']['label']['future_direction_120'] for row in result],
                         ['UP', 'DOWN'])
        self.assertEqual(stats, {'flat': 1, 'censored': 1})

    def test_v2_dataset_is_versioned_and_old_checkpoint_resume_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = root / 'train.jsonl'
            row = {'metadata': {'kind': 'bulk', 'p2a_label_version': 2,
                                'p2a_label_status': 'labeled',
                                'label': {'future_direction_120': 'UP',
                                          'method': 'adjusted-return-v2',
                                          'future_outcomes': {'120': {'flat_band_pct': 1.5}}}}}
            data.write_text(json.dumps(row) + '\n')
            self.assertEqual(dataset_label_version(data), 2)
            spec = dataset_label_spec(data)
            self.assertEqual(spec['flat_band_pct'], 1.5)
            manifest = make_training_manifest(data, spec['label_version'], 4096, 2,
                                              flat_band_pct=spec['flat_band_pct'],
                                              label_method=spec['label_method'])
            old_checkpoint = root / 'checkpoint-150'; old_checkpoint.mkdir()
            with self.assertRaisesRegex(ValueError, 'Cannot verify this legacy checkpoint'):
                validate_resume_manifest(old_checkpoint, manifest)

    def test_resume_requires_matching_dataset_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = root / 'train.jsonl'; checkpoint = root / 'checkpoint-25'
            checkpoint.mkdir(); data.write_text('fixture')
            manifest = make_training_manifest(data, 2, 4096, 2)
            saved = dict(manifest); saved['train_sha256'] = 'old-dataset'
            (checkpoint / 'p2a_training_manifest.json').write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, 'train_sha256 mismatch'):
                validate_resume_manifest(checkpoint, manifest)


if __name__ == '__main__':
    unittest.main()
