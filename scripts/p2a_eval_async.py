#!/usr/bin/env python3
"""Run a checkpoint evaluation on a separate Colab account without blocking P2 training."""
import argparse
import csv
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ID = 'Jerlob/vn-stock-ai-p2a-checkpoints'
HOLDOUT_URL = 'https://huggingface.co/datasets/Jerlob/vn-stock-ai-p1/resolve/main/p1_holdout.jsonl'
LOCK_ROOT = Path.home() / '.cache/vn-stock-ai/p2-eval'
RESULT_ROOT = Path(os.environ.get('P2_EVAL_OUTPUT_DIR', str(Path.home() / 'p2-evaluations')))
TKN = ('openid', 'https://www.googleapis.com/auth/userinfo.profile',
       'https://www.googleapis.com/auth/userinfo.email',
       'https://www.googleapis.com/auth/cloud-platform',
       'https://www.googleapis.com/auth/colaboratory',
       'https://www.googleapis.com/auth/drive.file')


def token_candidate(profile):
    home = Path.home() / '.config/vncolab'
    options = (home / f'token.json.{profile}', home / profile / 'token.json',
               home / f'token_{profile}.json')
    return next((path for path in options if path.is_file()), None)


def stage_profile(profile):
    source = token_candidate(profile)
    if source is None:
        raise FileNotFoundError(f'Colab profile token file missing: {profile}')
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    staged_home = Path(tempfile.mkdtemp(prefix=f'p2-colab-{profile}-'))
    staged_home.chmod(0o700)
    try:
        token_path = staged_home / 'token.json'
        info = json.loads(source.read_text(encoding='utf-8'))
        creds = Credentials.from_authorized_user_info(info, list(TKN))
        if not creds.valid:
            if not creds.expired or not creds.refresh_token:
                raise RuntimeError(f'Colab profile {profile} cannot refresh')
            creds.refresh(Request())
        response = AuthorizedSession(creds).get(
            'https://www.googleapis.com/oauth2/v1/userinfo?alt=json', timeout=30)
        response.raise_for_status()
        email = response.json().get('email')
        expected = os.environ.get(f'P2_EVAL_{profile.upper()}_EMAIL')
        if not email or (expected and email.lower() != expected.lower()):
            raise RuntimeError(f'Colab profile {profile} userinfo verification failed')
        token_path.write_text(creds.to_json(), encoding='utf-8')
        token_path.chmod(0o600)
        return staged_home
    except Exception:
        shutil.rmtree(staged_home, ignore_errors=True)
        raise


def hf_repo_files(token):
    url = f'https://huggingface.co/api/models/{REPO_ID}/tree/main?recursive=true&expand=false'
    files = []
    while url:
        request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(request, timeout=60) as response:
            files.extend(item.get('path', '') for item in json.load(response))
            link = response.headers.get('Link', '')
        next_url = None
        for item in link.split(','):
            if 'rel="next"' in item:
                next_url = item[item.find('<') + 1:item.find('>')]
                break
        url = next_url
    return files


def checkpoint_complete(token, step):
    prefix = f'checkpoints/checkpoint-{step}/'
    files = {p[len(prefix):] for p in hf_repo_files(token) if p.startswith(prefix)}
    required = {'optimizer.pt', 'scheduler.pt', 'trainer_state.json', 'rng_state.pth',
                'adapter_config.json'}
    return required <= files and bool({'adapter_model.safetensors', 'adapter_model.bin'} & files)


def latest_complete_step(token):
    complete = []
    for path in hf_repo_files(token):
        match = re.fullmatch(r'checkpoints/checkpoint-(\d+)/(.+)', path)
        if match:
            complete.append((int(match.group(1)), match.group(2)))
    grouped = {}
    for step, name in complete:
        grouped.setdefault(step, set()).add(name)
    required = {'optimizer.pt', 'scheduler.pt', 'trainer_state.json', 'rng_state.pth',
                'adapter_config.json'}
    valid = [step for step, names in grouped.items()
             if required <= names and {'adapter_model.safetensors', 'adapter_model.bin'} & names]
    if not valid:
        raise RuntimeError(f'No complete checkpoint found in {REPO_ID}')
    return max(valid)


