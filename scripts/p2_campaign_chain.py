#!/usr/bin/env python3
"""Plan and persist safe continuations for the approved P2a V2 campaign."""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from p2_campaign_ledger import (
    CAMPAIGN_ID, CAMPAIGN_REF, DATASET_REVISION, MAX_SESSIONS, MAX_SESSION_STEPS,
    MAX_TOTAL_STEPS, validate_ledger, write_ledger,
)

TRAIN_REPO = 'Jerlob/vn-stock-ai-p2a-checkpoints'
TRAIN_SHA256 = 'aaa239c33f7d6891bdc0dc5dd8cace00ff72075cf230bfeaa35aafac6a4978fe'
VALIDATION_SHA256 = '5ab54b64d5576eeeea2ffe849baaa1f494028916f1bac209a00ec38638e3f175'
LABEL_METHOD = 'adjusted_total_return_close; 120 exchange sessions after as_of'
CHECKPOINT_REQUIRED_FILES = {
    'optimizer.pt', 'scheduler.pt', 'trainer_state.json', 'rng_state.pth',
    'adapter_config.json', 'p2a_training_manifest.json',
}
ADAPTER_FILES = {'adapter_model.safetensors', 'adapter_model.bin'}


def _positive_int(value, name):
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{name} must be an integer') from error
    if number <= 0:
        raise ValueError(f'{name} must be positive')
    return number


def _is_true(value):
    return value is True or str(value).lower() == 'true'


def _eligible_run_context(event, context, ledger):
    if not isinstance(context, dict):
        return False, 'run-context artifact missing'
    if event.get('status') != 'completed' or event.get('conclusion') != 'success':
        return False, 'source workflow did not complete successfully'
    if event.get('head_branch') != CAMPAIGN_REF:
        return False, 'source workflow ref is not main'
    if int(context.get('run_id', -1)) != int(event['run_id']):
        return False, 'run-context source ID mismatch'
    if context.get('head_sha') != event.get('head_sha'):
        return False, 'run-context SHA mismatch'
    if context.get('workflow_ref') != CAMPAIGN_REF:
        return False, 'run-context ref mismatch'
    if context.get('campaign_id') != CAMPAIGN_ID:
        return False, 'run is not tagged for p2a-v2-full'
    if context.get('notebook') != 'notebooks/p2a_train.ipynb' or context.get('mode') != 'full':
        return False, 'completed run is not full P2a training'
    if any(_is_true(context.get(key)) for key in (
            'drive_inventory', 'hf_source_audit', 'p2a_v2_smoke', 'p2a_v2_ablation')):
        return False, 'source workflow was read-only, smoke, or ablation'
    if context.get('training_approval_ref') != ledger.get('approval_reference'):
        return False, 'source run approval reference does not match campaign ledger'
    if context.get('p2a_v2_dataset_revision') != DATASET_REVISION:
        return False, 'source run dataset revision does not match campaign ledger'
    if context.get('executor') != 'lv1':
        return False, 'source run did not use the approved lv1 executor'
    if context.get('gpu') != 'T4':
        return False, 'source run GPU differs from the approved T4 campaign profile'
    source_save_steps = _positive_int(context.get('save_steps'), 'save_steps')
    source_max_steps = _positive_int(context.get('max_steps'), 'max_steps')
    if source_save_steps != 25 and not (
            source_max_steps == MAX_TOTAL_STEPS and source_save_steps == MAX_TOTAL_STEPS):
        return False, 'source run save_steps differs from the 25-step or final-cap save rule'
    if _positive_int(context.get('timeout'), 'timeout') != 28800:
        return False, 'source run timeout differs from the approved 8-hour session cap'
    if context.get('train_profile') not in {'train_tk4', 'train_tk5', 'train_tk1'}:
        return False, 'source run does not identify an approved training profile'
    if not ledger.get('approved') or not ledger.get('approval_reference'):
        return False, 'campaign approval is not recorded'
    return True, 'eligible full campaign session'


