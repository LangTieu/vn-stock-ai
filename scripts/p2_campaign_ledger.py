#!/usr/bin/env python3
"""Durable, paused schema-v2 ledger for P2 campaign workflow events."""
import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2
CAMPAIGN_ID = 'p2a-v2-full'
CAMPAIGN_REF = 'main'
LEGACY_CUTOFF_RUN_ID = 43580242658
DATASET_REVISION = '4e00aefe775509fdd69fe1e70c6232468d4041d8'


def initial_ledger():
    return {
        'schema_version': SCHEMA_VERSION,
        'campaign_id': CAMPAIGN_ID,
        'status': 'paused',
        'approved': False,
        'approval_reference': None,
        'approved_by': None,
        'approved_at': None,
        'approval_recorded_at': None,
        'training_workflow_ready': False,
        'campaign_ref': CAMPAIGN_REF,
        'legacy_cutoff_run_id': LEGACY_CUTOFF_RUN_ID,
        'dataset_revision': DATASET_REVISION,
        'ledger_revision': 0,
        'seen_source_run_ids': [],
        'events': [],
        'dispatch_intents': [],
        'sessions': [],
        'latest_v2_compatible_checkpoint': None,
    }


def validate_ledger(ledger):
    if ledger.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('campaign ledger must use schema_version 2')
    if ledger.get('campaign_id') != CAMPAIGN_ID:
        raise ValueError('campaign ledger id mismatch')
    if ledger.get('campaign_ref') != CAMPAIGN_REF:
        raise ValueError(f'campaign_ref must equal {CAMPAIGN_REF!r}')
    if ledger.get('legacy_cutoff_run_id') != LEGACY_CUTOFF_RUN_ID:
        raise ValueError('campaign ledger legacy cutoff mismatch')
    if ledger.get('status') != 'paused':
        raise ValueError('campaign ledger must remain paused')
    if not isinstance(ledger.get('approved'), bool):
        raise ValueError('campaign approval flag must be boolean')
    approval_reference = ledger.get('approval_reference')
    if ledger['approved'] and (not isinstance(approval_reference, str) or not approval_reference.strip()):
        raise ValueError('approved campaign ledger requires an approval reference')
    if ledger['approved'] and (ledger.get('approved_by') != 'Henrry' or not ledger.get('approved_at')):
        raise ValueError('approved campaign ledger requires the approving authority and time')
    if not ledger['approved'] and approval_reference is not None:
        raise ValueError('unapproved campaign ledger cannot contain an approval reference')
    if ledger['approved'] and not ledger.get('approval_recorded_at'):
        raise ValueError('approved campaign ledger requires an approval timestamp')
    if ledger.get('training_workflow_ready', False) is not False:
        raise ValueError('campaign training workflow must remain unready until separately certified')
    if ledger.get('dataset_revision') != DATASET_REVISION:
        raise ValueError('campaign ledger dataset revision mismatch')
    seen = ledger.get('seen_source_run_ids')
    events = ledger.get('events')
    if not isinstance(seen, list) or not isinstance(events, list):
        raise ValueError('campaign ledger event state is malformed')
    event_ids = [event.get('source_run_id') for event in events]
    if len(seen) != len(set(seen)) or seen != event_ids:
        raise ValueError('campaign ledger event index does not match its append-only events')
    if any(not isinstance(run_id, int) or run_id <= LEGACY_CUTOFF_RUN_ID for run_id in seen):
        raise ValueError('campaign ledger contains a legacy or invalid source run id')
    if ledger.get('ledger_revision') != len(events):
        raise ValueError('campaign ledger revision does not match event count')
    if ledger.get('dispatch_intents') != []:
        raise ValueError('automatic dispatch intents are disabled while campaign is paused')
    return True


