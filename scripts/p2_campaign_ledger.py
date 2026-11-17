#!/usr/bin/env python3
"""Durable schema-v2 P2 campaign ledger."""
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
MAX_SESSION_STEPS = 50
MAX_TOTAL_STEPS = 5198
MAX_SESSIONS = (MAX_TOTAL_STEPS + MAX_SESSION_STEPS - 1) // MAX_SESSION_STEPS


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
        'max_sessions': MAX_SESSIONS,
        'steps_per_session': MAX_SESSION_STEPS,
        'max_total_steps': MAX_TOTAL_STEPS,
        'ledger_revision': 0,
        'state_revision': 0,
        'seen_source_run_ids': [],
        'events': [],
        'dispatch_intents': [],
        'sessions': [],
        'latest_v2_compatible_checkpoint': None,
    }


def migrate_ledger(ledger):
    ledger.setdefault('approval_reference', None)
    ledger.setdefault('approved_by', None)
    ledger.setdefault('approved_at', None)
    ledger.setdefault('approval_recorded_at', None)
    ledger.setdefault('training_workflow_ready', False)
    ledger.setdefault('max_sessions', MAX_SESSIONS)
    ledger.setdefault('steps_per_session', MAX_SESSION_STEPS)
    ledger.setdefault('max_total_steps', MAX_TOTAL_STEPS)
    ledger.setdefault('state_revision', ledger.get('ledger_revision', 0))
    ledger.setdefault('sessions', [])
    ledger.setdefault('dispatch_intents', [])
    ledger.setdefault('latest_v2_compatible_checkpoint', None)
    return ledger


def validate_ledger(ledger):
    migrate_ledger(ledger)
    if ledger.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('campaign ledger must use schema_version 2')
    if ledger.get('campaign_id') != CAMPAIGN_ID:
        raise ValueError('campaign ledger id mismatch')
    if ledger.get('campaign_ref') != CAMPAIGN_REF:
        raise ValueError(f'campaign_ref must equal {CAMPAIGN_REF!r}')
    if ledger.get('legacy_cutoff_run_id') != LEGACY_CUTOFF_RUN_ID:
        raise ValueError('campaign ledger legacy cutoff mismatch')
    if ledger.get('dataset_revision') != DATASET_REVISION:
        raise ValueError('campaign ledger dataset revision mismatch')
    if ledger.get('status') not in {'paused', 'active', 'completed'}:
        raise ValueError('campaign ledger status is invalid')
    if not isinstance(ledger.get('approved'), bool):
        raise ValueError('campaign approval flag must be boolean')
    if ledger['approved']:
        if not re.fullmatch(r'henrry-train-approval-\d{4}-\d{2}-\d{2}-\d{4}-ict',
                            str(ledger.get('approval_reference') or '')):
            raise ValueError('approved campaign ledger requires a valid approval reference')
        if ledger.get('approved_by') != 'Henrry' or not ledger.get('approved_at'):
            raise ValueError('approved campaign ledger requires approver and approval time')
        if not ledger.get('approval_recorded_at'):
            raise ValueError('approved campaign ledger requires approval record time')
    elif any(ledger.get(key) is not None for key in (
            'approval_reference', 'approved_by', 'approved_at', 'approval_recorded_at')):
        raise ValueError('unapproved ledger cannot carry approval metadata')
    if not isinstance(ledger.get('training_workflow_ready'), bool):
        raise ValueError('training workflow readiness must be boolean')
    if ledger['status'] == 'active' and (not ledger['approved'] or not ledger['training_workflow_ready']):
        raise ValueError('active campaign requires approval and verified workflow readiness')
    if any(ledger.get(key) != value for key, value in (
            ('max_sessions', MAX_SESSIONS),
            ('steps_per_session', MAX_SESSION_STEPS),
            ('max_total_steps', MAX_TOTAL_STEPS))):
        raise ValueError('campaign ledger limits differ from approved 5,198-step plan')

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
    if not isinstance(ledger.get('state_revision'), int) or ledger['state_revision'] < ledger['ledger_revision']:
        raise ValueError('campaign ledger state revision is invalid')

    sessions = ledger.get('sessions')
    intents = ledger.get('dispatch_intents')
    if not isinstance(sessions, list) or not isinstance(intents, list):
        raise ValueError('campaign session/dispatch state is malformed')
    if len(sessions) > MAX_SESSIONS:
        raise ValueError('campaign session cap exceeded')
    last_end = 0
    session_ids = set()
    for session in sessions:
        if not isinstance(session, dict):
            raise ValueError('campaign session record is malformed')
        run_id = session.get('source_run_id')
        start_step = session.get('start_step')
        end_step = session.get('end_step')
        if not isinstance(run_id, int) or run_id <= LEGACY_CUTOFF_RUN_ID or run_id in session_ids:
            raise ValueError('campaign session source run id is invalid or duplicated')
        if (not isinstance(start_step, int) or not isinstance(end_step, int)
                or start_step != last_end or end_step <= start_step
                or end_step - start_step > MAX_SESSION_STEPS
                or session.get('steps') != end_step - start_step
                or end_step > MAX_TOTAL_STEPS):
            raise ValueError('campaign session step lineage is invalid')
        if (session.get('dataset_revision') != DATASET_REVISION
                or session.get('approval_reference') != ledger.get('approval_reference')):
            raise ValueError('campaign session data/approval lineage mismatch')
        session_ids.add(run_id)
        last_end = end_step
    intent_ids = []
    for intent in intents:
        if not isinstance(intent, dict) or intent.get('status') not in {
                'prepared', 'dispatching', 'submitted', 'completed', 'failed'}:
            raise ValueError('campaign dispatch intent is malformed')
        if (not intent.get('intent_id') or intent.get('dataset_revision') != DATASET_REVISION
                or intent.get('approval_reference') != ledger.get('approval_reference')):
            raise ValueError('campaign dispatch intent data/approval lineage mismatch')
        intent_ids.append(intent['intent_id'])
    if len(intent_ids) != len(set(intent_ids)):
        raise ValueError('campaign dispatch intent is duplicated')
    if not session_ids <= set(seen):
        raise ValueError('campaign session source run is absent from event history')
    if any(intent.get('source_run_id') not in seen for intent in intents):
        raise ValueError('campaign dispatch intent source run is absent from event history')
    if not session_ids <= set(seen):
        raise ValueError('campaign session source runs are not all present in event history')
    if any(intent.get('source_run_id') not in seen for intent in intents):
        raise ValueError('campaign dispatch intents are not linked to recorded events')
    pending_intents = [intent for intent in intents
                       if intent['status'] in {'prepared', 'dispatching', 'submitted'}]
    if len(pending_intents) > 1:
        raise ValueError('more than one campaign continuation intent is pending')
    if intents and (not ledger['approved'] or not ledger['training_workflow_ready']):
        raise ValueError('campaign cannot dispatch until approved and workflow-ready')
    if ledger['status'] == 'completed' and pending_intents:
        raise ValueError('completed campaign cannot have pending dispatch intents')
    if ledger['status'] == 'completed' and last_end < MAX_TOTAL_STEPS:
        raise ValueError('campaign cannot complete before the total step cap')
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
    ledger = migrate_ledger(json.loads(path.read_text(encoding='utf-8')))
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
    ledger['state_revision'] += 1
    write_ledger(path, ledger)
    return {'recorded': True, 'duplicate': False, 'ledger_revision': ledger['ledger_revision']}


