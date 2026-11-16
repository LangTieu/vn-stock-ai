import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_eval import calibration, validate_eval_label_versions


def record(truth, prediction='DOWN', p_up=0.5):
    return {'truth': truth, 'prediction': prediction, 'p_up': p_up,
            'probability_level': 3 if p_up >= 0.5 else 2,
            'generated_direction': 'TĂNG' if truth == 'UP' else 'GIẢM',
            'raw_generation': 'TĂNG' if truth == 'UP' else 'GIẢM'}


class EvaluationBaselineTests(unittest.TestCase):
    def test_train_and_holdout_label_versions_must_match(self):
        validate_eval_label_versions({'label_version': 2}, {'label_version': 2})
        with self.assertRaisesRegex(ValueError, 'version 2'):
            validate_eval_label_versions({'label_version': 2}, {'label_version': 1})
        with self.assertRaisesRegex(ValueError, 'manifest is required'):
            validate_eval_label_versions(None, {'label_version': 2})
        with self.assertRaisesRegex(ValueError, 'version 2'):
            validate_eval_label_versions({'label_version': 1}, {'label_version': 1})

    def test_balanced_validation_slice_has_explicit_simple_baselines(self):
        result = calibration([record('UP'), record('UP'), record('DOWN'), record('DOWN')])
        baseline = result['baselines']
        self.assertEqual(baseline['class_counts'], {'UP': 2, 'DOWN': 2})
        self.assertEqual(baseline['majority_class'], 'UP')
        self.assertEqual(baseline['majority_accuracy'], 0.5)
        self.assertEqual(baseline['constant_prevalence_p_up'], 0.5)
        self.assertEqual(baseline['constant_prevalence_brier'], 0.25)

    def test_imbalanced_holdout_reports_majority_and_prevalence_baselines(self):
        result = calibration([record('DOWN') for _ in range(3)] + [record('UP')])
        baseline = result['baselines']
        self.assertEqual(baseline['majority_class'], 'DOWN')
        self.assertEqual(baseline['majority_accuracy'], 0.75)
        self.assertEqual(baseline['constant_prevalence_p_up'], 0.25)
        self.assertEqual(baseline['constant_prevalence_brier'], 0.1875)


if __name__ == '__main__':
    unittest.main()
