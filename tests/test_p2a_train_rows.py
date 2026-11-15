import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_train import (compact_input, dataset_label_spec, dataset_label_version,
                       make_training_manifest, messages, require_v2_training, rows,
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

    def test_ablation_config_is_fingerprinted_and_resume_rejects_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = root / 'train.jsonl'; checkpoint = root / 'checkpoint-25'
            checkpoint.mkdir(); data.write_text('fixture')
            first = make_training_manifest(
                data, 2, 4096, 2,
                lora_config={'r': 8, 'lora_alpha': 32, 'lora_dropout': 0.1},
                training_config={'learning_rate': 1e-4, 'gradient_accumulation_steps': 32},
                target_modules=['q_proj', 'v_proj'], seed=42)
            second = make_training_manifest(
                data, 2, 4096, 2,
                lora_config={'r': 8, 'lora_alpha': 32, 'lora_dropout': 0.1},
                training_config={'learning_rate': 1e-4, 'gradient_accumulation_steps': 32},
                target_modules=['q_proj', 'v_proj'], seed=43)
            self.assertNotEqual(first['seed'], second['seed'])
            self.assertNotEqual(first['training'], second['training'])
            (checkpoint / 'p2a_training_manifest.json').write_text(json.dumps(first))
            with self.assertRaisesRegex(ValueError, 'training mismatch'):
                validate_resume_manifest(checkpoint, second)

    def test_training_refuses_legacy_labels(self):
        with self.assertRaisesRegex(ValueError, 'blocked for P2a label v1'):
            require_v2_training({'label_version': 1})
        require_v2_training({'label_version': 2})

    def test_prompt_compacts_only_coverage_date_arrays_and_keeps_summary(self):
        dates = [f'2023-01-{day:02d}' for day in range(1, 22)]
        payload = {'ticker': 'AAA', 'flows': {'foreign': {
            'last20_coverage': {'count': 21, 'dates': dates, 'from': dates[0],
                                'to': dates[-1], 'status': 'partial_recent_rows'}},
            'trading_days': dates}}
        row = {'input': 'BRIEF: test\nVERIFIED_DATA\n' + json.dumps(payload)}
        before = row['input']
        compacted = compact_input(before)
        self.assertLess(len(compacted), len(before))
        parsed = json.loads(compacted.split('VERIFIED_DATA\n', 1)[1])
        coverage = parsed['flows']['foreign']['last20_coverage']
        self.assertNotIn('dates', coverage)
        self.assertEqual((coverage['count'], coverage['from'], coverage['to'], coverage['status']),
                         (21, dates[0], dates[-1], 'partial_recent_rows'))
        self.assertEqual(parsed['flows']['trading_days'], dates)
        self.assertEqual(messages(row)[1]['content'], compacted)

    def test_v2_messages_only_expose_ohlcv_and_indicators(self):
        payload = {
            'ticker': 'AAA', 'as_of': '2025-01-02', 'price': {
                'unit': 'VND', 'ohlcv': {'close': 10, 'volume': 1000},
                'change_pct_1d': 5,
            },
            'indicators': {'rsi14': 55, 'macd': 0.4},
            'flows': {'foreign': {'net': 100}}, 'fundamentals': {'pe': 12},
            'macro': {'gdp': 3}, 'signal_text': 'extra feature',
            'source': {'ohlcv': 'raw'},
        }
        row = {'input': 'BRIEF: test\nVERIFIED_DATA\n' + json.dumps(payload),
               'metadata': {'kind': 'bulk', 'p2a_label_version': 2}}
        message = messages(row)[1]['content']
        scoped = json.loads(message.split('VERIFIED_DATA\n', 1)[1])
        self.assertEqual(set(scoped), {'ticker', 'as_of', 'price', 'indicators'})
        self.assertEqual(set(scoped['price']), {'unit', 'ohlcv'})
        self.assertEqual(scoped['indicators'], {'rsi14': 55, 'macd': 0.4})
        self.assertNotIn('foreign', message)
        self.assertNotIn('fundamentals', message)
        self.assertNotIn('macro', message)

    def test_v2_feature_scope_is_fingerprinted_but_v1_scope_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'train.jsonl'
            path.write_text('fixture')
            v1 = make_training_manifest(path, 1, 4096, 2)
            v2 = make_training_manifest(path, 2, 4096, 2)
        self.assertEqual(v1['input_transform_version'], 'compact-coverage-date-lists-v1')
        self.assertEqual(v2['input_transform_version'],
                         'compact-coverage-date-lists-v1+v2-ohlcv-indicators-only-v1')


if __name__ == '__main__':
    unittest.main()
