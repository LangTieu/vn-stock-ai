#!/usr/bin/env python3
import argparse
import json
import math
import random
from pathlib import Path
from p2a_train import (MODEL_ID, LABELS, dataset_label_spec, dataset_path,
                       messages, rows)
from p2a_validation import row_strata


def validate_eval_label_versions(train_manifest, holdout_spec):
    if train_manifest is None:
        raise ValueError('V2 training manifest is required for evaluation')
    train_version = train_manifest.get('label_version')
    holdout_version = holdout_spec.get('label_version')
    if train_version != 2 or holdout_version != 2:
        raise ValueError(f'P2 V2 evaluation requires label version 2; got {train_version!r} / {holdout_version!r}')
    if train_version != holdout_version:
        raise ValueError(f'Train/holdout label version mismatch: {train_version!r} != '
                         f'{holdout_version!r}')


def load_eval_tokenizer(auto_tokenizer=None):
    if auto_tokenizer is None:
        from transformers import AutoTokenizer
        auto_tokenizer = AutoTokenizer
    return auto_tokenizer.from_pretrained(MODEL_ID)


def direction_probability(model, tokenizer, row, torch):
    prefix = tokenizer.apply_chat_template(messages(row), tokenize=True,
                                           add_generation_prompt=True)
    scores = []
    for label in ('TĂNG', 'GIẢM'):
        suffix = tokenizer.encode(label, add_special_tokens=False) + [tokenizer.eos_token_id]
        ids = torch.tensor([prefix + suffix], device=model.device)
        logits = model(ids).logits[0, len(prefix) - 1:-1].float()
        scores.append(torch.log_softmax(logits, -1).gather(
            1, torch.tensor(suffix, device=model.device)[:, None]).sum().item())
    delta = max(-700, min(700, scores[1] - scores[0]))
    return 1 / (1 + math.exp(delta))


def _classification_metrics(records, prediction_key='prediction', probability_key='p_up'):
    if not records:
        raise ValueError('Cannot compute evaluation metrics for an empty sample')
    confusion = {truth: {prediction: 0 for prediction in ('UP', 'DOWN')}
                 for truth in ('UP', 'DOWN')}
    for record in records:
        truth, prediction = record['truth'], record[prediction_key]
        if truth not in confusion or prediction not in confusion[truth]:
            raise ValueError('Evaluation labels and predictions must be UP or DOWN')
        confusion[truth][prediction] += 1
    precision, recall, f1 = {}, {}, {}
    for label in ('UP', 'DOWN'):
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in ('UP', 'DOWN') if other != label)
        fn = sum(confusion[label][other] for other in ('UP', 'DOWN') if other != label)
        precision[label] = tp / (tp + fp) if tp + fp else 0.0
        recall[label] = tp / (tp + fn) if tp + fn else 0.0
        f1[label] = (2 * precision[label] * recall[label] /
                     (precision[label] + recall[label])
                     if precision[label] + recall[label] else 0.0)
    n = len(records)
    accuracy = sum(r[prediction_key] == r['truth'] for r in records) / n
    brier = sum((r[probability_key] - (r['truth'] == 'UP')) ** 2 for r in records) / n
    return {
        'direction_accuracy': accuracy,
        'macro_f1': sum(f1.values()) / 2,
        'brier': brier,
        'class_precision': precision,
        'class_recall': recall,
        'class_f1': f1,
        'confusion_matrix': confusion,
    }


