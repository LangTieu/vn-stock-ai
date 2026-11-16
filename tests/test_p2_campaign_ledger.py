import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/p2_campaign_ledger.py'
sys.path.insert(0, str(ROOT / 'scripts'))
from p2_campaign_ledger import (LEGACY_CUTOFF_RUN_ID, initial_ledger,
                                record_event, validate_ledger)


class CampaignLedgerTests(unittest.TestCase):
    def test_new_ledger_is_paused_main_only_and_excludes_legacy_history(self):
        ledger = initial_ledger()
        self.assertTrue(validate_ledger(ledger))
        self.assertEqual(ledger['schema_version'], 2)
        self.assertEqual(ledger['campaign_ref'], 'main')
        self.assertEqual(ledger['legacy_cutoff_run_id'], 43580242658)
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
        with self.assertRaisesRegex(ValueError, 'paused and unapproved'):
            validate_ledger(ledger)
        ledger = initial_ledger()
        ledger['dispatch_intents'].append({'source_run_id': 43730000001})
        with self.assertRaisesRegex(ValueError, 'dispatch intents are disabled'):
            validate_ledger(ledger)


if __name__ == '__main__':
    unittest.main()
