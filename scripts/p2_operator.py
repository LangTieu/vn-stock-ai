#!/usr/bin/env python3
"""Single P2 operator interface for side-effect-free train/evaluate plans."""
import argparse
import json
import os
import subprocess

from p2_campaign import load_json, plan_operation, validate_manifest


def gh_dispatch_args(plan):
    if plan.get('decision') == 'blocked':
        raise ValueError('cannot dispatch a blocked plan')
    workflow = plan['workflow']
    args = ['gh', 'workflow', 'run', workflow, '--ref', plan['ref']]
    for key, value in sorted(plan.get('inputs', {}).items()):
        args.extend(['-f', f'{key}={value}'])
    if not all(isinstance(item, str) for item in args):
        raise TypeError('subprocess argv values must all be strings')
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('train', 'evaluate'))
    parser.add_argument('--manifest', default='docs/p2-campaign.json')
    parser.add_argument('--checkpoint-step', default='latest')
    parser.add_argument('--dispatch', action='store_true',
                        help='Execute only an approved, ready plan; omitted means dry-run')
    args = parser.parse_args()
    manifest = load_json(args.manifest)
    validate_manifest(manifest)
    plan = plan_operation(manifest, args.operation, args.checkpoint_step)
    plan['dry_run'] = not args.dispatch
    if args.dispatch:
        if plan.get('decision') == 'blocked':
            raise SystemExit('Dispatch refused: ' + '; '.join(plan.get('blocked_reasons', [])))
        if args.operation == 'train':
            approval_ref = (manifest.get('training_approval') or {}).get('approval_reference')
            if not approval_ref or os.environ.get('P2_TRAIN_APPROVAL_REF', '') != approval_ref:
                raise SystemExit('Training dispatch refused: protected approval reference is missing or mismatched.')
            if not manifest.get('training_workflow_ready'):
                raise SystemExit('Training dispatch remains disabled until the v2 full-training workflow is certified ready.')
        command = gh_dispatch_args(plan)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        print(json.dumps({'command': command, 'return_code': result.returncode,
                          'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()},
                         ensure_ascii=False, indent=2))
        return result.returncode
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if plan['decision'] != 'blocked' else 2


if __name__ == '__main__':
    raise SystemExit(main())
