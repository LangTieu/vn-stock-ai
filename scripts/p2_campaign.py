#!/usr/bin/env python3
"""Fail-closed P2 campaign planner. Planning/dry-run never dispatches workflows."""
import argparse
import json
from pathlib import Path

REQUIRED_CHECKPOINT_FILES = {
    'optimizer.pt', 'scheduler.pt', 'trainer_state.json', 'rng_state.pth',
    'adapter_config.json', 'p2a_training_manifest.json',
}
ADAPTER_FILES = {'adapter_model.safetensors', 'adapter_model.bin'}
CAMPAIGN_REF = 'main'
CAMPAIGN_MAX_SESSION_STEPS = 50
CAMPAIGN_MAX_TOTAL_STEPS = 5198
CAMPAIGN_MAX_SESSIONS = 104


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_manifest(manifest):
    if manifest.get('schema_version') != 1:
        raise ValueError('unsupported campaign manifest schema_version')
    if not manifest.get('campaign_id'):
        raise ValueError('campaign_id is required')
    if manifest.get('ref') != CAMPAIGN_REF:
        raise ValueError(f'campaign_ref must equal {CAMPAIGN_REF!r}')
    dataset = manifest.get('dataset') or {}
    if dataset.get('label_version') != 2 or dataset.get('repo_id') != 'Jerlob/vn-stock-ai-p2a-v2':
        raise ValueError('campaign must target the private P2a V2 dataset repository and label-version 2')
    limits = manifest.get('limits') or {}
    if not all(isinstance(limits.get(key), int) and limits[key] > 0
               for key in ('max_sessions', 'steps_per_session', 'max_total_steps')):
        raise ValueError('positive max_sessions, steps_per_session, and max_total_steps are required')
    if limits != {'max_sessions': CAMPAIGN_MAX_SESSIONS,
                  'steps_per_session': CAMPAIGN_MAX_SESSION_STEPS,
                  'max_total_steps': CAMPAIGN_MAX_TOTAL_STEPS}:
        raise ValueError('campaign limits must remain 104 sessions, 50 steps/session, 5,198 total')
    profiles = manifest.get('profiles') or {}
    for key, expected in (('training_order', ['train_tk4', 'train_tk5', 'train_tk1', 'train_tk6']),
                          ('evaluation_order', ['eval_tk2', 'eval_tk5'])):
        if profiles.get(key) != expected:
            raise ValueError(f'{key} must be {expected!r}')
    if 'token' in json.dumps(manifest, ensure_ascii=True).lower():
        raise ValueError('credential material/fields are forbidden in the campaign manifest')
    return True


def checkpoint_is_v2_compatible(checkpoint, dataset, approval_reference=None):
    if not checkpoint:
        return False, 'no checkpoint supplied'
    files = set(checkpoint.get('files') or [])
    if not REQUIRED_CHECKPOINT_FILES <= files or not (ADAPTER_FILES & files):
        return False, 'checkpoint artifact set is incomplete'
    manifest = checkpoint.get('training_manifest') or {}
    train_pin = (dataset.get('files') or {}).get('train-v2.jsonl')
    if isinstance(train_pin, dict): train_pin = train_pin.get('sha256')
    checks = {
        'label_version': dataset.get('label_version'),
        'train_sha256': train_pin,
        'dataset_revision': dataset.get('revision'),
        'label_method': dataset.get('label_method'),
        'flat_band_pct': dataset.get('flat_band_pct'),
        'campaign_id': 'p2a-v2-full',
    }
    if approval_reference:
        checks['training_approval_ref'] = approval_reference
    mismatches = [key for key, expected in checks.items() if manifest.get(key) != expected]
    if mismatches:
        return False, 'checkpoint training manifest mismatch: ' + ', '.join(mismatches)
    return True, 'v2 checkpoint manifest and complete artifact set match campaign data'


def _base_decision(operation, manifest):
    return {
        'campaign_id': manifest['campaign_id'],
        'operation': operation,
        'ref': manifest['ref'],
        'dispatch': False,
        'credentials_accessed': False,
    }


