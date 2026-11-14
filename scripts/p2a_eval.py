#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path
from p2a_train import MODEL_ID, LABELS, HOLDOUT_MD5, dataset_path, messages, rows


def calibration(records):
    bins = []
    for level in range(4):
        group = [r for r in records if r['probability_level'] == level + 1]
        bins.append({'level': level + 1, 'count': len(group),
                     'mean_p_up': sum(r['p_up'] for r in group) / len(group) if group else None,
                     'observed_up_rate': sum(r['truth'] == 'UP' for r in group) / len(group) if group else None})
    n = len(records)
    confusion = {truth: {prediction: 0 for prediction in ('UP', 'DOWN')}
                 for truth in ('UP', 'DOWN')}
    for record in records:
        confusion[record['truth']][record['prediction']] += 1
    class_f1 = {}
    for label in ('UP', 'DOWN'):
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in ('UP', 'DOWN') if other != label)
        fn = sum(confusion[label][other] for other in ('UP', 'DOWN') if other != label)
        denom = 2 * tp + fp + fn
        class_f1[label] = 2 * tp / denom if denom else 0.0
    return {'count': n,
            'direction_accuracy': sum(r['prediction'] == r['truth'] for r in records) / n,
            'macro_f1': sum(class_f1.values()) / len(class_f1),
            'class_f1': class_f1,
            'confusion_matrix': confusion,
            'generation_accuracy': sum(r['generated_direction'] == LABELS[r['truth']] for r in records) / n,
            'generation_invalid': sum(r['generated_direction'] not in LABELS.values() for r in records),
            'exact_format_rate': sum(r['raw_generation'] in LABELS.values() for r in records) / n,
            'brier': sum((r['p_up'] - (r['truth'] == 'UP')) ** 2 for r in records) / n,
            'ece_4_bins': sum(b['count'] / n * abs(b['mean_p_up'] - b['observed_up_rate'])
                              for b in bins if b['count']), 'bins': bins}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--holdout', required=True)
    p.add_argument('--adapter', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--holdout-md5', default=HOLDOUT_MD5)
    p.add_argument('--checkpoint-step', type=int)
    p.add_argument('--slice-manifest')
    p.add_argument('--full-holdout', action='store_true')
    a = p.parse_args()
    holdout = dataset_path(a.holdout, Path(a.output).parent / 'holdout.jsonl', a.holdout_md5)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed
    from peft import PeftModel
    set_seed(42)
    tok = AutoTokenizer.from_pretrained(a.adapter)
    base = AutoModelForCausalLM.from_pretrained(MODEL_ID, device_map={'': 0},
        torch_dtype=torch.float16, quantization_config=BitsAndBytesConfig(load_in_4bit=True,
        bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16))
    model = PeftModel.from_pretrained(base, a.adapter).eval()
    records = []
    with Path(a.output).open('w') as stream, torch.inference_mode():
        for row in rows(holdout, a.limit):
            prefix = tok.apply_chat_template(messages(row), tokenize=True, add_generation_prompt=True)
            scores = []
            for label in ['TĂNG', 'GIẢM']:
                suffix = tok.encode(label, add_special_tokens=False) + [tok.eos_token_id]
                ids = torch.tensor([prefix + suffix], device=model.device)
                logits = model(ids).logits[0, len(prefix)-1:-1].float()
                scores.append(torch.log_softmax(logits, -1).gather(
                    1, torch.tensor(suffix, device=model.device)[:, None]).sum().item())
            delta = max(-700, min(700, scores[1] - scores[0]))
            p_up = 1 / (1 + math.exp(delta))
            ids = torch.tensor([prefix], device=model.device)
            generated = model.generate(ids, attention_mask=torch.ones_like(ids), max_new_tokens=16,
                do_sample=False, pad_token_id=tok.eos_token_id)
            raw_gen = tok.decode(generated[0, len(prefix):], skip_special_tokens=True).strip()
            first_tok = raw_gen.split()[0].strip('.,:;!?"\'()[]') if raw_gen else ''
            gen_dir = first_tok.upper() if first_tok.upper() in LABELS.values() else raw_gen
            record = {'index': len(records), 'truth': row['metadata']['label']['future_direction_120'],
                'prediction': 'UP' if p_up >= 0.5 else 'DOWN', 'p_up': p_up,
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
                   'full_holdout': a.full_holdout})
    Path(a.output + '.metrics.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