def write_ledger(path, ledger):
    path = Path(path)
    validate_ledger(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(ledger, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record_event(path, event, decision):
    path = Path(path)
    ledger = json.loads(path.read_text(encoding='utf-8'))
    validate_ledger(ledger)
    try:
        source_run_id = int(event.get('run_id'))
    except (TypeError, ValueError) as error:
        raise ValueError('workflow event must contain a numeric source run id') from error
    if source_run_id <= LEGACY_CUTOFF_RUN_ID:
        raise ValueError('workflow event is at or before the legacy cutoff')
    if event.get('head_branch') != CAMPAIGN_REF:
        raise ValueError(f'workflow event ref must equal {CAMPAIGN_REF!r}')
    head_sha = str(event.get('head_sha') or '')
    if not re.fullmatch(r'[0-9a-f]{40}', head_sha):
        raise ValueError('workflow event must include a 40-character head SHA')
    if event.get('status') != 'completed':
        raise ValueError('only completed workflow events may be recorded')
    conclusion = event.get('conclusion')
    if conclusion not in {'success', 'failure', 'cancelled', 'timed_out', 'action_required', 'stale'}:
        raise ValueError('workflow event conclusion is missing or unsupported')
    if not isinstance(decision, str) or not decision or len(decision) > 80:
        raise ValueError('planner decision is invalid')
    if source_run_id in ledger['seen_source_run_ids']:
        return {'recorded': False, 'duplicate': True, 'ledger_revision': ledger['ledger_revision']}

    ledger['events'].append({
        'source_run_id': source_run_id,
        'source_ref': CAMPAIGN_REF,
        'source_sha': head_sha,
        'status': 'completed',
        'conclusion': conclusion,
        'decision': decision,
        'recorded_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    })
    ledger['seen_source_run_ids'].append(source_run_id)
    ledger['ledger_revision'] += 1
    write_ledger(path, ledger)
    return {'recorded': True, 'duplicate': False, 'ledger_revision': ledger['ledger_revision']}


def record_approval(path, approval_reference, approved_at):
    path = Path(path)
    ledger = json.loads(path.read_text(encoding='utf-8'))
    validate_ledger(ledger)
    if not isinstance(approval_reference, str) or not re.fullmatch(
            r'henrry-train-approval-\d{4}-\d{2}-\d{2}-\d{4}-ict', approval_reference):
        raise ValueError('training approval reference has an invalid format')
    if approved_at != '2026-11-16 14:46 ICT':
        raise ValueError('training approval timestamp does not match the recorded Henrry authorization')
    if ledger['approved'] and ledger['approval_reference'] != approval_reference:
        raise ValueError('campaign ledger already contains a different approval reference')
    ledger['approved'] = True
    ledger['approval_reference'] = approval_reference
    ledger['approved_by'] = 'Henrry'
    ledger['approved_at'] = approved_at
    ledger['approval_recorded_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    ledger.setdefault('training_workflow_ready', False)
    write_ledger(path, ledger)
    return {'approved': True, 'approval_reference': approval_reference,
            'status': ledger['status'], 'training_workflow_ready': ledger['training_workflow_ready'],
            'dispatch_intents': len(ledger['dispatch_intents'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    init = subparsers.add_parser('init', help='create a new paused schema-v2 ledger')
    init.add_argument('--output', required=True)
    record = subparsers.add_parser('record', help='append one completed source workflow event')
    record.add_argument('--ledger', required=True)
    record.add_argument('--event', required=True)
    record.add_argument('--decision', required=True)
    approve = subparsers.add_parser('approve', help='record explicit training approval while keeping campaign paused')
    approve.add_argument('--ledger', required=True)
    approve.add_argument('--approval-reference', required=True)
    approve.add_argument('--approved-at', required=True)
    args = parser.parse_args()
    if args.command == 'init':
        path = Path(args.output)
        if path.exists():
            raise SystemExit(f'refusing to overwrite existing campaign ledger: {path}')
        write_ledger(path, initial_ledger())
        result = {'created': True, 'ledger_revision': 0, 'campaign_ref': CAMPAIGN_REF,
                  'status': 'paused', 'dispatch_enabled': False}
    elif args.command == 'record':
        result = record_event(args.ledger, json.loads(Path(args.event).read_text(encoding='utf-8')),
                              args.decision)
    else:
        result = record_approval(args.ledger, args.approval_reference, args.approved_at)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