def plan_operation(manifest, operation, checkpoint_step=None):
    validate_manifest(manifest)
    if operation not in ('train', 'evaluate'):
        raise ValueError('operation must be train or evaluate')
    plan = _base_decision(operation, manifest)
    if operation == 'evaluate':
        checkpoint_step = str(checkpoint_step or 'latest')
        dataset = manifest['dataset']
        validation_pin = (dataset.get('files') or {}).get('validation-v2.jsonl')
        validation_sha = validation_pin.get('sha256') if isinstance(validation_pin, dict) else validation_pin
        if (not dataset.get('revision') or not dataset.get('signing_public_key_b64') or not validation_sha
                or not (dataset.get('file_md5') or {}).get('validation-v2.jsonl')):
            plan.update({'decision': 'blocked', 'blocked_reasons': [
                'private V2 dataset immutable revision, validation SHA-256, and trusted signing key are not pinned'
            ]})
            return plan
        plan.update({
            'decision': 'ready_for_operator_approval',
            'workflow': 'p2-eval.yml',
            'checkpoint_step': checkpoint_step,
            'full_holdout': False,
            'profile_order': list(manifest['profiles']['evaluation_order']),
            'fallback_only_on': manifest['profiles']['evaluation_fallback_only_on'],
            'inputs': {'checkpoint_step': checkpoint_step, 'full_holdout': 'false'},
            'note': 'Evaluation uses its own Colab runtime and cannot block or terminate a training run.',
        })
        return plan
    reasons = []
    approval = manifest.get('training_approval') or {}
    if approval.get('status') != 'approved' or not approval.get('approval_reference'):
        reasons.append('Henrry training approval is pending or has no recorded reference')
    if not manifest.get('training_workflow_ready'):
        reasons.append('v2 full-training workflow is not yet certified ready')
    dataset = manifest['dataset']
    train_pin = (dataset.get('files') or {}).get('train-v2.jsonl')
    validation_pin = (dataset.get('files') or {}).get('validation-v2.jsonl')
    train_sha = train_pin.get('sha256') if isinstance(train_pin, dict) else train_pin
    validation_sha = validation_pin.get('sha256') if isinstance(validation_pin, dict) else validation_pin
    if (not dataset.get('revision') or not dataset.get('signing_public_key_b64')
            or not train_sha or not validation_sha
            or not (dataset.get('file_md5') or {}).get('train-v2.jsonl')
            or not (dataset.get('file_md5') or {}).get('validation-v2.jsonl')):
        reasons.append('private V2 dataset immutable revision, train/validation SHA-256+MD5, and trusted signing key are not pinned')
    state = manifest.get('state') or {}
    sessions = state.get('sessions') or []
    limits = manifest['limits']
    used_steps = sum(int(item.get('steps', 0)) for item in sessions)
    if len(sessions) >= limits['max_sessions']:
        reasons.append('max_sessions cap reached')
    if used_steps >= limits['max_total_steps']:
        reasons.append('max_total_steps cap reached')
    if reasons:
        plan.update({'decision': 'blocked', 'blocked_reasons': reasons})
        return plan
    remaining = limits['max_total_steps'] - used_steps
    requested = min(limits['steps_per_session'], remaining)
    checkpoint = state.get('latest_checkpoint')
    if sessions:
        compatible, reason = checkpoint_is_v2_compatible(
            checkpoint, manifest['dataset'],
            (manifest.get('training_approval') or {}).get('approval_reference'))
        if not compatible:
            plan.update({'decision': 'blocked', 'blocked_reasons': [reason]})
            return plan
    elif checkpoint:
        compatible, reason = checkpoint_is_v2_compatible(
            checkpoint, manifest['dataset'],
            (manifest.get('training_approval') or {}).get('approval_reference'))
        if not compatible:
            plan.update({'decision': 'blocked', 'blocked_reasons': [reason]})
            return plan
    plan.update({
        'decision': 'ready_for_operator_approval',
        'workflow': 'run-colab.yml',
        'mode': 'full',
        'max_steps': used_steps + requested,
        'steps_this_session': requested,
        'resume_checkpoint': (checkpoint or {}).get('name', ''),
        'profile_order': list(manifest['profiles']['training_order']),
        'fallback_only_on': manifest['profiles']['training_fallback_only_on'],
        'inputs': {
            'notebook': 'notebooks/p2a_train.ipynb',
            'mode': 'full',
            'executor': 'lv1',
            'train_profile': manifest['profiles']['training_order'][0],
            'max_steps': str(used_steps + requested),
            'save_steps': '25',
        },
    })
    return plan


