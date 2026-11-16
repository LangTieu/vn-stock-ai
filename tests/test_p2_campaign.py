import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from p2_campaign import checkpoint_is_v2_compatible, plan_event, plan_operation, validate_manifest
from p2_operator import gh_dispatch_args


class CampaignPlannerTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'docs/p2-campaign.json').read_text())
        self.manifest['dataset'].update({
            'revision': 'a' * 40,
            'signing_public_key_b64': 'dGVzdC1rZXk=',
            'files': {'train-v2.jsonl': {'sha256': 'b' * 64},
                      'validation-v2.jsonl': {'sha256': 'c' * 64}},
            'file_md5': {'train-v2.jsonl': 'd' * 32, 'validation-v2.jsonl': 'e' * 32},
        })

    def compatible_checkpoint(self):
        return {
            'name': 'checkpoint-50',
            'files': [
                'optimizer.pt', 'scheduler.pt', 'trainer_state.json', 'rng_state.pth',
                'adapter_config.json', 'p2a_training_manifest.json', 'adapter_model.safetensors',
            ],
            'training_manifest': {
                'label_version': 2,
                'train_sha256': self.manifest['dataset']['files']['train-v2.jsonl']['sha256'],
                'dataset_revision': self.manifest['dataset']['revision'],
                'label_method': self.manifest['dataset']['label_method'],
                'flat_band_pct': self.manifest['dataset']['flat_band_pct'],
            },
        }

    def test_campaign_blocks_training_and_evaluation_until_dataset_is_pinned(self):
        unpinned = json.loads((ROOT / 'docs/p2-campaign.json').read_text())
        unpinned['dataset']['revision'] = None
        unpinned['dataset']['signing_public_key_b64'] = None
        unpinned['dataset']['files'] = {'train-v2.jsonl': None, 'validation-v2.jsonl': None}
        unpinned['dataset']['file_md5'] = {'train-v2.jsonl': None, 'validation-v2.jsonl': None}
        for operation in ('train', 'evaluate'):
            plan = plan_operation(unpinned, operation)
            self.assertEqual(plan['decision'], 'blocked')
            self.assertTrue(any('pinned' in reason for reason in plan['blocked_reasons']))

    def test_train_plan_fails_closed_without_approval_and_v2_workflow(self):
        plan = plan_operation(self.manifest, 'train')
        self.assertEqual(plan['decision'], 'blocked')
        self.assertTrue(any('approval' in reason for reason in plan['blocked_reasons']))
        self.assertTrue(any('workflow' in reason for reason in plan['blocked_reasons']))
        self.assertFalse(plan['dispatch'])

    def test_evaluate_plan_uses_separate_runtime_profile_order(self):
        plan = plan_operation(self.manifest, 'evaluate', '50')
        self.assertEqual(plan['workflow'], 'p2-eval.yml')
        self.assertEqual(plan['profile_order'], ['eval_tk2', 'eval_tk5'])
        self.assertEqual(plan['fallback_only_on'], 'confirmed /tun/m/assign HTTP 503')
        self.assertFalse(plan['full_holdout'])

    def test_checkpoint_requires_structural_and_v2_manifest_match(self):
        ok, _ = checkpoint_is_v2_compatible(self.compatible_checkpoint(), self.manifest['dataset'])
        self.assertTrue(ok)
        old = self.compatible_checkpoint()
        old['training_manifest']['label_version'] = 1
        ok, reason = checkpoint_is_v2_compatible(old, self.manifest['dataset'])
        self.assertFalse(ok)
        self.assertIn('label_version', reason)

    def test_event_planner_blocks_running_failed_duplicate_and_wrong_ref(self):
        event = {'run_id': 1, 'status': 'in_progress', 'conclusion': None,
                 'head_branch': self.manifest['ref']}
        self.assertEqual(plan_event(self.manifest, event)['decision'], 'source_not_completed')
        event.update(status='completed', conclusion='failure')
        self.assertEqual(plan_event(self.manifest, event)['decision'], 'manual_recovery_review')
        event.update(conclusion='success', head_branch='review/p2-async-evaluation')
        self.assertEqual(plan_event(self.manifest, event)['decision'], 'ref_mismatch')
        event['head_branch'] = self.manifest['ref']
        self.manifest['state']['seen_source_run_ids'] = ['1']
        self.assertEqual(plan_event(self.manifest, event)['decision'], 'already_seen')

    def test_training_profile_advances_only_on_confirmed_assign_503(self):
        self.manifest['training_approval'] = {'status': 'approved', 'approval_reference': 'HENRRY-OK'}
        self.manifest['training_workflow_ready'] = True
        event = {'run_id': 3, 'status': 'completed', 'conclusion': 'failure',
                 'head_branch': self.manifest['ref'], 'training_profile': 'train_tk4',
                 'failure_kind': 'colab_assignment', 'http_status': 503,
                 'endpoint': '/tun/m/assign'}
        plan = plan_event(self.manifest, event)
        self.assertEqual(plan['decision'], 'profile_fallback_plan_only')
        self.assertEqual(plan['next_profile'], 'train_tk5')
        self.assertFalse(plan['dispatch'])
        event['http_status'] = 401
        self.assertEqual(plan_event(self.manifest, event)['decision'], 'manual_recovery_review')

    def test_event_planner_requires_matching_checkpoint_after_session(self):
        self.manifest['training_approval'] = {'status': 'approved', 'approval_reference': 'HENRRY-OK'}
        self.manifest['training_workflow_ready'] = True
        self.manifest['limits']['max_sessions'] = 2
        self.manifest['limits']['max_total_steps'] = 100
        self.manifest['state']['sessions'] = [{'steps': 50}]
        event = {'run_id': 2, 'status': 'completed', 'conclusion': 'success',
                 'head_branch': self.manifest['ref']}
        plan = plan_event(self.manifest, event, self.compatible_checkpoint())
        self.assertEqual(plan['decision'], 'eligible_plan_only')
        self.assertEqual(plan['max_steps'], 100)
        self.assertFalse(plan['dispatch'])
        plan = plan_event(self.manifest, event, None)
        self.assertEqual(plan['decision'], 'approval_or_preflight_required')

    def test_session_and_total_caps_block_training(self):
        self.manifest['training_approval'] = {'status': 'approved', 'approval_reference': 'HENRRY-OK'}
        self.manifest['training_workflow_ready'] = True
        self.manifest['state']['sessions'] = [{'steps': 50}]
        self.manifest['state']['latest_checkpoint'] = self.compatible_checkpoint()
        self.assertIn('max_sessions cap reached', plan_operation(self.manifest, 'train')['blocked_reasons'])

    def test_manifest_rejects_credential_material(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['credentials'] = {'token': 'never'}
        with self.assertRaisesRegex(ValueError, 'credential'):
            validate_manifest(manifest)

    def test_campaign_ref_fails_closed_unless_main(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['ref'] = 'review/p2-async-evaluation'
        with self.assertRaisesRegex(ValueError, 'campaign_ref must equal .main.'):
            validate_manifest(manifest)
        manifest['ref'] = 'main'
        self.assertTrue(validate_manifest(manifest))

    def test_campaign_workflow_only_accepts_main_workflow_run_events(self):
        workflow = (ROOT / '.github/workflows/p2-campaign.yml').read_text()
        self.assertIn('branches: [main]', workflow)
        self.assertNotIn('branches: [review/p2-async-evaluation]', workflow)
        self.assertIn('contents: write', workflow)
        self.assertIn('p2_campaign_ledger.py record', workflow)
        self.assertIn('git push origin HEAD:main', workflow)
        self.assertIn('docs/p2-campaign-ledger-v2.json', workflow)
        self.assertIn('queue: max', workflow)

    def test_dispatch_argv_is_all_strings_and_uses_main_ref(self):
        plan = plan_operation(self.manifest, 'evaluate', 50)
        plan['inputs'] = {'checkpoint_step': 50, 'full_holdout': False}
        argv = gh_dispatch_args(plan)
        self.assertTrue(all(isinstance(value, str) for value in argv))
        self.assertIn('--ref', argv)
        self.assertIn('main', argv)
        self.assertIn('checkpoint_step=50', argv)


if __name__ == '__main__':
    unittest.main()
