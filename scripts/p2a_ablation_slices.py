#!/usr/bin/env python3
"""Create fixed, leakage-separated train/validation slices from V2 train only."""
import argparse
import collections
import json
from datetime import date
from pathlib import Path

try:
    from .p2a_relabel import row_identity, sha256
    from .p2a_validation import create_slice
except ImportError:
    from p2a_relabel import row_identity, sha256
    from p2a_validation import create_slice


def make_slices(source, output_dir, validation_year=2024,
                train_per_class=64, validation_per_class=32, seed=42):
    source=Path(source); output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
    validation=[]
    with source.open(encoding='utf-8') as stream:
        for line_number,line in enumerate(stream,1):
            row=json.loads(line); metadata=row.get('metadata') or {}
            if metadata.get('kind')!='bulk' or metadata.get('p2a_label_version')!=2:
                continue
            if metadata.get('p2a_label_status')!='labeled':
                continue
            label=(metadata.get('label') or {}).get('future_direction_120')
            if label not in ('UP','DOWN'): continue
            ticker,exchange,as_of=row_identity(row)
            day=date.fromisoformat(as_of) if isinstance(as_of,str) else as_of
            if day.year==validation_year:
                endpoint=(((metadata.get('label') or {}).get('future_outcomes') or {})
                          .get('120') or {}).get('endpoint_date')
                if not endpoint:
                    raise ValueError(f'missing v2 target endpoint on line {line_number}')
                validation.append((line_number,ticker,day,date.fromisoformat(endpoint),label,line))
    if not validation:
        raise ValueError(f'no labeled UP/DOWN validation rows for year {validation_year}')
    validation_start=min(item[2] for item in validation)
    eligible_validation={label:sum(item[4]==label for item in validation) for label in ('UP','DOWN')}
    eligible_train=collections.Counter()
    train_rows=0
    train_max_endpoint=None
    train_pool=output_dir/'train-pool.jsonl'
    with source.open(encoding='utf-8') as stream, train_pool.open('w',encoding='utf-8') as target:
        for line_number,line in enumerate(stream,1):
            row=json.loads(line); metadata=row.get('metadata') or {}
            if metadata.get('kind')!='bulk' or metadata.get('p2a_label_version')!=2:
                continue
            if metadata.get('p2a_label_status')!='labeled': continue
            label=(metadata.get('label') or {}).get('future_direction_120')
            if label not in ('UP','DOWN'): continue
            outcome=(((metadata.get('label') or {}).get('future_outcomes') or {})
                     .get('120') or {})
            endpoint=outcome.get('endpoint_date')
            if not endpoint: raise ValueError(f'missing v2 target endpoint on line {line_number}')
            endpoint_day=date.fromisoformat(endpoint)
            if endpoint_day >= validation_start: continue
            target.write(line if line.endswith('\n') else line+'\n')
            train_rows+=1;eligible_train[label]+=1
            train_max_endpoint=max(train_max_endpoint or endpoint_day,endpoint_day)
    validation_pool=output_dir/'validation-pool.jsonl'
    validation_pool.write_text(''.join(item[5] if item[5].endswith('\n') else item[5]+'\n'
                                      for item in validation),encoding='utf-8')
    if train_rows==0 or not all(eligible_validation.values()):
        raise ValueError('time-separated train/validation candidates are empty')
    train_slice=output_dir/'train-v2.jsonl'; train_manifest=output_dir/'train-v2.manifest.json'
    validation_slice=output_dir/'validation-v2.jsonl'; validation_manifest=output_dir/'validation-v2.manifest.json'
    train_sample=create_slice(train_pool,train_slice,train_manifest,per_class=train_per_class,seed=seed)
    validation_sample=create_slice(validation_pool,validation_slice,validation_manifest,
                                   per_class=validation_per_class,seed=seed+1)
    train_endpoints=[];train_asofs=[]
    with train_slice.open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line); metadata=row['metadata']
            _,_,as_of=row_identity(row);train_asofs.append(as_of)
            train_endpoints.append(date.fromisoformat(
                metadata['label']['future_outcomes']['120']['endpoint_date']))
    if max(train_endpoints)>=validation_start:
        raise ValueError('forward target leakage: train endpoint overlaps validation as_of')
    validation_days=[item[2] for item in validation if item[4] in ('UP','DOWN')]
    report={
        'source_train_sha256':sha256(source),
        'validation_time_bucket_year':validation_year,
        'train_candidate_rows_with_endpoint_before_validation':train_rows,
        'train_candidate_binary_class_counts':dict(sorted(eligible_train.items())),
        'validation_candidate_binary_class_counts':eligible_validation,
        'train_sample':train_sample,'validation_sample':validation_sample,
        'actual_split':{
            'train_as_of_max':max(train_asofs).isoformat() if train_asofs else None,
            'train_target_endpoint_max':max(train_endpoints).isoformat() if train_endpoints else None,
            'validation_as_of_min':min(validation_days).isoformat(),
            'validation_as_of_max':max(validation_days).isoformat(),
            'train_target_before_validation_as_of':max(train_endpoints)<validation_start,
        },
        'external_holdout_used_for_selection':False,
        'synthetic_rows_created':False,
        'passes':True,
    }
    (output_dir/'split-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    train_pool.unlink();validation_pool.unlink()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True);parser.add_argument('--output-dir',required=True)
    parser.add_argument('--validation-year',type=int,default=2024)
    parser.add_argument('--train-per-class',type=int,default=64)
    parser.add_argument('--validation-per-class',type=int,default=32)
    parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args()
    result=make_slices(args.input,args.output_dir,args.validation_year,
                       args.train_per_class,args.validation_per_class,args.seed)
    print(json.dumps({'passes':result['passes'],'train_sample_sha256':result['train_sample']['slice_sha256'],
                      'validation_sample_sha256':result['validation_sample']['slice_sha256'],
                      'train_target_before_validation_as_of':result['actual_split']['train_target_before_validation_as_of'],
                      'external_holdout_used_for_selection':False},sort_keys=True))


if __name__=='__main__':main()
