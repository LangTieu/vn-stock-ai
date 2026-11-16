import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from p2_campaign_chain import (
    MAX_SESSIONS, MAX_TOTAL_STEPS, dispatch_argv, mark_dispatch_state,
    prepare_continuation, prepare_retry,
)
from p2_campaign_ledger import (
    initial_ledger, record_approval, record_event, validate_ledger,
    validate_training_dispatch, write_ledger,
)

LEDGER_SCRIPT = ROOT / 'scripts/p2_campaign_ledger.py'
CHAIN_SCRIPT = ROOT / 'scripts/p2_campaign_chain.py'


def approved_ledger():
    ledger = initial_ledger()
    ledger['approved'] = True
    ledger['approval_reference'] = 'henrry-train-approval-2026-11-16-1446-ict'
    ledger['approved_by'] = 'Henrry'
    ledger['approved_at'] = '2026-11-16 14:46 ICT'
    ledger['approval_recorded_at'] = '2026-11-16T07:52:39Z'
    return ledger


def make_event(run_id, conclusion='success'):
    return {'run_id': run_id, 'status': 'completed', 'conclusion': conclusion,
            'head_branch': 'main', 'head_sha': f'{run_id:040x}'}


def make_context(run_id, max_steps=50, parent='', resume=''):
    return {
        'campaign_id': 'p2a-v2-full',
        'run_id': run_id,
        'head_sha': f'{run_id:040x}',
        'workflow_ref': 'main',
        'notebook': 'notebooks/p2a_train.ipynb',
        'mode': 'full',
        'training_approval_ref': 'henrry-train-approval-2026-11-16-1446-ict',
        'p2a_v2_dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
        'campaign_chain_source_run_id': parent,
        'max_steps': str(max_steps),
        'save_steps': '25',
        'resume_checkpoint': resume,
        'executor': 'lv1',
        'train_profile': 'train_tk1',
        'gpu': 'T4',
        'timeout': '28800',
        'drive_inventory': 'false',
        'hf_source_audit': 'false',
        'p2a_v2_smoke': 'false',
        'p2a_v2_ablation': 'false',
    }


def make_checkpoint(step):
    prefix = {
        'optimizer.pt', 'scheduler.pt', 'trainer_state.json', 'rng_state.pth',
        'adapter_config.json', 'p2a_training_manifest.json', 'adapter_model.safetensors',
    }
    return {
        'name': f'checkpoint-{step}', 'step': step, 'files': sorted(prefix),
        'training_manifest': {
            'label_version': 2,
            'train_sha256': 'aaa239c33f7d6891bdc0dc5dd8cace00ff72075cf230bfeaa35aafac6a4978fe',
            'dataset_validation_sha256': '5ab54b64d5576eeeea2ffe849baaa1f494028916f1bac209a00ec38638e3f175',
            'dataset_repo': 'Jerlob/vn-stock-ai-p2a-v2',
            'dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
            'label_method': 'adjusted_total_return_close; 120 exchange sessions after as_of',
            'flat_band_pct': 2.0,
            'campaign_id': 'p2a-v2-full',
            'training_approval_ref': 'henrry-train-approval-2026-11-16-1446-ict',
        },
    }