def validate_checkpoint(checkpoint, context, ledger):
    if not isinstance(checkpoint, dict):
        raise ValueError('no complete checkpoint was found in the private checkpoint repo')
    step = _positive_int(checkpoint.get('step'), 'checkpoint step')
    if checkpoint.get('name') != f'checkpoint-{step}':
        raise ValueError('checkpoint name/step mismatch')
    requested_max = _positive_int(context.get('max_steps'), 'source max_steps')
    if step != requested_max:
        raise ValueError('latest complete checkpoint does not match source max_steps')
    files = set(checkpoint.get('files') or [])
    if not CHECKPOINT_REQUIRED_FILES <= files or not (ADAPTER_FILES & files):
        raise ValueError('checkpoint is missing optimizer/trainer/adapter files')
    training = checkpoint.get('training_manifest') or {}
    expected = {
        'label_version': 2,
        'train_sha256': TRAIN_SHA256,
        'dataset_validation_sha256': VALIDATION_SHA256,
        'dataset_repo': 'Jerlob/vn-stock-ai-p2a-v2',
        'dataset_revision': DATASET_REVISION,
        'label_method': LABEL_METHOD,
        'flat_band_pct': 2.0,
        'campaign_id': CAMPAIGN_ID,
        'training_approval_ref': ledger['approval_reference'],
    }
    mismatch = [key for key, value in expected.items() if training.get(key) != value]
    if mismatch:
        raise ValueError('checkpoint manifest mismatch: ' + ', '.join(mismatch))
    return {'name': checkpoint['name'], 'step': step}


def _mark_parent_intent_failed(ledger, event, context, reason):
    if not ledger['sessions'] or not context.get('campaign_chain_source_run_id'):
        return False
    parent_run_id = int(context['campaign_chain_source_run_id'])
    parent_intent = next((item for item in ledger['dispatch_intents']
                          if item.get('source_run_id') == parent_run_id
                          and item.get('status') in {'dispatching', 'submitted'}), None)
    if not parent_intent:
        return False
    parent_intent['status'] = 'failed'
    parent_intent['child_run_id'] = int(event['run_id'])
    parent_intent['child_conclusion'] = event.get('conclusion')
    parent_intent['failure_reason'] = reason[:240]
    parent_intent['failed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    ledger['status'] = 'paused'
    ledger['state_revision'] += 1
    return True


def latest_complete_checkpoint(token, approval_reference, expected_step=None):
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=token)
    files = set(api.list_repo_files(repo_id=TRAIN_REPO, repo_type='model'))
    grouped = {}
    pattern = re.compile(r'checkpoints/checkpoint-(\d+)/(.+)')
    for path in files:
        match = pattern.fullmatch(path)
        if match:
            grouped.setdefault(int(match.group(1)), set()).add(match.group(2))
    for step in sorted(grouped, reverse=True):
        if expected_step is not None and step != _positive_int(expected_step, 'source max_steps'):
            continue
        names = grouped[step]
        if not CHECKPOINT_REQUIRED_FILES <= names or not (ADAPTER_FILES & names):
            continue
        manifest_path = hf_hub_download(
            repo_id=TRAIN_REPO, repo_type='model',
            filename=f'checkpoints/checkpoint-{step}/p2a_training_manifest.json', token=token)
        training = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        if (training.get('training_approval_ref') == approval_reference
                and training.get('campaign_id') == CAMPAIGN_ID
                and training.get('dataset_revision') == DATASET_REVISION
                and training.get('label_version') == 2
                and training.get('train_sha256') == TRAIN_SHA256
                and training.get('dataset_validation_sha256') == VALIDATION_SHA256
                and training.get('label_method') == LABEL_METHOD
                and training.get('flat_band_pct') == 2.0):
            return {'name': f'checkpoint-{step}', 'step': step,
                    'files': sorted(names), 'training_manifest': training}
    return None


