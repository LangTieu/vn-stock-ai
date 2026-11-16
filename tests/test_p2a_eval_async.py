import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import p2a_eval_async
from scripts.p2a_eval_async import build_remote_job, checkpoint_complete, run_one


class AsyncEvalTests(unittest.TestCase):
    def test_remote_eval_bundle_includes_required_training_and_validation_sources(self):
        source = build_remote_job(50, False, '/tmp/p2-eval')
        self.assertIn("Path('/content/p2a_train.py').write_text(", source)
        self.assertIn("Path('/content/p2a_validation.py').write_text(", source)
        self.assertIn("Path('/content/p2a_eval.py').write_text(", source)

    def test_checkpoint_completeness_requires_optimizer_and_adapter_payload(self):
        files = [
            'checkpoints/checkpoint-50/optimizer.pt',
            'checkpoints/checkpoint-50/scheduler.pt',
            'checkpoints/checkpoint-50/trainer_state.json',
            'checkpoints/checkpoint-50/rng_state.pth',
            'checkpoints/checkpoint-50/adapter_config.json',
            'checkpoints/checkpoint-50/adapter_model.safetensors',
        ]
        with patch('scripts.p2a_eval_async.hf_repo_files', return_value=files):
            self.assertTrue(checkpoint_complete('unused', 50))
        with patch('scripts.p2a_eval_async.hf_repo_files', return_value=files[:-1]):
            self.assertFalse(checkpoint_complete('unused', 50))

    def test_fallback_to_tk5_only_for_tk2_assignment_503(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(p2a_eval_async, 'RESULT_ROOT', Path(directory)), \
                 patch.object(p2a_eval_async, 'run_colab_eval') as run_eval, \
                 patch.object(p2a_eval_async, 'write_trend'), \
                 patch.object(p2a_eval_async, 'upload_results'):
                run_eval.side_effect = [RuntimeError('HTTP 503 /tun/m/assign'), {
                    'checkpoint_step': 50, 'full_holdout': False,
                    'direction_accuracy': 0.5, 'macro_f1': 0.4, 'brier': 0.25}]
                self.assertTrue(run_one({'step': 50, 'full_holdout': False}))
                self.assertEqual([call.args[2] for call in run_eval.call_args_list], ['tk2', 'tk5'])

    def test_non_503_evaluator_failure_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(p2a_eval_async, 'RESULT_ROOT', Path(directory)), \
                 patch.object(p2a_eval_async, 'run_colab_eval', side_effect=RuntimeError('HTTP 401')), \
                 patch.object(p2a_eval_async, 'write_trend'), \
                 patch.object(p2a_eval_async, 'upload_results'):
                self.assertFalse(run_one({'step': 50, 'full_holdout': False}))
                p2a_eval_async.run_colab_eval.assert_called_once()


if __name__ == '__main__':
    unittest.main()