class CampaignChainTests(unittest.TestCase):
    def test_failed_assignment_can_only_retry_from_committed_checkpoint_with_new_intent(self):
        parent_id, failed_id = 43830000001, 43830000002
        ledger = approved_ledger()
        ledger['seen_source_run_ids'] = [parent_id]
        ledger['events'] = [{
            'source_run_id': parent_id, 'source_ref': 'main',
            'source_sha': f'{parent_id:040x}', 'status': 'completed',
            'conclusion': 'success', 'decision': 'candidate',
            'recorded_at': '2026-11-16T00:00:00Z',
        }]
        ledger['ledger_revision'] = ledger['state_revision'] = 1
        context = make_context(parent_id)
        context['train_profile'] = 'train_tk4'
        first = prepare_continuation(ledger, make_event(parent_id), context,
                                     make_checkpoint(50))
        mark_dispatch_state(ledger, first['intent_id'], 'dispatching')
        mark_dispatch_state(ledger, first['intent_id'], 'submitted')

        failed_event = make_event(failed_id, 'failure')
        ledger['seen_source_run_ids'].append(failed_id)
        ledger['events'].append({
            'source_run_id': failed_id, 'source_ref': 'main',
            'source_sha': failed_event['head_sha'], 'status': 'completed',
            'conclusion': 'failure', 'decision': 'continuation_failed_manual_review',
            'recorded_at': '2026-11-16T00:05:00Z',
        })
        ledger['ledger_revision'] += 1
        ledger['state_revision'] += 1
        failed_context = make_context(failed_id, max_steps=100,
                                      parent=str(parent_id), resume='checkpoint-50')
        failed = prepare_continuation(ledger, failed_event, failed_context, None)
        self.assertEqual(failed['decision'], 'continuation_failed_manual_review')
        self.assertEqual(ledger['dispatch_intents'][0]['status'], 'failed')

        retried = prepare_retry(ledger, parent_id, failed_id)
        self.assertEqual(retried['intent_id'], f'p2a-v2-full:{parent_id}:retry:1')
        self.assertEqual(retried['inputs']['resume_checkpoint'], 'checkpoint-50')
        self.assertEqual(retried['inputs']['max_steps'], '100')
        self.assertEqual(retried['inputs']['train_profile'], 'train_tk4')
        mark_dispatch_state(ledger, retried['intent_id'], 'dispatching')
        self.assertEqual(validate_training_dispatch(ledger, retried['inputs'])['session_kind'],
                         'continuation')
        self.assertTrue(validate_ledger(ledger))

    def test_prepared_intent_survives_process_restart_and_duplicate_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger_path = root / 'ledger.json'
            event_path = root / 'event.json'
            context_path = root / 'context.json'
            checkpoint_path = root / 'checkpoint.json'
            plan_path = root / 'plan.json'
            run_id = 43830000001
            event = make_event(run_id)
            context = make_context(run_id)
            checkpoint = make_checkpoint(50)
            write_ledger(ledger_path, approved_ledger())
            for path, value in ((event_path, event), (context_path, context),
                                (checkpoint_path, checkpoint)):
                path.write_text(json.dumps(value), encoding='utf-8')

            record_event(ledger_path, event, 'campaign_candidate')
            command = [sys.executable, str(CHAIN_SCRIPT), 'plan',
                       '--ledger', str(ledger_path), '--event', str(event_path),
                       '--context', str(context_path), '--checkpoint-fixture',
                       str(checkpoint_path), '--output', str(plan_path)]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(first.stdout)['decision'], 'dispatch_prepared')
            persisted = json.loads(ledger_path.read_text(encoding='utf-8'))
            self.assertEqual(persisted['dispatch_intents'][0]['status'], 'prepared')
            self.assertEqual(persisted['sessions'][0]['end_step'], 50)

            replay = subprocess.run(command, check=True, capture_output=True, text=True)
            replay_plan = json.loads(replay.stdout)
            self.assertEqual(replay_plan['decision'], 'dispatch_prepared')
            self.assertFalse(replay_plan['ledger_changed'])
            self.assertEqual(len(json.loads(ledger_path.read_text())['sessions']), 1)

            intent_id = replay_plan['intent_id']
            subprocess.run([sys.executable, str(CHAIN_SCRIPT), 'mark-dispatching',
                            '--ledger', str(ledger_path), '--intent-id', intent_id],
                           check=True, capture_output=True, text=True)
            inputs_path = root / 'inputs.json'
            inputs_path.write_text(json.dumps(replay_plan['inputs']), encoding='utf-8')
            checked = subprocess.run(
                [sys.executable, str(LEDGER_SCRIPT), 'validate-dispatch',
                 '--ledger', str(ledger_path), '--inputs', str(inputs_path)],
                check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(checked.stdout)['dispatch_allowed'])
            final_ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
            self.assertEqual(final_ledger['dispatch_intents'][0]['status'], 'dispatching')
            self.assertTrue(validate_ledger(final_ledger))

    def test_first_successful_session_prepares_next_step_after_valid_checkpoint(self):
        ledger = approved_ledger()
        ledger['seen_source_run_ids'] = [43830000001]
        ledger['events'] = [{'source_run_id': 43830000001}]
        ledger['ledger_revision'] = 1
        ledger['state_revision'] = 1
        event = make_event(43830000001)
        context = make_context(43830000001)
        result = prepare_continuation(ledger, event, context, make_checkpoint(50))
        self.assertEqual(result['decision'], 'dispatch_prepared')
        self.assertTrue(result['dispatch'])
        self.assertEqual(result['inputs']['max_steps'], '100')
        self.assertEqual(result['inputs']['resume_checkpoint'], 'checkpoint-50')
        self.assertEqual(result['inputs']['campaign_chain_source_run_id'], '43830000001')
        self.assertEqual(result['inputs']['training_approval_ref'],
                         'henrry-train-approval-2026-11-16-1446-ict')
        self.assertTrue(ledger['training_workflow_ready'])
        self.assertEqual(ledger['status'], 'active')
        self.assertEqual(ledger['max_total_steps'], 5198)
        self.assertEqual(ledger['max_sessions'], MAX_SESSIONS)
        self.assertEqual(result['intent_id'], 'p2a-v2-full:43830000001')
        self.assertEqual(ledger['dispatch_intents'][0]['status'], 'prepared')
        self.assertTrue(validate_ledger(ledger))
        argv = dispatch_argv(result)
        self.assertTrue(all(isinstance(value, str) for value in argv))
        self.assertIn('--ref', argv)
        self.assertIn('main', argv)

    def test_second_successful_session_links_parent_and_resumes_latest(self):
        ledger = approved_ledger()
        ledger['training_workflow_ready'] = True
        ledger['status'] = 'active'
        ledger['seen_source_run_ids'] = [43830000001, 43830000002]
        ledger['events'] = [{'source_run_id': value} for value in ledger['seen_source_run_ids']]
        ledger['ledger_revision'] = ledger['state_revision'] = 2
        ledger['sessions'] = [{
            'source_run_id': 43830000001, 'source_sha': f'{43830000001:040x}',
            'start_step': 0, 'end_step': 50, 'steps': 50,
            'checkpoint_name': 'checkpoint-50',
            'dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
            'approval_reference': 'henrry-train-approval-2026-11-16-1446-ict',
            'profile': 'train_tk1',
        }]
        ledger['latest_v2_compatible_checkpoint'] = {'name': 'checkpoint-50', 'step': 50}
        ledger['dispatch_intents'] = [{
            'intent_id': 'p2a-v2-full:43830000001', 'source_run_id': 43830000001,
            'target_max_steps': 100, 'resume_checkpoint': 'checkpoint-50',
            'dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
            'approval_reference': 'henrry-train-approval-2026-11-16-1446-ict',
            'status': 'submitted',
        }]
        context = make_context(43830000002, max_steps=100, parent='43830000001',
                              resume='checkpoint-50')
        unsafe_ledger = copy.deepcopy(ledger)
        bad_checkpoint = make_checkpoint(100)
        bad_checkpoint['training_manifest']['dataset_revision'] = 'other-revision'
        rejected = prepare_continuation(unsafe_ledger, make_event(43830000002), context, bad_checkpoint)
        self.assertFalse(rejected['dispatch'])
        self.assertTrue(rejected['ledger_changed'])
        self.assertEqual(unsafe_ledger['dispatch_intents'][0]['status'], 'failed')
        self.assertEqual(unsafe_ledger['status'], 'paused')
        result = prepare_continuation(ledger, make_event(43830000002), context, make_checkpoint(100))
        self.assertEqual(result['decision'], 'dispatch_prepared')
        self.assertEqual(result['inputs']['max_steps'], '150')
        self.assertEqual(ledger['dispatch_intents'][0]['status'], 'completed')
        self.assertEqual(ledger['dispatch_intents'][0]['child_run_id'], 43830000002)
        self.assertTrue(validate_ledger(ledger))

    def test_campaign_final_session_caps_at_5198_without_dispatch(self):
        ledger = approved_ledger()
        ledger['training_workflow_ready'] = True
        ledger['status'] = 'active'
        all_run_ids = [43830000000 + index for index in range(104)]
        ledger['seen_source_run_ids'] = all_run_ids
        ledger['events'] = [{'source_run_id': run_id} for run_id in all_run_ids]
        ledger['ledger_revision'] = ledger['state_revision'] = len(all_run_ids)
        ledger['sessions'] = [{
            'source_run_id': 43830000000 + index,
            'source_sha': f'{43830000000 + index:040x}',
            'start_step': index * 50,
            'end_step': (index + 1) * 50,
            'steps': 50,
            'checkpoint_name': f'checkpoint-{(index + 1) * 50}',
            'dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
            'approval_reference': 'henrry-train-approval-2026-11-16-1446-ict',
        } for index in range(103)]
        ledger['latest_v2_compatible_checkpoint'] = {'name': 'checkpoint-5150', 'step': 5150}
        ledger['dispatch_intents'] = [{
            'intent_id': 'p2a-v2-full:43830000102', 'source_run_id': 43830000102,
            'target_max_steps': 5198, 'resume_checkpoint': 'checkpoint-5150',
            'dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
            'approval_reference': 'henrry-train-approval-2026-11-16-1446-ict',
            'status': 'submitted',
        }]
        context = make_context(43830000103, max_steps=5198, parent='43830000102',
                              resume='checkpoint-5150')
        context['save_steps'] = '5198'
        result = prepare_continuation(ledger, make_event(43830000103), context, make_checkpoint(5198))
        self.assertEqual(result['decision'], 'campaign_complete')
        self.assertFalse(result['dispatch'])
        self.assertEqual(ledger['status'], 'completed')
        self.assertEqual(ledger['sessions'][-1]['steps'], 48)
        self.assertEqual(ledger['sessions'][-1]['end_step'], 5198)
        self.assertTrue(validate_ledger(ledger))

    def test_failed_cancelled_wrong_context_and_bad_checkpoint_never_dispatch(self):
        ledger = approved_ledger()
        ledger['seen_source_run_ids'] = [43830000001]
        ledger['events'] = [{'source_run_id': 43830000001}]
        ledger['ledger_revision'] = ledger['state_revision'] = 1
        context = make_context(43830000001)
        failed = prepare_continuation(ledger, make_event(43830000001, 'failure'),
                                         context, make_checkpoint(50))
        self.assertFalse(failed['dispatch'])
        cancelled = prepare_continuation(ledger, make_event(43830000001, 'cancelled'),
                                            context, make_checkpoint(50))
        self.assertFalse(cancelled['dispatch'])
        wrong_approval = copy.deepcopy(context)
        wrong_approval['training_approval_ref'] = 'wrong'
        mismatch = prepare_continuation(ledger, make_event(43830000001),
                                           wrong_approval, make_checkpoint(50))
        self.assertFalse(mismatch['dispatch'])
        wrong_data = make_checkpoint(50)
        wrong_data['training_manifest']['dataset_revision'] = 'legacy'
        bad = prepare_continuation(ledger, make_event(43830000001), context, wrong_data)
        self.assertFalse(bad['dispatch'])
        self.assertEqual(ledger['dispatch_intents'], [])
        self.assertFalse(ledger['training_workflow_ready'])

    def test_failed_child_marks_intent_failed_without_dispatch(self):
        ledger = approved_ledger()
        ledger['training_workflow_ready'] = True
        ledger['status'] = 'active'
        parent_id, child_id = 43830000001, 43830000002
        ledger['seen_source_run_ids'] = [parent_id, child_id]
        ledger['events'] = [{'source_run_id': run_id} for run_id in (parent_id, child_id)]
        ledger['ledger_revision'] = ledger['state_revision'] = 2
        ledger['sessions'] = [{
            'source_run_id': parent_id, 'source_sha': f'{parent_id:040x}',
            'start_step': 0, 'end_step': 50, 'steps': 50,
            'checkpoint_name': 'checkpoint-50',
            'dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
            'approval_reference': ledger['approval_reference'],
        }]
        ledger['latest_v2_compatible_checkpoint'] = {'name': 'checkpoint-50', 'step': 50}
        ledger['dispatch_intents'] = [{
            'intent_id': f'p2a-v2-full:{parent_id}', 'source_run_id': parent_id,
            'target_max_steps': 100, 'resume_checkpoint': 'checkpoint-50',
            'dataset_revision': '4e00aefe775509fdd69fe1e70c6232468d4041d8',
            'approval_reference': ledger['approval_reference'], 'status': 'dispatching',
        }]
        context = make_context(child_id, max_steps=100, parent=str(parent_id), resume='checkpoint-50')
        result = prepare_continuation(ledger, make_event(child_id, 'failure'), context, None)
        self.assertFalse(result['dispatch'])
        self.assertEqual(result['decision'], 'continuation_failed_manual_review')
        self.assertEqual(ledger['dispatch_intents'][0]['status'], 'failed')
        self.assertEqual(ledger['dispatch_intents'][0]['child_run_id'], child_id)
        self.assertEqual(len(ledger['sessions']), 1)
        self.assertTrue(validate_ledger(ledger))


if __name__ == '__main__':
    unittest.main()
