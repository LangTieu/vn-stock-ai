#!/usr/bin/env python3
"""Report v2 label prevalence baselines without loading/evaluating a model."""
import argparse
import collections
import json
from pathlib import Path

try:
    from .p2a_eval import calibration
    from .p2a_relabel import row_identity, sha256
    from .p2a_train import LABELS, dataset_label_spec
except ImportError:
    from p2a_eval import calibration
    from p2a_relabel import row_identity, sha256
    from p2a_train import LABELS, dataset_label_spec


def _baseline(labels):
    if not labels:
        return {'n': 0, 'class_counts': {}, 'baselines': None}
    counts = collections.Counter(labels)
    n = len(labels)
    prior = counts['UP'] / n
    majority = 'UP' if counts['UP'] >= counts['DOWN'] else 'DOWN'
    records = [{
        'truth': truth, 'prediction': majority, 'p_up': prior,
        'probability_level': min(4, int(prior * 4) + 1),
        'generated_direction': LABELS[truth], 'raw_generation': LABELS[truth],
    } for truth in labels]
    metrics = calibration(records)['baselines']
    return {'n': n, 'class_counts': dict(sorted(counts.items())), 'baselines': metrics}


def report(paths):
    outputs = []
    for path in paths:
        path = Path(path)
        spec = dataset_label_spec(path)
        if spec.get('label_version') != 2:
            raise ValueError(f'v2 baseline refuses label version {spec.get("label_version")}: {path.name}')
        counts = collections.Counter()
        binary_by_year = collections.defaultdict(list)
        binary_by_exchange = collections.defaultdict(list)
        censored_by_exchange = collections.Counter()
        censored_by_ticker = collections.Counter()
        eligible = []
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                metadata = row.get('metadata') or {}
                if metadata.get('kind') != 'bulk':
                    counts['non_bulk'] += 1
                    continue
                status = metadata.get('p2a_label_status')
                label = (metadata.get('label') or {}).get('future_direction_120')
                counts[f'status_{status or "missing"}'] += 1
                if label in ('UP', 'DOWN', 'FLAT'):
                    counts[f'label_{label}'] += 1
                if status == 'censored':
                    outcome = ((metadata.get('label') or {}).get('future_outcomes') or {}).get('120') or {}
                    reason = outcome.get('reason', 'unknown')
                    ticker, exchange, _ = row_identity(row)
                    censored_by_exchange[f'{exchange}:{reason}'] += 1
                    censored_by_ticker[f'{ticker}:{reason}'] += 1
                if label not in ('UP', 'DOWN'):
                    continue
                ticker, exchange, as_of = row_identity(row)
                eligible.append(label)
                binary_by_year[str(as_of.year)].append(label)
                binary_by_exchange[exchange].append(label)
        year_baselines = {year: _baseline(labels)
                          for year, labels in sorted(binary_by_year.items())}
        exchange_baselines = {exchange: _baseline(labels)
                              for exchange, labels in sorted(binary_by_exchange.items())}
        outputs.append({
            'file': path.name,
            'sha256': sha256(path),
            'label_version': spec['label_version'],
            'label_method': spec['label_method'],
            'flat_band_pct': spec['flat_band_pct'],
            'counts': dict(sorted(counts.items())),
            'majority_prevalence_coinflip_baseline': _baseline(eligible),
            'by_asof_year': year_baselines,
            'by_exchange': exchange_baselines,
            'censored_by_exchange_reason': dict(sorted(censored_by_exchange.items())),
            'censored_by_ticker_reason': dict(sorted(censored_by_ticker.items())),
            'model_evaluation_run': False,
        })
    return {
        'method': 'dataset prevalence baselines only; no model loaded or evaluated',
        'reports': outputs,
        'passes': bool(outputs) and all(item['label_version'] == 2 for item in outputs),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', action='append', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = report(args.input)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8')
    print(json.dumps({
        'passes': result['passes'],
        'reports': [{
            'file': item['file'], 'sha256': item['sha256'], 'counts': item['counts'],
            'binary_baseline': item['majority_prevalence_coinflip_baseline'],
        } for item in result['reports']],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