def build_remote_job(step, full_holdout, out_dir):
    train_src = Path(__file__).with_name('p2a_train.py').read_text(encoding='utf-8')
    eval_src = Path(__file__).with_name('p2a_eval.py').read_text(encoding='utf-8')
    validation_src = Path(__file__).with_name('p2a_validation.py').read_text(encoding='utf-8')
    lines = [
        'import csv, json, os, subprocess, sys, tempfile',
        'from pathlib import Path',
        "subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', "
        "'transformers==4.51.3', 'datasets==3.5.0', 'peft==0.15.2', "
        "'accelerate==1.6.0', 'bitsandbytes==0.48.2', "
        "'huggingface_hub==0.30.2', 'jinja2==3.1.6'], check=True)",
        "subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--force-reinstall', "
        "'--no-deps', '--only-binary=:all:', 'bitsandbytes==0.48.2'], check=True)",
        f"Path('/content/p2a_train.py').write_text({train_src!r}, encoding='utf-8')",
        f"Path('/content/p2a_eval.py').write_text({eval_src!r}, encoding='utf-8')",
        f"Path('/content/p2a_validation.py').write_text({validation_src!r}, encoding='utf-8')",
        "sys.path.insert(0, '/content')",
        'from huggingface_hub import HfApi, snapshot_download',
        'from p2a_train import HOLDOUT_MD5, dataset_path',
        'from p2a_validation import create_slice, file_hash',
        f"step={int(step)}",
        f"full_holdout={bool(full_holdout)!r}",
        f"repo={REPO_ID!r}",
        "token=os.environ['HF_TOKEN']",
        "api=HfApi(token=token)",
        "if not any(p.startswith(f'checkpoints/checkpoint-{step}/') for p in api.list_repo_files(repo_id=repo, repo_type='model')): raise RuntimeError(f'checkpoint-{step} is absent from HF')",
        "remote=f'checkpoints/checkpoint-{step}'",
        "snapshot=snapshot_download(repo_id=repo, repo_type='model', allow_patterns=[f'{remote}/*'], token=token)",
        "adapter=str(Path(snapshot)/remote)",
        "out=Path('/content/p2-eval')/f'step-{step}'/('full' if full_holdout else 'slice')",
        "out.mkdir(parents=True, exist_ok=True)",
        f"holdout=dataset_path({HOLDOUT_URL!r}, '/content/p2-eval/holdout.jsonl', HOLDOUT_MD5)",
    ]
    if full_holdout:
        lines += ["eval_holdout=holdout", "eval_md5=HOLDOUT_MD5", "manifest_path=''", "dataset_sha=file_hash(holdout)"]
    else:
        lines += [
            "eval_holdout=str(out/'validation.jsonl')",
            "manifest_path=str(out/'validation.manifest.json')",
            "manifest=create_slice(holdout, eval_holdout, manifest_path, per_class=32, seed=42)",
            "eval_md5=manifest['slice_md5']",
            "dataset_sha=manifest['slice_sha256']",
        ]
    lines += [
        "metrics_path=str(out/'metrics.json')",
        "predictions_path=str(out/'predictions.jsonl')",
        "cmd=[sys.executable, '-u', '/content/p2a_eval.py', '--holdout', eval_holdout, '--holdout-md5', eval_md5, '--adapter', adapter, '--output', predictions_path, '--checkpoint-step', str(step)]",
        "if manifest_path: cmd += ['--slice-manifest', manifest_path]",
        "if full_holdout: cmd += ['--full-holdout']",
        'subprocess.run(cmd, check=True)',
        "metrics=__import__('json').load(open(predictions_path+'.metrics.json'))",
        "metrics.update({'checkpoint_step':step,'checkpoint_path':remote,'full_holdout':full_holdout,'dataset_sha256':dataset_sha})",
        "Path(metrics_path).write_text(json.dumps(metrics, ensure_ascii=False, indent=2)+'\\n', encoding='utf-8')",
        '''def save_eval_to_hf():
    try:
        eval_path = f"evaluations/checkpoint-{step}/{'full' if full_holdout else 'slice'}"
        api.upload_folder(repo_id=repo, repo_type='model', folder_path=str(out),
                          path_in_repo=eval_path,
                          commit_message=f"P2 eval checkpoint-{step} {'full' if full_holdout else 'slice'}")
        files = api.list_repo_files(repo_id=repo, repo_type='model')
        metric_paths = [p for p in files if p.startswith('evaluations/checkpoint-') and p.endswith('/metrics.json')]
        history = []
        with tempfile.TemporaryDirectory() as temp:
            from huggingface_hub import hf_hub_download
            for filename in metric_paths:
                local = hf_hub_download(repo_id=repo, filename=filename, repo_type='model',
                                        token=token, local_dir=temp)
                with open(local, encoding='utf-8') as stream:
                    history.append(json.load(stream))
        key = (step, full_holdout)
        history = [item for item in history
                   if (int(item.get('checkpoint_step', -1)), bool(item.get('full_holdout'))) != key]
        history.append(metrics)
        history.sort(key=lambda item: (int(item['checkpoint_step']), bool(item.get('full_holdout'))))
        trend_json = Path('/content/p2-eval/trend.json')
        trend_csv = Path('/content/p2-eval/trend.csv')
        trend_json.write_text(json.dumps(history, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')
        columns = ('checkpoint_step','full_holdout','count','direction_accuracy','macro_f1',
                   'brier','ece_4_bins','dataset_sha256')
        with trend_csv.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for item in history:
                writer.writerow({column:item.get(column) for column in columns})
        api.upload_file(repo_id=repo, repo_type='model', path_or_fileobj=str(trend_json),
                        path_in_repo='evaluations/trend.json', commit_message='Update P2 eval trend')
        api.upload_file(repo_id=repo, repo_type='model', path_or_fileobj=str(trend_csv),
                        path_in_repo='evaluations/trend.csv', commit_message='Update P2 eval trend')
        files = set(api.list_repo_files(repo_id=repo, repo_type='model'))
        required = {f'{eval_path}/metrics.json', 'evaluations/trend.json', 'evaluations/trend.csv'}
        required.add(f'{eval_path}/predictions.jsonl')
        if not full_holdout:
            required.add(f'{eval_path}/validation.manifest.json')
        missing = sorted(required - files)
        if missing:
            raise RuntimeError(f'evaluation artifact verification missing: {missing}')
        print(f'EVAL_METRICS_HF_UPLOADED step={step} mode={"full" if full_holdout else "slice"} '
              f'verified_files={len(required)}', flush=True)
    except Exception as error:
        print(f'EVAL_METRICS_HF_UPLOAD_FAILED step={step} '
              f'{type(error).__name__}: {error}; runner backup will retain results', flush=True)

save_eval_to_hf()''',
        "print('P2_EVAL_RESULT '+json.dumps(metrics, ensure_ascii=False, sort_keys=True), flush=True)",
    ]
    return '\n'.join(lines) + '\n'


