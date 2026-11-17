import sys
import json
import csv
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.p2a_eval_async import (
    EVAL_SLICE_PER_CLASS, REMOTE_EVAL_RUNNER, TREND_CSV_COLUMNS,
    RESULT_ROOT, build_remote_job, preserve_remote_eval_logs, trend_csv_row, write_trend,
    train_sha256_pin,
)

DATASET_REVISION = '4e00aefe775509fdd69fe1e70c6232468d4041d8'


class AsyncEvalBundleTests(unittest.TestCase):
    def test_remote_eval_bundle_uses_pinned_v2_validation_not_public_p1(self):
        source = build_remote_job(50, False, '/tmp/p2-eval', 'md5', 'sha256', 'train-sha',
                                  DATASET_REVISION)
        compile(source, '<generated-eval-job>', 'exec')
        self.assertIn("filename='validation-v2.jsonl'", source)
        self.assertEqual(EVAL_SLICE_PER_CLASS, 128)
        self.assertIn('per_class=128, seed=42', source)
        self.assertIn("manifest['selected_count'] < 256", source)
        self.assertIn('fixed checkpoint evaluation slice must contain at least 256 rows', source)
        self.assertIn(f'dataset_revision={DATASET_REVISION!r}', source)
        self.assertNotIn("dataset_revision=''", source)
        self.assertIn("Path('/content/p2a_eval.py').write_text", source)
        self.assertIn('pinned V2 validation SHA-256 mismatch', source)
        self.assertIn("'--expected-dataset-repo'", source)
        self.assertNotIn('vn-stock-ai-p1', source)

    def test_train_hash_object_is_normalized_before_embedding_subprocess_argv(self):
        train_sha = 'a' * 64
        source = build_remote_job(50, False, '/tmp/p2-eval', 'md5', 'b' * 64,
                                  {'sha256': train_sha}, DATASET_REVISION)
        self.assertIn(f'train_sha256={train_sha!r}', source)
        self.assertNotIn("train_sha256={'sha256':", source)
        self.assertIn('all(isinstance(arg, str) for arg in cmd)', source)

    def test_invalid_train_hash_pin_is_rejected_before_remote_job_generation(self):
        for value in ({'sha256': None}, {'sha256': 123}, None, 123):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'SHA-256'):
                train_sha256_pin(value)

    def test_invalid_dataset_revision_is_rejected_before_remote_job_generation(self):
        for revision in ('', 'main', '4e00aefe'):
            with self.subTest(revision=revision), self.assertRaisesRegex(ValueError, 'immutable SHA'):
                build_remote_job(150, False, '/tmp/p2-eval', 'md5', 'sha', 'train-sha', revision)

    def test_remote_evaluator_captures_and_persists_child_stdout_and_stderr(self):
        source = build_remote_job(100, False, '/tmp/p2-eval', 'md5', 'b' * 64,
                                  {'sha256': 'a' * 64}, DATASET_REVISION)
        self.assertIn('subprocess.run(cmd, capture_output=True, text=True, check=False)', source)
        self.assertIn("diagnostics=Path('/content/p2-eval')/'diagnostics'", source)
        self.assertIn('\nrun_eval_command(cmd, diagnostics)\nmetrics=', source)
        self.assertIn("remote_dir = '/content/p2-eval'",
                      (Path(__file__).resolve().parents[1] / 'scripts/p2a_eval_async.py').read_text())
        self.assertIn("'p2a_eval.stdout.log'", source)
        self.assertIn("'p2a_eval.stderr.log'", source)
        self.assertIn("stderr=result.stderr", source)

        with tempfile.TemporaryDirectory() as temporary:
            namespace = {
                'subprocess': types.SimpleNamespace(
                    run=lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 2, 'model stdout', 'root error'),
                    CalledProcessError=subprocess.CalledProcessError),
                'Path': Path,
            }
            exec(REMOTE_EVAL_RUNNER, namespace)
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                namespace['run_eval_command'](['python', 'p2a_eval.py'], temporary)
            self.assertEqual(raised.exception.stderr, 'root error')
            self.assertEqual((Path(temporary) / 'p2a_eval.stdout.log').read_text(), 'model stdout')
            self.assertEqual((Path(temporary) / 'p2a_eval.stderr.log').read_text(), 'root error')

    def test_failed_remote_archive_logs_are_extracted_for_runner_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'eval.zip'
            import zipfile
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('diagnostics/step-100/slice/p2a_eval.stdout.log', 'stdout detail')
                zipped.writestr('diagnostics/step-100/slice/p2a_eval.stderr.log', 'specific evaluator failure')
                zipped.writestr('../unrelated.txt', 'must not extract')
            preserved = preserve_remote_eval_logs(archive, root / 'runner')
            self.assertEqual({p.name for p in preserved},
                             {'p2a_eval.stdout.log', 'p2a_eval.stderr.log'})
            self.assertEqual((root / 'runner/p2a_eval.stderr.log').read_text(),
                             'specific evaluator failure')
            self.assertFalse((root / 'unrelated.txt').exists())

    def test_trend_row_flattens_model_ci_and_base_comparison(self):
        metrics = {
            'checkpoint_step': 250, 'count': 256, 'full_holdout': False,
            'direction_accuracy': .44, 'macro_f1': .43, 'brier': .26,
            'confidence_intervals': {
                'direction_accuracy': {'lower': .38, 'upper': .50},
                'macro_f1': {'lower': .37, 'upper': .49},
                'brier': {'lower': .24, 'upper': .28},
            },
            'base_model': {'direction_accuracy': .52, 'macro_f1': .51, 'brier': .24,
                           'confidence_intervals': {'direction_accuracy': {'lower': .46, 'upper': .58}}},
            'learning_signal': {'direction_accuracy_delta': -.08},
            'learning_signal_confidence_intervals': {
                'direction_accuracy_delta': {'lower': -.16, 'upper': 0.0}},
            'class_precision': {'UP': .6, 'DOWN': .4},
            'class_recall': {'UP': .5, 'DOWN': .5},
            'invalid_output_rate': .03, 'ece_4_bins': .1,
            'dataset_sha256': 'slice-hash',
        }
        row = trend_csv_row(metrics)
        self.assertEqual(row['n'], 256)
        self.assertEqual(row['direction_accuracy_ci_lower'], .38)
        self.assertEqual(row['base_model_accuracy'], .52)
        self.assertEqual(row['direction_accuracy_delta_ci_upper'], 0.0)
        self.assertEqual(row['up_precision'], .6)
        self.assertEqual(row['invalid_output_rate'], .03)
        self.assertTrue(set(TREND_CSV_COLUMNS) <= set(row))

    def test_trend_csv_contains_one_flat_comparison_row_per_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
                'scripts.p2a_eval_async.RESULT_ROOT', Path(temporary)):
            for step, accuracy in ((250, .44), (300, .48)):
                path = Path(temporary) / f'step-{step}/slice/metrics.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({
                    'checkpoint_step': step, 'full_holdout': False, 'count': 256,
                    'direction_accuracy': accuracy, 'macro_f1': .4, 'brier': .26,
                    'confidence_intervals': {
                        'direction_accuracy': {'lower': accuracy - .05, 'upper': accuracy + .05},
                        'macro_f1': {'lower': .35, 'upper': .45},
                        'brier': {'lower': .24, 'upper': .28},
                    },
                    'base_model': {'direction_accuracy': .5, 'macro_f1': .42, 'brier': .25,
                                   'confidence_intervals': {'direction_accuracy': {'lower': .44, 'upper': .56}}},
                    'learning_signal': {'direction_accuracy_delta': accuracy - .5,
                                        'macro_f1_delta': -.02, 'brier_delta': .01},
                    'learning_signal_confidence_intervals': {
                        'direction_accuracy_delta': {'lower': -.1, 'upper': .02}},
                    'class_precision': {'UP': .5, 'DOWN': .5},
                    'class_recall': {'UP': .5, 'DOWN': .5},
                    'invalid_output_rate': .01, 'ece_4_bins': .05,
                    'dataset_sha256': 'same-fixed-slice',
                }))
            write_trend()
            with (Path(temporary) / 'trend.csv').open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([int(row['checkpoint_step']) for row in rows], [250, 300])
            self.assertEqual([row['base_model_accuracy'] for row in rows], ['0.5', '0.5'])
            self.assertEqual(rows[1]['n'], '256')

    def test_modal_legacy_p1_smoke_is_retired_before_gpu_assignment(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/modal_p2a.py').read_text()
        self.assertIn('Modal P2a smoke is retired', source)
        self.assertIn('No GPU was requested', source)
        self.assertNotIn('gpu="T4"', source)
        self.assertNotIn('.remote()', source)


if __name__ == '__main__':
    unittest.main()
