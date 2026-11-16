import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from vncolab import p2_eval_events


class AsyncCheckpointHookTests(unittest.TestCase):
    def test_checkpoint_events_use_slice_cadence_and_full_milestones(self):
        text = '\n'.join([
            'CHECKPOINT_UPLOADED checkpoints/checkpoint-49',
            'CHECKPOINT_UPLOADED checkpoints/checkpoint-50',
            'CHECKPOINT_UPLOADED checkpoints/checkpoint-500',
            'P2_EVAL_FINAL_TRIGGER step=750',
        ])
        self.assertEqual(p2_eval_events(text), [(50, False), (500, True), (750, True)])

    def test_disabled_hook_schedules_no_evaluation(self):
        self.assertEqual(
            p2_eval_events('CHECKPOINT_UPLOADED checkpoints/checkpoint-50', enabled=False),
            [])

    def test_eval_worker_exit_is_logged_without_changing_training_ok_flag(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/vncolab.py').read_text()
        start = source.index('        for worker in eval_workers:')
        end = source.index('        for log_file in eval_log_files:', start)
        cleanup = source[start:end]
        self.assertIn('P2_EVAL_WORKER_EXIT', cleanup)
        self.assertNotIn('ok = False', cleanup)


if __name__ == '__main__':
    unittest.main()