def prepare_continuation(ledger, event, context, checkpoint):
    validate_ledger(ledger)
    if isinstance(context, dict):
        parent_value = context.get('campaign_chain_source_run_id')
        try:
            parent_run_id = int(parent_value) if parent_value else None
        except (TypeError, ValueError):
            parent_run_id = None
    else:
        parent_run_id = None
    eligible, reason = _eligible_run_context(event, context, ledger)
    if not eligible:
        failed_child_context = (isinstance(context, dict)
                                and context.get('campaign_id') == CAMPAIGN_ID
                                and str(context.get('run_id')) == str(event.get('run_id'))
                                and context.get('head_sha') == event.get('head_sha')
                                and context.get('notebook') == 'notebooks/p2a_train.ipynb'
                                and context.get('mode') == 'full'
                                and context.get('training_approval_ref') == ledger.get('approval_reference')
                                and context.get('p2a_v2_dataset_revision') == DATASET_REVISION)
        if (failed_child_context and event.get('status') == 'completed'
                and event.get('conclusion') != 'success'
                and parent_run_id is not None):
            failed_intent = next((item for item in ledger['dispatch_intents']
                                  if item.get('source_run_id') == parent_run_id
                                  and item.get('status') in {'dispatching', 'submitted'}), None)
            if failed_intent:
                failed_intent['status'] = 'failed'
                failed_intent['child_run_id'] = int(event['run_id'])
                failed_intent['child_conclusion'] = event.get('conclusion')
                failed_intent['failed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                ledger['status'] = 'paused'
                ledger['state_revision'] += 1
                return {'decision': 'continuation_failed_manual_review', 'dispatch': False,
                        'ledger_changed': True, 'reason': reason}
        return {'decision': 'no_chain', 'reason': reason, 'dispatch': False,
                'ledger_changed': False}
    source_run_id = int(event['run_id'])
    if any(session['source_run_id'] == source_run_id for session in ledger['sessions']):
        intent = next((item for item in ledger['dispatch_intents']
                       if item.get('source_run_id') == source_run_id), None)
        if intent and intent.get('status') == 'prepared':
            return {'decision': 'dispatch_prepared', 'dispatch': True,
                    'ledger_changed': False, 'intent_id': intent['intent_id'],
                    'inputs': intent['inputs'], 'checkpoint': ledger.get('latest_v2_compatible_checkpoint')}
        return {'decision': 'duplicate_session', 'dispatch': False, 'ledger_changed': False}
    try:
        checkpoint_info = validate_checkpoint(checkpoint, context, ledger)
    except ValueError as error:
        changed = _mark_parent_intent_failed(ledger, event, context, str(error))
        return {'decision': 'no_chain_checkpoint_rejected', 'reason': str(error),
                'dispatch': False, 'ledger_changed': changed}
    sessions = ledger['sessions']
    prior_step = int(sessions[-1]['end_step']) if sessions else 0
    if sessions:
        parent_run_id = int(sessions[-1]['source_run_id'])
        if str(context.get('campaign_chain_source_run_id') or '') != str(parent_run_id):
            return {'decision': 'no_chain_parent_mismatch', 'dispatch': False,
                    'ledger_changed': False}
        if context.get('resume_checkpoint') != sessions[-1]['checkpoint_name']:
            return {'decision': 'no_chain_resume_mismatch', 'dispatch': False,
                    'ledger_changed': False}
        parent_intent = next((intent for intent in reversed(ledger['dispatch_intents'])
                              if intent['source_run_id'] == parent_run_id
                              and intent['status'] in {'dispatching', 'submitted'}), None)
        if not parent_intent:
            return {'decision': 'no_chain_parent_intent_unconfirmed', 'dispatch': False,
                    'ledger_changed': False}
        parent_intent['status'] = 'completed'
        parent_intent['child_run_id'] = source_run_id
        parent_intent['child_sha'] = event['head_sha']
        parent_intent['completed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    elif context.get('resume_checkpoint') or context.get('campaign_chain_source_run_id'):
        return {'decision': 'no_chain_initial_session_has_resume', 'dispatch': False,
                'ledger_changed': False}

    step = checkpoint_info['step']
    steps_this_session = step - prior_step
    if steps_this_session <= 0 or steps_this_session > MAX_SESSION_STEPS:
        return {'decision': 'no_chain_step_window', 'dispatch': False, 'ledger_changed': False}
    if step > MAX_TOTAL_STEPS:
        return {'decision': 'checkpoint_exceeds_campaign_cap', 'dispatch': False,
                'ledger_changed': False}
    if len(sessions) >= MAX_SESSIONS:
        return {'decision': 'campaign_session_cap_reached', 'dispatch': False,
                'ledger_changed': False}

    ledger['training_workflow_ready'] = True
    ledger['status'] = 'active'
    sessions.append({
        'source_run_id': source_run_id,
        'source_sha': event['head_sha'],
        'start_step': prior_step,
        'end_step': step,
        'steps': steps_this_session,
        'checkpoint_name': checkpoint_info['name'],
        'dataset_revision': DATASET_REVISION,
        'approval_reference': ledger['approval_reference'],
        'campaign_chain_source_run_id': context.get('campaign_chain_source_run_id') or None,
        'profile': context['train_profile'],
    })
    ledger['latest_v2_compatible_checkpoint'] = checkpoint_info

    if step >= MAX_TOTAL_STEPS or len(sessions) >= MAX_SESSIONS:
        ledger['status'] = 'completed'
        ledger['state_revision'] += 1
        return {'decision': 'campaign_complete', 'dispatch': False,
                'checkpoint': checkpoint_info, 'ledger_changed': True}

    next_max = min(step + MAX_SESSION_STEPS, MAX_TOTAL_STEPS)
    intent_id = f'{CAMPAIGN_ID}:{source_run_id}'
    if any(intent['intent_id'] == intent_id for intent in ledger['dispatch_intents']):
        return {'decision': 'duplicate_dispatch_intent', 'dispatch': False,
                'ledger_changed': False}
    inputs = {
        'notebook': 'notebooks/p2a_train.ipynb',
        'mode': 'full',
        'training_approval_ref': ledger['approval_reference'],
        'gpu': str(context.get('gpu') or 'T4'),
        'timeout': str(_positive_int(context.get('timeout') or 28800, 'timeout')),
        'max_steps': str(next_max),
        'resume_checkpoint': checkpoint_info['name'],
        'p2a_v2_dataset_revision': DATASET_REVISION,
        'save_steps': str(next_max if next_max == MAX_TOTAL_STEPS else MAX_SESSION_STEPS // 2),
        'executor': 'lv1',
        'train_profile': context['train_profile'],
        'campaign_id': CAMPAIGN_ID,
        'campaign_chain_source_run_id': str(source_run_id),
    }
    if not all(isinstance(value, str) for value in inputs.values()):
        raise TypeError('all chained workflow inputs must be strings')
    ledger['dispatch_intents'].append({
        'intent_id': intent_id,
        'source_run_id': source_run_id,
        'source_sha': event['head_sha'],
        'target_max_steps': next_max,
        'resume_checkpoint': checkpoint_info['name'],
        'dataset_revision': DATASET_REVISION,
        'approval_reference': ledger['approval_reference'],
        'status': 'prepared',
        'inputs': inputs,
        'prepared_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    })
    ledger['state_revision'] += 1
    return {'decision': 'dispatch_prepared', 'dispatch': True, 'ledger_changed': True,
            'intent_id': intent_id, 'checkpoint': checkpoint_info, 'inputs': inputs}


def mark_dispatch_state(ledger, intent_id, status):
    validate_ledger(ledger)
    transitions = {'dispatching': 'prepared', 'submitted': 'dispatching'}
    if status not in transitions:
        raise ValueError('unsupported dispatch state')
    intent = next((item for item in ledger['dispatch_intents']
                   if item['intent_id'] == intent_id), None)
    if not intent or intent['status'] != transitions[status]:
        raise ValueError('campaign dispatch intent transition is not allowed')
    intent['status'] = status
    intent[f'{status}_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    ledger['state_revision'] += 1
    return True


def prepare_retry(ledger, parent_run_id, failed_run_id, train_profile=None):
    validate_ledger(ledger)
    parent_run_id = _positive_int(parent_run_id, 'parent_run_id')
    failed_run_id = _positive_int(failed_run_id, 'failed_run_id')
    failure_event = next((event for event in ledger['events']
                          if event['source_run_id'] == failed_run_id), None)
    if not failure_event or failure_event['conclusion'] != 'failure':
        raise ValueError('manual continuation retry requires a recorded failed child event')
    parent = next((item for item in ledger['dispatch_intents']
                   if item.get('source_run_id') == parent_run_id
                   and item.get('status') == 'failed'
                   and item.get('child_run_id') == failed_run_id), None)
    if not parent:
        raise ValueError('failed child does not match a failed parent dispatch intent')
    session = next((item for item in ledger['sessions']
                    if item.get('source_run_id') == parent_run_id), None)
    checkpoint = ledger.get('latest_v2_compatible_checkpoint') or {}
    if (not session or checkpoint.get('name') != session.get('checkpoint_name')
            or checkpoint.get('step') != session.get('end_step')):
        raise ValueError('retry checkpoint does not match the latest committed campaign session')
    if any(item.get('source_run_id') == failed_run_id for item in ledger['sessions']):
        raise ValueError('failed child already has a committed campaign session')
    if any(item['status'] in {'prepared', 'dispatching', 'submitted'}
           for item in ledger['dispatch_intents']):
        raise ValueError('another campaign dispatch intent is still pending')

    inputs = dict(parent.get('inputs') or {})
    profile = train_profile or inputs.get('train_profile')
    if profile not in {'train_tk4', 'train_tk5', 'train_tk1'}:
        raise ValueError('retry requires an approved named training profile')
    target_step = _positive_int(inputs.get('max_steps'), 'target max_steps')
    current_step = session['end_step']
    if (target_step > MAX_TOTAL_STEPS or target_step <= current_step
            or target_step - current_step > MAX_SESSION_STEPS):
        raise ValueError('retry target exceeds the per-session or campaign step cap')
    if (inputs.get('resume_checkpoint') != checkpoint.get('name')
            or inputs.get('training_approval_ref') != ledger.get('approval_reference')
            or inputs.get('p2a_v2_dataset_revision') != DATASET_REVISION):
        raise ValueError('retry inputs do not match the committed checkpoint campaign lineage')
    inputs['train_profile'] = profile
    inputs['campaign_chain_source_run_id'] = str(parent_run_id)
    retries = [item for item in ledger['dispatch_intents']
               if item.get('source_run_id') == parent_run_id
               and ':retry:' in item.get('intent_id', '')]
    intent_id = f'{CAMPAIGN_ID}:{parent_run_id}:retry:{len(retries) + 1}'
    ledger['dispatch_intents'].append({
        'intent_id': intent_id,
        'source_run_id': parent_run_id,
        'source_sha': session.get('source_sha'),
        'target_max_steps': target_step,
        'resume_checkpoint': checkpoint['name'],
        'dataset_revision': DATASET_REVISION,
        'approval_reference': ledger['approval_reference'],
        'status': 'prepared',
        'inputs': inputs,
        'retry_of_intent_id': parent['intent_id'],
        'retry_after_run_id': failed_run_id,
        'prepared_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    })
    ledger['status'] = 'active'
    ledger['training_workflow_ready'] = True
    ledger['state_revision'] += 1
    return {'decision': 'dispatch_prepared', 'dispatch': True, 'ledger_changed': True,
            'intent_id': intent_id, 'checkpoint': checkpoint, 'inputs': inputs}


def dispatch_argv(plan):
    if not plan.get('dispatch') or plan.get('decision') != 'dispatch_prepared':
        raise ValueError('refusing to dispatch a non-ready campaign plan')
    inputs = plan.get('inputs') or {}
    argv = ['gh', 'workflow', 'run', 'run-colab.yml', '--ref', CAMPAIGN_REF]
    for key in sorted(inputs):
        argv.extend(['-f', f'{key}={inputs[key]}'])
    if not all(isinstance(value, str) for value in argv):
        raise TypeError('workflow dispatch argv must contain strings only')
    return argv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=(
        'plan', 'dispatch', 'mark-dispatching', 'mark-submitted', 'prepare-retry'))
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--event')
    parser.add_argument('--context')
    parser.add_argument('--checkpoint-fixture')
    parser.add_argument('--plan-file')
    parser.add_argument('--intent-id')
    parser.add_argument('--parent-run-id')
    parser.add_argument('--failed-run-id')
    parser.add_argument('--train-profile')
    parser.add_argument('--output')
    args = parser.parse_args()
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
    if args.command == 'plan':
        if not args.event or not args.context:
            raise SystemExit('event and context JSON are required')
        event = json.loads(Path(args.event).read_text(encoding='utf-8'))
        context = json.loads(Path(args.context).read_text(encoding='utf-8'))
        eligible, _ = _eligible_run_context(event, context, ledger)
        if not eligible:
            checkpoint = None
        elif args.checkpoint_fixture:
            checkpoint = json.loads(Path(args.checkpoint_fixture).read_text(encoding='utf-8'))
        else:
            token = os.environ.get('HF_TOKEN')
            if not token:
                raise RuntimeError('HF_TOKEN is required to inspect checkpoints')
            checkpoint = latest_complete_checkpoint(token, ledger.get('approval_reference') or '',
                                                   context.get('max_steps'))
        result = prepare_continuation(ledger, event, context, checkpoint)
        if result.get('ledger_changed'):
            write_ledger(ledger_path, ledger)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, sort_keys=True))
    elif args.command == 'dispatch':
        if not args.plan_file:
            raise SystemExit('--plan-file is required')
        plan = json.loads(Path(args.plan_file).read_text(encoding='utf-8'))
        argv = dispatch_argv(plan)
        subprocess.run(argv, check=True, env={**os.environ, 'GH_TOKEN': os.environ['GH_TOKEN']})
        print(json.dumps({'dispatched': True, 'intent_id': plan['intent_id']}, sort_keys=True))
    elif args.command == 'prepare-retry':
        if not args.parent_run_id or not args.failed_run_id:
            raise SystemExit('--parent-run-id and --failed-run-id are required')
        result = prepare_retry(ledger, args.parent_run_id, args.failed_run_id,
                               args.train_profile)
        write_ledger(ledger_path, ledger)
        print(json.dumps(result, sort_keys=True))
    else:
        if not args.intent_id:
            raise SystemExit('--intent-id is required')
        target = 'dispatching' if args.command == 'mark-dispatching' else 'submitted'
        mark_dispatch_state(ledger, args.intent_id, target)
        write_ledger(ledger_path, ledger)
        print(json.dumps({'status': target, 'intent_id': args.intent_id}, sort_keys=True))


if __name__ == '__main__':
    main()
