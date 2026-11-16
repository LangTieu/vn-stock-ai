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


if __name__ == '__main__':
    unittest.main()
