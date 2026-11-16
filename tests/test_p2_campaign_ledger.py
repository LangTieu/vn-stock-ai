import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/p2_campaign_ledger.py'
sys.path.insert(0, str(ROOT / 'scripts'))
from p2_campaign_ledger import (DATASET_REVISION, LEGACY_CUTOFF_RUN_ID,
                                MAX_SESSIONS, MAX_SESSION_STEPS, MAX_TOTAL_STEPS,
                                initial_ledger, record_event, validate_ledger,
                                validate_training_dispatch)


class CampaignLedgerTests(unittest.TestCase):
    def test_new_ledger_is_paused_main_only_and_excludes_legacy_history(self):
        ledger = initial_ledger()
        self.assertTrue(validate_ledger(ledger))
        self.assertEqual(ledger['schema_version'], 2)
        self.assertEqual(ledger['campaign_ref'], 'main')
        self.assertEqual(ledger['legacy_cutoff_run_id'], 43580242658)
        self.assertEqual(ledger['max_sessions'], MAX_SESSIONS)
        self.assertEqual(ledger['steps_per_session'], MAX_SESSION_STEPS)
        self.assertEqual(ledger['max_total_steps'], MAX_TOTAL_STEPS)
        self.assertEqual(ledger['status'], 'paused')
        self.assertFalse(ledger['approved'])
        self.assertEqual(ledger['dispatch_intents'], [])
        self.assertEqual(ledger['seen_source_run_ids'], [])

    def test_separate_event_processes_persist_state_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger_path = Path(temporary) / 'ledger.json'
            subprocess.run([sys.executable, str(SCRIPT), 'init', '--output', str(ledger_path)],
                           check=True, capture_output=True, text=True)
            event_data = [
                {'run_id': 43730000001, 'status': 'completed', 'conclusion': 'success',
                 'head_branch': 'main', 'head_sha': 'a' * 40},
                {'run_id': 43730000002, 'status': 'completed', 'conclusion': 'failure',
                 'head_branch': 'main', 'head_sha': 'b' * 40},
            ]
            for index, event in enumerate(event_data, start=1):
                event_path = Path(temporary) / f'event-{index}.json'
                event_path.write_text(json.dumps(event))
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), 'record', '--ledger', str(ledger_path),
                     '--event', str(event_path), '--decision', 'manual_recovery_review'],
                    check=True, capture_output=True, text=True)
                self.assertTrue(json.loads(result.stdout)['recorded'])
                persisted = json.loads(ledger_path.read_text())
                self.assertEqual(persisted['ledger_revision'], index)
                self.assertEqual(persisted['seen_source_run_ids'], [e['run_id'] for e in event_data[:index]])

            duplicate = record_event(ledger_path, event_data[0], 'manual_recovery_review')
            self.assertTrue(duplicate['duplicate'])
            final = json.loads(ledger_path.read_text())
            self.assertEqual(final['ledger_revision'], 2)
            self.assertEqual([e['source_sha'] for e in final['events']], ['a' * 40, 'b' * 40])
            self.assertEqual(final['dispatch_intents'], [])
            self.assertEqual(final['status'], 'paused')

    def test_ledger_fails_closed_for_wrong_ref_and_legacy_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'ledger.json'
            path.write_text(json.dumps(initial_ledger()))
            event = {'run_id': LEGACY_CUTOFF_RUN_ID, 'status': 'completed',
                     'conclusion': 'success', 'head_branch': 'main', 'head_sha': 'a' * 40}
            with self.assertRaisesRegex(ValueError, 'legacy cutoff'):
                record_event(path, event, 'ready')
            event.update(run_id=LEGACY_CUTOFF_RUN_ID + 1, head_branch='review/old')
            with self.assertRaisesRegex(ValueError, 'must equal'):
                record_event(path, event, 'ready')
            self.assertEqual(json.loads(path.read_text())['ledger_revision'], 0)

    def test_ledger_validation_refuses_unpaused_state_or_dispatch_intent(self):
        ledger = initial_ledger()
        ledger['status'] = 'active'
        with self.assertRaisesRegex(ValueError, 'active campaign requires'):
            validate_ledger(ledger)
        ledger = initial_ledger()
        ledger['seen_source_run_ids'] = [43730000001]
        ledger['events'] = [{'source_run_id': 43730000001}]
        ledger['ledger_revision'] = ledger['state_revision'] = 1
        ledger['dispatch_intents'].append({
            'intent_id': 'p2a-v2-full:test',
            'source_run_id': 43730000001,
            'dataset_revision': ledger['dataset_revision'],
            'approval_reference': None,
            'status': 'prepared',
        })
        with self.assertRaisesRegex(ValueError, 'cannot dispatch until approved'):
            validate_ledger(ledger)

    def test_dispatch_inputs_allow_only_initial_run_or_committed_intent(self):
        ledger = initial_ledger()
        ledger.update({
            'approved': True,
            'approval_reference': 'henrry-train-approval-2026-11-16-1446-ict',
            'approved_by': 'Henrry',
            'approved_at': '2026-11-16 14:46 ICT',
            'approval_recorded_at': '2026-11-16T07:00:00Z',
        })
        initial = {
            'campaign_id': 'p2a-v2-full',
            'training_approval_ref': ledger['approval_reference'],
            'p2a_v2_dataset_revision': DATASET_REVISION,
            'max_steps': '50', 'resume_checkpoint': '', 'campaign_chain_source_run_id': '',
            'notebook': 'notebooks/p2a_train.ipynb', 'mode': 'full',
            'executor': 'lv1', 'gpu': 'T4', 'train_profile': 'train_tk1',
            'save_steps': '25', 'timeout': '28800',
        }
        self.assertEqual(validate_training_dispatch(ledger, initial)['session_kind'], 'initial')
        ledger['training_workflow_ready'] = True
        ledger['status'] = 'active'
        source_id = 43830000001
        ledger['seen_source_run_ids'] = [source_id]
        ledger['events'] = [{'source_run_id': source_id}]
        ledger['ledger_revision'] = ledger['state_revision'] = 1
        ledger['sessions'] = [{
            'source_run_id': source_id, 'start_step': 0, 'end_step': 50, 'steps': 50,
            'dataset_revision': DATASET_REVISION,
            'approval_reference': ledger['approval_reference'],
        }]
        intent_inputs = {
            'campaign_id': 'p2a-v2-full',
            'training_approval_ref': ledger['approval_reference'],
            'p2a_v2_dataset_revision': DATASET_REVISION,
            'max_steps': '100', 'resume_checkpoint': 'checkpoint-50',
            'campaign_chain_source_run_id': str(source_id),
            'notebook': 'notebooks/p2a_train.ipynb', 'mode': 'full',
            'executor': 'lv1', 'gpu': 'T4', 'train_profile': 'train_tk1',
            'save_steps': '25', 'timeout': '28800',
        }
        ledger['dispatch_intents'] = [{
            'intent_id': f'p2a-v2-full:{source_id}', 'source_run_id': source_id,
            'dataset_revision': DATASET_REVISION,
            'approval_reference': ledger['approval_reference'],
            'status': 'dispatching', 'inputs': intent_inputs,
        }]
        self.assertEqual(validate_training_dispatch(ledger, intent_inputs)['session_kind'],
                         'continuation')
        tampered = dict(intent_inputs, max_steps='150')
        with self.assertRaisesRegex(ValueError, 'continuation input mismatch'):
            validate_training_dispatch(ledger, tampered)


if __name__ == '__main__':
    unittest.main()
