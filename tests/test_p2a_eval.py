import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_eval import (bootstrap_confidence_intervals, calibration, load_eval_tokenizer,
                      trend_row, validate_eval_label_versions)
from p2a_train import MODEL_ID


def record(truth, prediction='DOWN', p_up=0.5, base_prediction='DOWN', base_p_up=0.5,
           raw_generation=None):
    return {'truth': truth, 'prediction': prediction, 'p_up': p_up,
            'base_prediction': base_prediction, 'base_p_up': base_p_up,
            'probability_level': 3 if p_up >= 0.5 else 2,
            'generated_direction': 'TĂNG' if truth == 'UP' else 'GIẢM',
            'raw_generation': raw_generation or ('TĂNG' if truth == 'UP' else 'GIẢM')}


class EvaluationBaselineTests(unittest.TestCase):
    def test_adapter_evaluation_loads_tokenizer_from_base_model_not_lora_checkpoint(self):
        calls = []

        class TokenizerLoader:
            @staticmethod
            def from_pretrained(source):
                calls.append(source)
                return 'tokenizer'

        self.assertEqual(load_eval_tokenizer(TokenizerLoader), 'tokenizer')
        self.assertEqual(calls, [MODEL_ID])

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

    def test_metrics_include_per_class_validity_base_comparison_and_seeded_intervals(self):
        records = [
            record('UP', 'UP', .8, 'DOWN', .4),
            record('UP', 'DOWN', .4, 'UP', .7, raw_generation='uncertain'),
            record('DOWN', 'DOWN', .2, 'DOWN', .3),
            record('DOWN', 'DOWN', .1, 'UP', .6),
        ]
        first = calibration(records)
        second = calibration(records)
        self.assertEqual(first['n'], 4)
        self.assertEqual(first['class_precision'], {'UP': 1.0, 'DOWN': 2 / 3})
        self.assertEqual(first['class_recall'], {'UP': .5, 'DOWN': 1.0})
        self.assertEqual(first['invalid_output_rate'], .25)
        self.assertEqual(first['base_model']['direction_accuracy'], .5)
        self.assertAlmostEqual(first['learning_signal']['direction_accuracy_delta'], .25)
        self.assertEqual(first['confidence_intervals'], second['confidence_intervals'])
        for metric in ('direction_accuracy', 'macro_f1', 'brier'):
            ci = first['confidence_intervals'][metric]
            self.assertEqual(ci['resamples'], 1000)
            self.assertLessEqual(ci['lower'], first[metric])
            self.assertGreaterEqual(ci['upper'], first[metric])
            self.assertEqual(first['base_model']['confidence_intervals'][metric]['resamples'], 1000)
        trend = trend_row({**first, 'checkpoint_step': 250, 'dataset_sha256': 'slice-hash'})
        self.assertEqual(trend['n'], 4)
        self.assertEqual(trend['base_model_accuracy'], 0.5)
        self.assertEqual(trend['direction_accuracy_ci_lower'],
                         first['confidence_intervals']['direction_accuracy']['lower'])
        self.assertEqual(trend['brier_ci_upper'], first['confidence_intervals']['brier']['upper'])

    def test_bootstrap_rejects_empty_or_nonpositive_replicates(self):
        with self.assertRaisesRegex(ValueError, 'empty'):
            bootstrap_confidence_intervals([])
        with self.assertRaisesRegex(ValueError, 'positive'):
            bootstrap_confidence_intervals([record('UP')], resamples=0)


if __name__ == '__main__':
    unittest.main()