def _percentile(sorted_values, probability):
    index = (len(sorted_values) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def bootstrap_confidence_intervals(records, resamples=1000, seed=42,
                                   prediction_key='prediction', probability_key='p_up'):
    if resamples < 1:
        raise ValueError('bootstrap resamples must be positive')
    if not records:
        raise ValueError('Cannot bootstrap an empty evaluation sample')
    rng = random.Random(seed)
    n = len(records)
    samples = {'direction_accuracy': [], 'macro_f1': [], 'brier': []}
    for _ in range(resamples):
        draw = [records[rng.randrange(n)] for _ in range(n)]
        metrics = _classification_metrics(draw, prediction_key, probability_key)
        for key in samples:
            samples[key].append(metrics[key])
    return {key: {
        'lower': _percentile(sorted(values), 0.025),
        'upper': _percentile(sorted(values), 0.975),
        'level': 0.95,
        'resamples': resamples,
    } for key, values in samples.items()}


def bootstrap_learning_signal(records, resamples=1000, seed=42):
    if not records or not all('base_prediction' in r and 'base_p_up' in r for r in records):
        raise ValueError('Paired base-model predictions are required for learning-signal intervals')
    if resamples < 1:
        raise ValueError('bootstrap resamples must be positive')
    rng = random.Random(seed)
    n = len(records)
    differences = {'direction_accuracy_delta': [], 'macro_f1_delta': [], 'brier_delta': []}
    for _ in range(resamples):
        draw = [records[rng.randrange(n)] for _ in range(n)]
        model = _classification_metrics(draw)
        base = _classification_metrics(draw, 'base_prediction', 'base_p_up')
        differences['direction_accuracy_delta'].append(model['direction_accuracy'] - base['direction_accuracy'])
        differences['macro_f1_delta'].append(model['macro_f1'] - base['macro_f1'])
        differences['brier_delta'].append(model['brier'] - base['brier'])
    result = {}
    for key, values in differences.items():
        values.sort()
        result[key] = {'lower': _percentile(values, .025), 'upper': _percentile(values, .975),
                       'level': .95, 'resamples': resamples}
    return result


def calibration(records, bootstrap_resamples=1000, bootstrap_seed=42):
    point = _classification_metrics(records)
    bins = []
    for level in range(4):
        group = [r for r in records if r['probability_level'] == level + 1]
        bins.append({'level': level + 1, 'count': len(group),
                     'mean_p_up': sum(r['p_up'] for r in group) / len(group) if group else None,
                     'observed_up_rate': sum(r['truth'] == 'UP' for r in group) / len(group) if group else None})
    n = len(records)
    class_counts = {label: sum(record['truth'] == label for record in records)
                    for label in ('UP', 'DOWN')}
    if not all(class_counts.values()):
        raise ValueError('Evaluation slice must contain both UP and DOWN labels')
    majority = 'UP' if class_counts['UP'] >= class_counts['DOWN'] else 'DOWN'
    prior_up = class_counts['UP'] / n
    baseline_confusion = {truth: {prediction: 0 for prediction in ('UP', 'DOWN')}
                          for truth in ('UP', 'DOWN')}
    for truth in ('UP', 'DOWN'):
        baseline_confusion[truth][majority] = class_counts[truth]
    baseline_f1 = {}
    for label in ('UP', 'DOWN'):
        tp = baseline_confusion[label][label]
        fp = baseline_confusion['DOWN' if label == 'UP' else 'UP'][label]
        fn = baseline_confusion[label]['DOWN' if label == 'UP' else 'UP']
        denominator = 2 * tp + fp + fn
        baseline_f1[label] = 2 * tp / denominator if denominator else 0.0
    result = {
        'count': n,
        'n': n,
        **point,
        'confidence_intervals': bootstrap_confidence_intervals(
            records, bootstrap_resamples, bootstrap_seed),
        'generation_accuracy': sum(r['generated_direction'] == LABELS[r['truth']] for r in records) / n,
        'generation_invalid': sum(r['generated_direction'] not in LABELS.values() for r in records),
        'invalid_output_rate': sum(r['raw_generation'] not in LABELS.values() for r in records) / n,
        'exact_format_rate': sum(r['raw_generation'] in LABELS.values() for r in records) / n,
        'brier': point['brier'],
        'ece_4_bins': sum(b['count'] / n * abs(b['mean_p_up'] - b['observed_up_rate'])
                          for b in bins if b['count']), 'bins': bins,
        'baselines': {
                'class_counts': class_counts,
                'majority_class': majority,
                'majority_accuracy': max(class_counts.values()) / n,
                'majority_macro_f1': sum(baseline_f1.values()) / len(baseline_f1),
                'constant_prevalence_p_up': prior_up,
                'constant_prevalence_brier': prior_up * (1 - prior_up),
                'coin_flip_expected_accuracy': 0.5,
        },
    }
    if all('base_prediction' in record and 'base_p_up' in record for record in records):
        base = _classification_metrics(records, 'base_prediction', 'base_p_up')
        base['confidence_intervals'] = bootstrap_confidence_intervals(
            records, bootstrap_resamples, bootstrap_seed,
            prediction_key='base_prediction', probability_key='base_p_up')
        result['base_model'] = base
        result['learning_signal'] = {
            'direction_accuracy_delta': point['direction_accuracy'] - base['direction_accuracy'],
            'macro_f1_delta': point['macro_f1'] - base['macro_f1'],
            'brier_delta': point['brier'] - base['brier'],
        }
        result['learning_signal_confidence_intervals'] = bootstrap_learning_signal(
            records, bootstrap_resamples, bootstrap_seed)
    return result


def trend_row(metrics):
    intervals = metrics.get('confidence_intervals') or {}
    base = metrics.get('base_model') or {}
    base_ci = base.get('confidence_intervals') or {}
    precision = metrics.get('class_precision') or {}
    recall = metrics.get('class_recall') or {}
    return {
        'checkpoint_step': metrics.get('checkpoint_step'),
        'full_holdout': metrics.get('full_holdout'),
        'n': metrics.get('n', metrics.get('count')),
        'direction_accuracy': metrics.get('direction_accuracy'),
        'direction_accuracy_ci_lower': (intervals.get('direction_accuracy') or {}).get('lower'),
        'direction_accuracy_ci_upper': (intervals.get('direction_accuracy') or {}).get('upper'),
        'macro_f1': metrics.get('macro_f1'),
        'macro_f1_ci_lower': (intervals.get('macro_f1') or {}).get('lower'),
        'macro_f1_ci_upper': (intervals.get('macro_f1') or {}).get('upper'),
        'brier': metrics.get('brier'),
        'brier_ci_lower': (intervals.get('brier') or {}).get('lower'),
        'brier_ci_upper': (intervals.get('brier') or {}).get('upper'),
        'base_model_accuracy': base.get('direction_accuracy'),
        'base_model_accuracy_ci_lower': (base_ci.get('direction_accuracy') or {}).get('lower'),
        'base_model_accuracy_ci_upper': (base_ci.get('direction_accuracy') or {}).get('upper'),
        'base_model_macro_f1': base.get('macro_f1'),
        'base_model_brier': base.get('brier'),
        'direction_accuracy_delta': (metrics.get('learning_signal') or {}).get('direction_accuracy_delta'),
        'macro_f1_delta': (metrics.get('learning_signal') or {}).get('macro_f1_delta'),
        'brier_delta': (metrics.get('learning_signal') or {}).get('brier_delta'),
        'up_precision': precision.get('UP'),
        'up_recall': recall.get('UP'),
        'down_precision': precision.get('DOWN'),
        'down_recall': recall.get('DOWN'),
        'invalid_output_rate': metrics.get('invalid_output_rate'),
        'ece_4_bins': metrics.get('ece_4_bins'),
        'dataset_sha256': metrics.get('dataset_sha256'),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--holdout', required=True)
    p.add_argument('--adapter', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--holdout-md5', required=True)
    p.add_argument('--holdout-sha256', required=True)
    p.add_argument('--checkpoint-step', type=int)
    p.add_argument('--slice-manifest')
    p.add_argument('--full-holdout', action='store_true')
    p.add_argument('--full-validation-approval-ref')
    p.add_argument('--expected-dataset-repo')
    p.add_argument('--expected-dataset-revision')
    p.add_argument('--expected-train-sha256')
    a = p.parse_args()
    if a.full_holdout and not a.full_validation_approval_ref:
        p.error('--full-holdout requires a separately approved matching V2 validation artifact reference')
    holdout = dataset_path(a.holdout, Path(a.output).parent / 'holdout.jsonl', a.holdout_md5)
    from p2a_train import sha256_file, require_v2_training
    if sha256_file(holdout) != a.holdout_sha256:
        raise ValueError('V2 validation SHA-256 does not match its pinned manifest')
    holdout_spec = dataset_label_spec(holdout)
    require_v2_training(holdout_spec)
    manifest_path = Path(a.adapter) / 'p2a_training_manifest.json'
    if not manifest_path.is_file():
        raise ValueError('V2 adapter training manifest is required for evaluation')
    train_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    validate_eval_label_versions(train_manifest, holdout_spec)
    for key, expected in (
        ('dataset_repo', a.expected_dataset_repo),
        ('dataset_revision', a.expected_dataset_revision),
        ('train_sha256', a.expected_train_sha256),
    ):
        if expected and train_manifest.get(key) != expected:
            raise ValueError(f'checkpoint {key} does not match the pinned V2 dataset')
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed
    from peft import PeftModel
    set_seed(42)
    tok = load_eval_tokenizer(AutoTokenizer)
    base = AutoModelForCausalLM.from_pretrained(MODEL_ID, device_map={'': 0},
        torch_dtype=torch.float16, quantization_config=BitsAndBytesConfig(load_in_4bit=True,
        bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16))
    model = PeftModel.from_pretrained(base, a.adapter).eval()
    records = []
    with Path(a.output).open('w') as stream, torch.inference_mode():
        for row in rows(holdout, a.limit):
            prefix = tok.apply_chat_template(messages(row), tokenize=True, add_generation_prompt=True)
            with model.disable_adapter():
                base_p_up = direction_probability(model, tok, row, torch)
            p_up = direction_probability(model, tok, row, torch)
            ids = torch.tensor([prefix], device=model.device)
            generated = model.generate(ids, attention_mask=torch.ones_like(ids), max_new_tokens=16,
                do_sample=False, pad_token_id=tok.eos_token_id)
            raw_gen = tok.decode(generated[0, len(prefix):], skip_special_tokens=True).strip()
            first_tok = raw_gen.split()[0].strip('.,:;!?"\'()[]') if raw_gen else ''
            gen_dir = first_tok.upper() if first_tok.upper() in LABELS.values() else raw_gen
            ticker, time_bucket = row_strata(row)
            record = {'index': len(records), 'ticker': ticker, 'time_bucket': time_bucket,
                'truth': row['metadata']['label']['future_direction_120'],
                'prediction': 'UP' if p_up >= 0.5 else 'DOWN', 'p_up': p_up,
                'base_prediction': 'UP' if base_p_up >= 0.5 else 'DOWN',
                'base_p_up': base_p_up,
                'probability_level': min(4, int(p_up * 4) + 1),
                'generated_direction': gen_dir, 'raw_generation': raw_gen}
            records.append(record)
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
    if not records:
        raise ValueError('No labeled bulk holdout rows')
    result = calibration(records)
    result.update({'checkpoint_step': a.checkpoint_step,
                   'slice_manifest': a.slice_manifest,
                   'full_holdout': a.full_holdout,
                   'train_label_version': (train_manifest or {}).get('label_version'),
                   'holdout_label_version': holdout_spec['label_version']})
    Path(a.output + '.metrics.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