def record_approval(path, approval_reference, approved_at):
    path = Path(path)
    ledger = migrate_ledger(json.loads(path.read_text(encoding='utf-8')))
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
    ledger['state_revision'] += 1
    write_ledger(path, ledger)
    return {'approved': True, 'approval_reference': approval_reference,
            'status': ledger['status'], 'training_workflow_ready': ledger['training_workflow_ready'],
            'dispatch_intents': len(ledger['dispatch_intents'])}


def set_campaign_caps(path, max_sessions=MAX_SESSIONS,
                      steps_per_session=MAX_SESSION_STEPS,
                      max_total_steps=MAX_TOTAL_STEPS):
    if (max_sessions, steps_per_session, max_total_steps) != (
            MAX_SESSIONS, MAX_SESSION_STEPS, MAX_TOTAL_STEPS):
        raise ValueError('campaign caps must remain 104 sessions, 50 steps/session, 5,198 total')
    path = Path(path)
    ledger = migrate_ledger(json.loads(path.read_text(encoding='utf-8')))
    ledger['max_sessions'] = max_sessions
    ledger['steps_per_session'] = steps_per_session
    ledger['max_total_steps'] = max_total_steps
    ledger['state_revision'] += 1
    write_ledger(path, ledger)
    return {'max_sessions': max_sessions, 'steps_per_session': steps_per_session,
            'max_total_steps': max_total_steps, 'status': ledger['status']}