def plan_event(manifest, event, checkpoint=None):
    validate_manifest(manifest)
    run_id = str(event.get('run_id', ''))
    if not run_id:
        raise ValueError('source run_id is required')
    base = _base_decision('continue_training', manifest)
    base.update({'source_run_id': run_id, 'dispatch': False})
    seen = {str(value) for value in (manifest.get('state') or {}).get('seen_source_run_ids', [])}
    intents = {str(item.get('source_run_id')) for item in (manifest.get('state') or {}).get('dispatch_intents', [])}
    if run_id in seen or run_id in intents:
        base.update({'decision': 'already_seen', 'blocked_reasons': ['source run id is already recorded']})
        return base
    if event.get('status') != 'completed':
        base.update({'decision': 'source_not_completed', 'blocked_reasons': ['source workflow is still queued or running']})
        return base
    if event.get('conclusion') != 'success':
        profile = event.get('training_profile')
        assign_503 = (event.get('failure_kind') == 'colab_assignment'
                      and event.get('http_status') == 503
                      and event.get('endpoint') == '/tun/m/assign')
        order = manifest['profiles']['training_order']
        if assign_503 and profile in order and order.index(profile) + 1 < len(order):
            blocked = []
            approval = manifest.get('training_approval') or {}
            if approval.get('status') != 'approved' or not approval.get('approval_reference'):
                blocked.append('Henrry training approval is pending or has no recorded reference')
            if not manifest.get('training_workflow_ready'):
                blocked.append('v2 full-training workflow is not yet certified ready')
            if len((manifest.get('state') or {}).get('sessions') or []) >= manifest['limits']['max_sessions']:
                blocked.append('max_sessions cap reached')
            if blocked:
                base.update({'decision': 'approval_or_preflight_required', 'blocked_reasons': blocked})
                return base
            base.update({
                'decision': 'profile_fallback_plan_only',
                'blocked_reasons': ['confirmed Colab assignment HTTP 503; explicit next profile only'],
                'next_profile': order[order.index(profile) + 1],
                'dispatch': False,
            })
            return base
        base.update({'decision': 'manual_recovery_review', 'blocked_reasons': ['failed/cancelled runs never auto-chain except a confirmed assignment 503 fallback']})
        return base
    if event.get('head_branch') != manifest['ref']:
        base.update({'decision': 'ref_mismatch', 'blocked_reasons': ['event ref does not match campaign ref']})
        return base
    state = manifest.get('state') or {}
    if len(state.get('sessions') or []) >= manifest['limits']['max_sessions']:
        base.update({'decision': 'cap_reached', 'blocked_reasons': ['max_sessions cap reached']})
        return base
    if checkpoint is not None:
        compatible, reason = checkpoint_is_v2_compatible(
            checkpoint, manifest['dataset'],
            (manifest.get('training_approval') or {}).get('approval_reference'))
        if not compatible:
            base.update({'decision': 'checkpoint_rejected', 'blocked_reasons': [reason]})
            return base
    planning_manifest = json.loads(json.dumps(manifest))
    if checkpoint is not None:
        planning_manifest.setdefault('state', {})['latest_checkpoint'] = checkpoint
    plan = plan_operation(planning_manifest, 'train')
    base.update(plan)
    base['source_run_id'] = run_id
    if plan['decision'] == 'blocked':
        base['decision'] = 'approval_or_preflight_required'
    else:
        base['decision'] = 'eligible_plan_only'
        base['dispatch'] = False
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'event'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--manifest', required=True)
        cmd.add_argument('--output')
        if name == 'plan':
            cmd.add_argument('--operation', choices=('train', 'evaluate'), required=True)
            cmd.add_argument('--checkpoint-step')
        else:
            cmd.add_argument('--event', required=True, help='JSON file with run_id/status/conclusion/head_branch')
            cmd.add_argument('--checkpoint', help='JSON file containing complete files and v2 training_manifest')
    args = parser.parse_args()
    manifest = load_json(args.manifest)
    if args.command == 'plan':
        result = plan_operation(manifest, args.operation, args.checkpoint_step)
    else:
        result = plan_event(manifest, load_json(args.event), load_json(args.checkpoint) if args.checkpoint else None)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if args.output:
        Path(args.output).write_text(rendered, encoding='utf-8')
    print(rendered, end='')
    return 0 if result['decision'] not in ('blocked', 'manual_recovery_review', 'checkpoint_rejected') else 2


if __name__ == '__main__':
    raise SystemExit(main())