def run_colab_eval_staged(step, full_holdout, profile, home):
    env = os.environ.copy()
    env['VNCOLAB_HOME'] = str(home)
    if not env.get('HF_TOKEN'):
        raise RuntimeError('HF_TOKEN absent on LV1 runner; cannot download private checkpoints')
    if not checkpoint_complete(env['HF_TOKEN'], step):
        raise RuntimeError(f'checkpoint-{step} is not complete on HF')
    out_dir = RESULT_ROOT / f'step-{step}' / ('full' if full_holdout else 'slice')
    out_dir.mkdir(parents=True, exist_ok=True)
    remote_dir = f"/content/p2-eval/step-{step}/{'full' if full_holdout else 'slice'}"
    job_file = out_dir / 'colab_eval_job.py'
    job_file.write_text(build_remote_job(step, full_holdout, str(out_dir)), encoding='utf-8')
    archive = out_dir / 'colab-eval.zip'
    result_json = out_dir / 'vncolab-result.json'
    log_path = out_dir / 'eval.log'
    archive.unlink(missing_ok=True)
    result_json.unlink(missing_ok=True)
    command = [sys.executable, str(Path(__file__).with_name('vncolab.py')), 'run',
               str(job_file), '--gpu', 'T4', '--timeout', '21600', '--out', str(result_json),
               '--download', remote_dir, str(archive)]
    with log_path.open('a', encoding='utf-8') as log:
        log.write(f'EVAL_START step={step} account={profile} mode={"full" if full_holdout else "slice"}\n')
        proc = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                              text=True, check=False)
    result = {}
    if result_json.is_file():
        result = json.loads(result_json.read_text(encoding='utf-8'))
    if proc.returncode:
        error = str(result.get('error') or '') + '\n' + log_path.read_text(errors='replace')[-5000:]
        raise RuntimeError(f'Colab eval failed (exit={proc.returncode}): {error}')
    if not archive.is_file():
        raise RuntimeError('Colab eval completed without a results archive')
    extract = out_dir / 'remote'
    extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        root = extract.resolve()
        for member in zipped.infolist():
            target = (extract / member.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError('unsafe path in Colab eval archive')
        zipped.extractall(extract)
    metrics_files = list(extract.rglob('metrics.json'))
    if not metrics_files:
        raise RuntimeError('remote evaluation archive missing metrics.json')
    metrics_path = out_dir / 'metrics.json'
    shutil.copy2(metrics_files[0], metrics_path)
    predictions = list(extract.rglob('predictions.jsonl'))
    if predictions:
        shutil.copy2(predictions[0], out_dir / 'predictions.jsonl')
    manifest = list(extract.rglob('validation.manifest.json'))
    if manifest:
        shutil.copy2(manifest[0], out_dir / 'validation.manifest.json')
    return json.loads(metrics_path.read_text(encoding='utf-8'))


def run_colab_eval(step, full_holdout, profile):
    home = stage_profile(profile)
    try:
        return run_colab_eval_staged(step, full_holdout, profile, home)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def write_trend():
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    for path in RESULT_ROOT.glob('step-*/**/metrics.json'):
        try:
            records.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    records.sort(key=lambda item: (int(item['checkpoint_step']), bool(item.get('full_holdout'))))
    (RESULT_ROOT / 'trend.json').write_text(json.dumps(records, ensure_ascii=False,
                                                       indent=2) + '\n', encoding='utf-8')
    columns = ('checkpoint_step', 'full_holdout', 'count', 'direction_accuracy', 'macro_f1',
               'brier', 'ece_4_bins', 'dataset_sha256')
    with (RESULT_ROOT / 'trend.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for item in records:
            writer.writerow({key: item.get(key) for key in columns})


def upload_results(metrics):
    write_trend()
    print(f"EVAL_RESULTS_SAVED_LOCAL {RESULT_ROOT} step={metrics['checkpoint_step']} "
          f"mode={'full' if metrics.get('full_holdout') else 'slice'}", flush=True)


def run_one(request):
    step = int(request['step'])
    full = bool(request['full_holdout'])
    mode = 'full' if full else 'slice'
    target = RESULT_ROOT / f'step-{step}' / mode / 'metrics.json'
    if target.is_file():
        try:
            saved = json.loads(target.read_text(encoding='utf-8'))
            if int(saved['checkpoint_step']) == step and bool(saved.get('full_holdout')) == full:
                print(f'EVAL_ALREADY_DONE step={step} mode={mode}', flush=True)
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
    last_error = None
    for profile in ('tk5', 'tk6'):
        try:
            metrics = run_colab_eval(step, full, profile)
            metrics['source_run'] = request.get('source_run', '')
            metrics['eval_account_profile'] = profile
            temp_target = target.with_suffix(f'.tmp-{os.getpid()}')
            temp_target.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n',
                                   encoding='utf-8')
            os.replace(temp_target, target)
            write_trend()
            upload_results(metrics)
            print(f"P2_EVAL_COMPLETED step={step} mode={mode} account={profile} "
                  f"direction_accuracy={metrics.get('direction_accuracy')} "
                  f"macro_f1={metrics.get('macro_f1')} brier={metrics.get('brier')} "
                  f"ece={metrics.get('ece_4_bins')}", flush=True)
            return True
        except Exception as error:  # noqa: BLE001 — only switch profile after confirmed assign 503
            last_error = error
            text = str(error)
            if profile == 'tk5' and '503' in text and '/tun/m/assign' in text:
                print('P2_EVAL_TK5_ASSIGN_503 switching_once_to_tk6', flush=True)
                continue
            print(f'P2_EVAL_FAILED step={step} mode={mode} account={profile} '
                  f'{type(error).__name__}: {error}', flush=True)
            break
    print(f'P2_EVAL_FAILED step={step} mode={mode} final={last_error}', flush=True)
    return False


def queue_request(step, full_holdout, source_run):
    QUEUE_ROOT.mkdir(parents=True, exist_ok=True)
    key = f'{int(step):08d}-{"full" if full_holdout else "slice"}'
    path = QUEUE_ROOT / f'{key}.json'
    request = {'step': int(step), 'full_holdout': bool(full_holdout), 'source_run': source_run}
    if not path.exists():
        temp = path.with_suffix(f'.tmp-{os.getpid()}')
        temp.write_text(json.dumps(request), encoding='utf-8')
        os.replace(temp, path)
    return path


def enqueue_and_drain(step, full_holdout=False, source_run='manual', idle_timeout=60):
    if step <= 0 or (not full_holdout and step % 50 != 0):
        print(f'P2_EVAL_NOT_SCHEDULED step={step}; sample cadence is 50, full holdout is milestone/manual', flush=True)
        return
    request_file = queue_request(step, full_holdout, source_run)
    lock_path = QUEUE_ROOT / 'worker.lock'
    with lock_path.open('w') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'P2_EVAL_QUEUED step={step} full={full_holdout}', flush=True)
            return
        idle_since = time.monotonic()
        failures = []
        while True:
            pending = sorted(QUEUE_ROOT.glob('*.json'))
            if pending:
                request_path = pending[0]
                request = json.loads(request_path.read_text(encoding='utf-8'))
                request_path.unlink(missing_ok=True)
                idle_since = time.monotonic()
                if not run_one(request):
                    failures.append(f"step={request['step']} mode={'full' if request['full_holdout'] else 'slice'}")
                continue
            if time.monotonic() - idle_since >= idle_timeout:
                break
            time.sleep(3)
        if failures:
            raise RuntimeError('P2 evaluation failed: ' + ', '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--step', type=int)
    selection.add_argument('--latest', action='store_true')
    parser.add_argument('--full-holdout', action='store_true')
    parser.add_argument('--source-run', default=os.environ.get('GITHUB_RUN_ID', 'unknown'))
    parser.add_argument('--idle-timeout', type=int, default=60)
    args = parser.parse_args()
    step = latest_complete_step(os.environ['HF_TOKEN']) if args.latest else args.step
    print(f'P2_EVAL_SELECTED_CHECKPOINT step={step}', flush=True)
    enqueue_and_drain(step, args.full_holdout, args.source_run, args.idle_timeout)


if __name__ == '__main__':
    main()