def validate_training_dispatch(ledger, inputs):
    validate_ledger(ledger)
    if not ledger['approved'] or not ledger.get('approval_reference'):
        raise ValueError('training dispatch is blocked until campaign approval is recorded')
    if inputs.get('campaign_id') != CAMPAIGN_ID:
        raise ValueError('training dispatch campaign_id mismatch')
    if inputs.get('notebook') != 'notebooks/p2a_train.ipynb' or inputs.get('mode') != 'full':
        raise ValueError('campaign dispatch must use the full P2a training notebook')
    if inputs.get('executor') != 'lv1' or inputs.get('gpu') != 'T4':
        raise ValueError('campaign dispatch must use the approved lv1/T4 profile')
    if inputs.get('train_profile') not in {'train_tk4', 'train_tk5', 'train_tk1', 'train_tk6'}:
        raise ValueError('campaign dispatch requires an approved named training profile')
    save_steps = str(inputs.get('save_steps'))
    if inputs.get('training_approval_ref') != ledger['approval_reference']:
        raise ValueError('training dispatch approval reference mismatch')
    if inputs.get('p2a_v2_dataset_revision') != DATASET_REVISION:
        raise ValueError('training dispatch dataset revision mismatch')
    max_steps = int(inputs.get('max_steps', 0))
    if not 1 <= max_steps <= MAX_TOTAL_STEPS:
        raise ValueError('training dispatch max_steps exceeds the campaign cap')
    chain_source = str(inputs.get('campaign_chain_source_run_id') or '')
    resume_checkpoint = str(inputs.get('resume_checkpoint') or '')
    if not ledger['sessions'] and not ledger['dispatch_intents']:
        if chain_source or resume_checkpoint or max_steps != MAX_SESSION_STEPS or save_steps != '25':
            raise ValueError('first campaign session must be a clean 50-step base-model start')
        return {'dispatch_allowed': True, 'session_kind': 'initial', 'max_steps': max_steps}
    if ledger['status'] != 'active' or not ledger['training_workflow_ready']:
        raise ValueError('continuation dispatch blocked until the prior verified session marks campaign ready')
    try:
        source_run_id = int(chain_source)
    except (TypeError, ValueError) as error:
        raise ValueError('continuation requires campaign_chain_source_run_id') from error
    intent = next((item for item in reversed(ledger['dispatch_intents'])
                   if item.get('source_run_id') == source_run_id
                   and item.get('status') in {'dispatching', 'submitted'}), None)
    if not intent:
        raise ValueError('continuation does not match a submitted ledger dispatch intent')
    expected_save_steps = str(MAX_TOTAL_STEPS if max_steps == MAX_TOTAL_STEPS else MAX_SESSION_STEPS // 2)
    if save_steps != expected_save_steps:
        raise ValueError('campaign continuation save cadence is invalid')
    expected = intent.get('inputs') or {}
    for key in ('campaign_id', 'training_approval_ref', 'p2a_v2_dataset_revision',
                'max_steps', 'resume_checkpoint', 'campaign_chain_source_run_id',
                'notebook', 'mode', 'executor', 'gpu', 'train_profile', 'save_steps', 'timeout'):
        if str(inputs.get(key) or '') != str(expected.get(key) or ''):
            raise ValueError(f'continuation input mismatch: {key}')
    return {'dispatch_allowed': True, 'session_kind': 'continuation',
            'source_run_id': source_run_id, 'max_steps': max_steps,
            'resume_checkpoint': resume_checkpoint}


def mark_dispatch_state(ledger, intent_id, status):
    validate_ledger(ledger)
    transitions = {'dispatching': {'prepared'}, 'submitted': {'dispatching'}}
    if status not in transitions:
        raise ValueError('unsupported campaign dispatch transition')
    intent = next((item for item in ledger['dispatch_intents']
                   if item.get('intent_id') == intent_id), None)
    if not intent or intent.get('status') not in transitions[status]:
        raise ValueError('campaign dispatch intent transition is not allowed')
    intent['status'] = status
    intent[f'{status}_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    ledger['state_revision'] += 1
    return True


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
    caps = subparsers.add_parser('set-caps', help='set the approved campaign-wide caps')
    caps.add_argument('--ledger', required=True)
    caps.add_argument('--max-sessions', type=int, default=MAX_SESSIONS)
    caps.add_argument('--steps-per-session', type=int, default=MAX_SESSION_STEPS)
    caps.add_argument('--max-total-steps', type=int, default=MAX_TOTAL_STEPS)
    check = subparsers.add_parser('validate-dispatch', help='fail closed on campaign training inputs')
    check.add_argument('--ledger', required=True)
    check.add_argument('--inputs', required=True)
    mark_dispatching = subparsers.add_parser('mark-dispatching', help='persist intent before dispatch')
    mark_dispatching.add_argument('--ledger', required=True)
    mark_dispatching.add_argument('--intent-id', required=True)
    mark_submitted = subparsers.add_parser('mark-submitted', help='persist accepted dispatch state')
    mark_submitted.add_argument('--ledger', required=True)
    mark_submitted.add_argument('--intent-id', required=True)
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
    elif args.command == 'approve':
        result = record_approval(args.ledger, args.approval_reference, args.approved_at)
    elif args.command == 'set-caps':
        result = set_campaign_caps(args.ledger, args.max_sessions,
                                   args.steps_per_session, args.max_total_steps)
    elif args.command == 'validate-dispatch':
        inputs = json.loads(Path(args.inputs).read_text(encoding='utf-8'))
        result = validate_training_dispatch(
            migrate_ledger(json.loads(Path(args.ledger).read_text(encoding='utf-8'))), inputs)
    else:
        ledger = migrate_ledger(json.loads(Path(args.ledger).read_text(encoding='utf-8')))
        status = 'dispatching' if args.command == 'mark-dispatching' else 'submitted'
        mark_dispatch_state(ledger, args.intent_id, status)
        write_ledger(args.ledger, ledger)
        result = {'intent_id': args.intent_id, 'status': status}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    raise SystemExit(main())
