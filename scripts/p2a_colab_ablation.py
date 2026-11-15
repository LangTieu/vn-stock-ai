#!/usr/bin/env python3
"""Run a small, controlled P2a v2 LoRA/LR ablation on Colab."""
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
from p2a_validation import create_slice

ASSIGN_503 = re.compile(
    r'/tun/m/assign(?![A-Za-z0-9_-])[^\n]*503|503[^\n]*/tun/m/assign(?![A-Za-z0-9_-])', re.I)
EVAL_METRICS = re.compile(r'^P2A_ABLATION_EVAL (\{.*\})$', re.M)
GRAD_NORM = re.compile(r"grad_norm['\"]?\s*[:=]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|nan|inf)", re.I)

TRIALS = (
    {'name':'baseline','lora_r':8,'lora_alpha':32,'lora_dropout':0.1,'learning_rate':1e-4},
    {'name':'lower_learning_rate','lora_r':8,'lora_alpha':32,'lora_dropout':0.1,'learning_rate':5e-5},
    {'name':'lower_lora_rank','lora_r':4,'lora_alpha':32,'lora_dropout':0.1,'learning_rate':1e-4},
)


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def md5(path):
    h=hashlib.md5()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def choose_best(trials):
    completed=[item for item in trials if item.get('ok') and item.get('evaluation')]
    if not completed:
        raise ValueError('No successful ablation trial with validation metrics')
    def score(item):
        metrics=item['evaluation']
        return (float(metrics.get('direction_accuracy',-1)),
                float(metrics.get('macro_f1',-1)),
                -float(metrics.get('brier',math.inf)))
    return max(completed,key=score)['trial']['name']


def run_trial(profile,trial,train_slice,validation_slice,max_steps,timeout,work_dir):
    home=stage_profile(profile)
    try:
        env=os.environ.copy()
        train_md5=md5(train_slice); holdout_md5=md5(validation_slice)
        env.update({
            'VNCOLAB_HOME':str(home),'MODE':'smoke','MAX_STEPS':str(max_steps),
            'SAVE_STEPS':'1','TRAIN_URL':'/content/p2a_ablation_train_v2.jsonl',
            'TRAIN_MD5':train_md5,'HOLDOUT_URL':'/content/p2a_ablation_validation_v2.jsonl',
            'HOLDOUT_MD5':holdout_md5,'P2A_LOCAL_TRAIN':'1','P2A_EVAL_LIMIT':'64',
            'SKIP_EVAL':'0','UPLOAD_HF':'0','HF_CHECKPOINT_REPO':'',
            'HF_REPO':'','P2_EVAL_ENABLED':'0',
            'OUTPUT_DIR':f'/content/p2a-ablation/{trial["name"]}',
            'LORA_R':str(trial['lora_r']),'LORA_ALPHA':str(trial['lora_alpha']),
            'LORA_DROPOUT':str(trial['lora_dropout']),
            'LEARNING_RATE':str(trial['learning_rate']),
            'GRADIENT_ACCUMULATION_STEPS':'32','TARGET_MODULES':'q_proj,k_proj,v_proj,o_proj',
            'SEED':'42',
        })
        result_path=Path(work_dir)/f'{trial["name"]}-colab.json'
        command=[sys.executable,str(Path(__file__).with_name('vncolab.py')),'run',
                 'notebooks/p2a_train.ipynb','--gpu','T4','--timeout',str(timeout),
                 '--out',str(result_path),'--mode','smoke','--max-steps',str(max_steps),
                 '--save-steps','1','--upload-file',str(train_slice),
                 '/content/p2a_ablation_train_v2.jsonl','--upload-file',str(validation_slice),
                 '/content/p2a_ablation_validation_v2.jsonl']
        try:
            proc=subprocess.run(command,env=env,capture_output=True,text=True,
                                timeout=timeout+300,check=False)
        except subprocess.TimeoutExpired:
            return {'trial':trial,'profile':profile,'ok':False,'error_type':'TimeoutExpired',
                    'training_slice_sha256':sha256(train_slice),
                    'validation_slice_sha256':sha256(validation_slice)}
        result=json.loads(result_path.read_text()) if result_path.is_file() else {}
        text=(proc.stdout or '')+'\n'+(proc.stderr or '')
        for cell in result.get('cells',[]): text+='\n'+str(cell.get('output',''))+'\n'+str(cell.get('error',''))
        grad_values=[]
        for match in GRAD_NORM.finditer(text):
            try:grad_values.append(float(match.group(1)))
            except ValueError:grad_values.append(math.nan)
        finite=[value for value in grad_values if math.isfinite(value)]
        eval_matches=EVAL_METRICS.findall(text)
        evaluation=json.loads(eval_matches[-1]) if eval_matches else None
        guard_failed='Non-finite P2a gradient' in text or 'Non-finite P2a loss' in text
        return {
            'trial':trial,'profile':profile,'return_code':proc.returncode,
            'result_ok':result.get('ok') is True,'requested_max_steps':max_steps,
            'finite_gradient_norm_observations':len(finite),
            'nonfinite_guard_triggered':guard_failed,'evaluation':evaluation,
            'training_slice_sha256':sha256(train_slice),
            'validation_slice_sha256':sha256(validation_slice),
            'training_slice_md5':train_md5,'validation_slice_md5':holdout_md5,
            'ok':(proc.returncode==0 and result.get('ok') is True and not guard_failed
                  and bool(finite) and bool(evaluation) and evaluation.get('count')==64),
            'assign_503':bool(ASSIGN_503.search(text)),
        }
    finally:
        shutil.rmtree(home,ignore_errors=True)


