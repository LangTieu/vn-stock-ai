import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_colab_ablation import TRIALS, _run_with_fallback, choose_best


class ColabAblationTests(unittest.TestCase):
    def test_trials_change_one_hyperparameter_at_a_time(self):
        base, low_lr, low_rank = TRIALS
        self.assertEqual({k:v for k,v in base.items() if k!='name'},
                         {k:v for k,v in low_lr.items() if k not in ('name','learning_rate')} |
                         {'learning_rate':base['learning_rate']})
        self.assertEqual({k:v for k,v in base.items() if k not in ('name','learning_rate')},
                         {k:v for k,v in low_lr.items() if k not in ('name','learning_rate')})
        self.assertEqual({k:v for k,v in base.items() if k not in ('name','lora_r')},
                         {k:v for k,v in low_rank.items() if k not in ('name','lora_r')})
        self.assertEqual([trial['name'] for trial in TRIALS],
                         ['baseline','lower_learning_rate','lower_lora_rank'])

    def test_selects_best_validation_metric_without_training_full_model(self):
        trials=[
            {'trial':{'name':'base'},'ok':True,'evaluation':{'direction_accuracy':.5,'macro_f1':.49,'brier':.25}},
            {'trial':{'name':'lr'},'ok':True,'evaluation':{'direction_accuracy':.55,'macro_f1':.52,'brier':.24}},
            {'trial':{'name':'rank'},'ok':True,'evaluation':{'direction_accuracy':.55,'macro_f1':.52,'brier':.23}},
        ]
        self.assertEqual(choose_best(trials),'rank')

    def test_only_retries_on_tk2_assign_503(self):
        attempts=[]
        def fake(profile,*args):
            attempts.append(profile)
            return {'profile':profile,'ok':profile=='tk5','assign_503':profile=='tk2'}
        result=_run_with_fallback({'name':'test'},'train','valid',12,3600,'/tmp',runner=fake)
        self.assertEqual(attempts,['tk2','tk5'])
        self.assertEqual(result['profile'],'tk5')
        attempts.clear()
        def no503(profile,*args):
            attempts.append(profile)
            return {'profile':profile,'ok':False,'assign_503':False}
        result=_run_with_fallback({'name':'test'},'train','valid',12,3600,'/tmp',runner=no503)
        self.assertEqual(attempts,['tk2'])
        self.assertFalse(result['ok'])


if __name__=='__main__':
    unittest.main()
