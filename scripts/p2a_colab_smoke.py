#!/usr/bin/env python3
"""Run a bounded P2a gradient smoke on Colab, TK2 then TK5 only on assign 503."""
import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from p2a_eval_async import LOCK_ROOT, stage_profile
from p2a_train import dataset_label_spec

ASSIGN_503 = re.compile(
    r'/tun/m/assign(?![A-Za-z0-9_-])[^\n]*503|503[^\n]*/tun/m/assign(?![A-Za-z0-9_-])',
    re.I)
GRAD_NORM = re.compile(r"grad_norm['\"]?\s*[:=]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|nan|inf)", re.I)


def should_fallback_to_tk5(profile, output):
    return profile == 'tk2' and bool(ASSIGN_503.search(output))


def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run_profile(profile, train_path, max_steps, timeout, work_dir):
    try:
        home = stage_profile(profile)
    except Exception as error:  # Keep diagnostics redacted; never serialize credentials or email.
        return {
            'profile': profile, 'return_code': None, 'result_ok': False,
            'requested_max_steps': max_steps, 'finite_gradient_norm_count': 0,
            'nonfinite_guard_triggered': False, 'assign_503': False, 'ok': False,
            'error_type': type(error).__name__,
            'sha256_train_slice': digest(train_path),
            'md5_train_slice': digest(train_path, 'md5'), 'log': '',
        }
    try:
        env = os.environ.copy()
        env.update({
            'VNCOLAB_HOME': str(home),
            'MODE': 'smoke',
            'MAX_STEPS': str(max_steps),
            'SAVE_STEPS': '1',
            'TRAIN_URL': '/content/p2a_train_v2_smoke.jsonl',
            'TRAIN_MD5': digest(train_path, 'md5'),
            'HOLDOUT_URL': '/content/p2a_train_v2_smoke.jsonl',
            'HOLDOUT_MD5': digest(train_path, 'md5'),
            'P2A_LOCAL_TRAIN': '1',
            'SKIP_EVAL': '1',
            'UPLOAD_HF': '0',
            'HF_CHECKPOINT_REPO': '',
            'P2_EVAL_ENABLED': '0',
            'OUTPUT_DIR': '/content/p2a-v2-gradient-smoke',
        })
        result_path = Path(work_dir) / f'colab-{profile}.json'
        command = [
            sys.executable, str(Path(__file__).with_name('vncolab.py')), 'run',
            'notebooks/p2a_train.ipynb', '--gpu', 'T4', '--timeout', str(timeout),
            '--out', str(result_path), '--mode', 'smoke', '--max-steps', str(max_steps),
            '--save-steps', '1', '--upload-file', str(train_path),
            '/content/p2a_train_v2_smoke.jsonl',
        ]
        try:
            proc = subprocess.run(command, env=env, capture_output=True, text=True,
                                  timeout=timeout + 300, check=False)
        except subprocess.TimeoutExpired:
            return {
                'profile': profile, 'return_code': 124, 'result_ok': False,
                'requested_max_steps': max_steps, 'finite_gradient_norm_count': 0,
                'nonfinite_guard_triggered': False, 'assign_503': False, 'ok': False,
                'error_type': 'TimeoutExpired',
                'sha256_train_slice': digest(train_path),
                'md5_train_slice': digest(train_path, 'md5'), 'log': '',
            }
        result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.is_file() else {}
        combined = (proc.stdout or '') + '\n' + (proc.stderr or '')
        if result:
            combined += '\n' + json.dumps(result, ensure_ascii=False)
        grad_norms = []
        for match in GRAD_NORM.finditer(combined):
            try:
                grad_norms.append(float(match.group(1)))
            except ValueError:
                grad_norms.append(math.nan)
        finite = [value for value in grad_norms if math.isfinite(value)]
        guard_failed = 'Non-finite P2a gradient' in combined or 'Non-finite P2a loss' in combined
        assign_503 = bool(ASSIGN_503.search(combined))
        ok = proc.returncode == 0 and result.get('ok') is True and not guard_failed
        return {
            'profile': profile,
            'return_code': proc.returncode,
            'result_ok': result.get('ok') is True,
            'requested_max_steps': max_steps,
            'finite_gradient_norm_count': len(finite),
            'nonfinite_guard_triggered': guard_failed,
            'assign_503': assign_503,
            'ok': ok,
            'sha256_train_slice': digest(train_path),
            'md5_train_slice': digest(train_path, 'md5'),
            'log': combined,
        }
    finally:
        shutil.rmtree(home, ignore_errors=True)


def run_smoke(train_path, max_steps=2, timeout=3600, output=None):
    if max_steps < 1 or max_steps > 50:
        raise ValueError('smoke max_steps must be from 1 to 50')
    spec = dataset_label_spec(train_path)
    if spec.get('label_version') != 2:
        raise ValueError('Colab gradient smoke refuses non-v2 labels')
    with tempfile.TemporaryDirectory(prefix='p2a-colab-smoke-') as temp:
        lock_path = LOCK_ROOT / 'queue' / 'worker.lock'
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a+') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('TK2/TK5 Colab slot is busy with an evaluation; retry after it completes') from error
            tk2 = run_profile('tk2', train_path, max_steps, timeout, temp)
            attempts = [tk2]
            if should_fallback_to_tk5('tk2', tk2.get('log', '')):
                tk5 = run_profile('tk5', train_path, max_steps, timeout, temp)
                attempts.append(tk5)
            final = attempts[-1]
            report = {
                'label_version': 2,
                'smoke_only': True,
                'full_training_started': False,
                'max_steps': max_steps,
                'training_dataset_sha256': digest(train_path),
                'attempts': [{key:value for key,value in attempt.items() if key!='log'}
                             for attempt in attempts],
                'passes': final['ok'] and final['finite_gradient_norm_count'] > 0,
                'blocked_by': None,
            }
            if output:
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n',
                                        encoding='utf-8')
            if not report['passes']:
                raise RuntimeError('bounded v2 Colab smoke failed; inspect private local log')
            return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train',required=True)
    parser.add_argument('--max-steps',type=int,default=2)
    parser.add_argument('--timeout',type=int,default=3600)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=run_smoke(args.train,args.max_steps,args.timeout,args.output)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
