import sys
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.p2a_eval_async import (
    REMOTE_EVAL_RUNNER, build_remote_job, preserve_remote_eval_logs,
    train_sha256_pin,
)

DATASET_REVISION = '4e00aefe775509fdd69fe1e70c6232468d4041d8'


class AsyncEvalBundleTests(unittest.TestCase):
    def test_remote_eval_bundle_uses_pinned_v2_validation_not_public_p1(self):
        source = build_remote_job(50, False, '/tmp/p2-eval', 'md5', 'sha256', 'train-sha',
                                  DATASET_REVISION)
        self.assertIn("filename='validation-v2.jsonl'", source)
        self.assertIn(f'dataset_revision={DATASET_REVISION!r}', source)
        self.assertNotIn("dataset_revision=''", source)
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

    def test_modal_legacy_p1_smoke_is_retired_before_gpu_assignment(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/modal_p2a.py').read_text()
        self.assertIn('Modal P2a smoke is retired', source)
        self.assertIn('No GPU was requested', source)
        self.assertNotIn('gpu="T4"', source)
        self.assertNotIn('.remote()', source)


if __name__ == '__main__':
    unittest.main()