def _run_with_fallback(trial,train_slice,validation_slice,max_steps,timeout,work_dir,
                       runner=run_trial):
    tk2=runner('tk2',trial,train_slice,validation_slice,max_steps,timeout,work_dir)
    if tk2.get('ok') or not tk2.get('assign_503'):
        return tk2
    return runner('tk5',trial,train_slice,validation_slice,max_steps,timeout,work_dir)


def run_ablation(train,validation,max_steps=12,timeout=18000,output_dir='p2a-ablation',
                 split_manifest=None):
    if max_steps<1 or max_steps>50:raise ValueError('ablation max_steps must be 1..50')
    split_report=json.loads(Path(split_manifest).read_text(encoding='utf-8')) if split_manifest else None
    if split_report and (not split_report.get('passes')
                         or not split_report.get('actual_split',{}).get('train_target_before_validation_as_of')
                         or split_report.get('external_holdout_used_for_selection') is not False):
        raise ValueError('ablation split manifest does not certify a leakage-safe internal V2 split')
    train_spec=dataset_label_spec(train); val_spec=dataset_label_spec(validation)
    if train_spec.get('label_version')!=2 or val_spec.get('label_version')!=2:
        raise ValueError('ablation accepts only label-v2 train/validation files')
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='p2a-colab-ablation-') as temp:
        root=Path(temp)
        train_slice=root/'train-v2.jsonl'; train_manifest=root/'train-v2.manifest.json'
        validation_slice=root/'validation-v2.jsonl'; validation_manifest=root/'validation-v2.manifest.json'
        train_slice_manifest=create_slice(train,train_slice,train_manifest,per_class=64,seed=42)
        validation_slice_manifest=create_slice(validation,validation_slice,validation_manifest,per_class=32,seed=4242)
        lock_path=LOCK_ROOT/'queue'/'worker.lock';lock_path.parent.mkdir(parents=True,exist_ok=True)
        with lock_path.open('a+') as lock:
            try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('TK2/TK5 Colab slot is busy; do not run ablations concurrently with eval/smoke') from error
            results=[]
            for trial in TRIALS:
                result=_run_with_fallback(trial,train_slice,validation_slice,max_steps,timeout,root)
                results.append(result)
                if not result.get('ok'):
                    break
            passed=len(results)==len(TRIALS) and all(item.get('ok') for item in results)
            best=choose_best(results) if passed else None
            summary={
                'label_version':2,'experiment':'controlled_short_loRA_lr_ablation',
                'smoke_only':True,'full_training_started':False,
                'maximum_steps_per_trial':max_steps,'common_seed':42,
                'training_slice_rows':128,'validation_slice_rows':64,
                'training_slice_sha256':train_slice_manifest['slice_sha256'],
                'validation_slice_sha256':validation_slice_manifest['slice_sha256'],
                'internal_split_manifest':split_report,
                'external_holdout_used_for_selection':False,
                'training_label_sha256':sha256(train),'validation_label_sha256':sha256(validation),
                'trials':results,'best_trial':best,'passes':passed,
                'selection_rule':'highest validation direction accuracy; then macro-F1; then lowest Brier',
                'limitations':['Tiny validation slice; exploratory config selection only, not model-quality certification.',
                               'Full training remains paused for a separate Henrry decision.'],
            }
            out.mkdir(parents=True,exist_ok=True)
            (out/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
            return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train',required=True);parser.add_argument('--validation',required=True)
    parser.add_argument('--split-manifest',required=True)
    parser.add_argument('--max-steps',type=int,default=12);parser.add_argument('--timeout',type=int,default=18000)
    parser.add_argument('--output-dir',default='p2a-ablation')
    args=parser.parse_args()
    report=run_ablation(args.train,args.validation,args.max_steps,args.timeout,
                         args.output_dir,args.split_manifest)
    print(json.dumps({'passes':report['passes'],'best_trial':report['best_trial'],
                      'trial_count':len(report['trials']),'full_training_started':False},sort_keys=True))
    if not report['passes']:raise SystemExit(2)


if __name__=='__main__':main()
