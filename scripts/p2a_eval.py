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
    return {'count': n,
            'direction_accuracy': sum(r['prediction'] == r['truth'] for r in records) / n,
            'generation_accuracy': sum(r['generated_direction'] == LABELS[r['truth']] for r in records) / n,
            'generation_invalid': sum(r['generated_direction'] not in LABELS.values() for r in records),
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
                do_sample=True, temperature=0.1, top_p=0.75, top_k=40,
                pad_token_id=tok.eos_token_id)
            record = {'index': len(records), 'truth': row['metadata']['label']['future_direction_120'],
                'prediction': 'UP' if p_up >= 0.5 else 'DOWN', 'p_up': p_up,
                'probability_level': min(4, int(p_up * 4) + 1),
                'generated_direction': tok.decode(generated[0, len(prefix):], skip_special_tokens=True).strip()}
            records.append(record)
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
    if not records:
        raise ValueError('No labeled bulk holdout rows')
    result = calibration(records)
    Path(a.output + '.metrics.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
