import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.p2a_eval_async import build_remote_job, train_sha256_pin


class AsyncEvalBundleTests(unittest.TestCase):
    def test_remote_eval_bundle_uses_pinned_v2_validation_not_public_p1(self):
        source = build_remote_job(50, False, '/tmp/p2-eval', 'md5', 'sha256', 'train-sha')
        self.assertIn("filename='validation-v2.jsonl'", source)
        self.assertIn('dataset_revision=', source)
        self.assertIn('pinned V2 validation SHA-256 mismatch', source)
        self.assertIn("'--expected-dataset-repo'", source)
        self.assertNotIn('vn-stock-ai-p1', source)

    def test_train_hash_object_is_normalized_before_embedding_subprocess_argv(self):
        train_sha = 'a' * 64
        source = build_remote_job(50, False, '/tmp/p2-eval', 'md5', 'b' * 64,
                                  {'sha256': train_sha})
        self.assertIn(f'train_sha256={train_sha!r}', source)
        self.assertNotIn("train_sha256={'sha256':", source)
        self.assertIn('all(isinstance(arg, str) for arg in cmd)', source)

    def test_invalid_train_hash_pin_is_rejected_before_remote_job_generation(self):
        for value in ({'sha256': None}, {'sha256': 123}, None, 123):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'SHA-256'):
                train_sha256_pin(value)

    def test_modal_legacy_p1_smoke_is_retired_before_gpu_assignment(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/modal_p2a.py').read_text()
        self.assertIn('Modal P2a smoke is retired', source)
        self.assertIn('No GPU was requested', source)
        self.assertNotIn('gpu="T4"', source)
        self.assertNotIn('.remote()', source)


if __name__ == '__main__':
    unittest.main()
