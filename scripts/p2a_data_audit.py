#!/usr/bin/env python3
"""Audit P2 JSONL labels, split separation, endpoint gaps, and prompt leakage."""
import argparse
import collections
import hashlib
import json
import re
from datetime import date
from pathlib import Path

try:
    from .p2a_relabel import BRIEF_RE, sha256
except ImportError:
    from p2a_relabel import BRIEF_RE, sha256

DATE_RE = re.compile(r'\b20\d{2}-\d{2}-\d{2}\b')
EXCHANGE_RE = re.compile(r'(?:^|[_-])(HOSE|HNX|UPCOM|OTC)(?:[_-]|\.)', re.I)
THRESHOLDS = (200, 250, 365, 730, 1000)


def read_identity(row):
    text = row.get('input', '')
    match = BRIEF_RE.search(text.splitlines()[0] if text else '')
    verified = {}
    marker = 'VERIFIED_DATA\n'
    if marker in text:
        try:
            verified, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1])
        except (TypeError, ValueError):
            pass
    ticker = str(verified.get('ticker') or (match.group(1) if match else '')).strip().upper()
    as_of = verified.get('as_of') or (match.group(2) if match else None)
    source = ((verified.get('source') or {}).get('ohlcv') or '')
    source_match = EXCHANGE_RE.search(source)
    exchange = str((row.get('metadata') or {}).get('exchange') or
                   (source_match.group(1) if source_match else 'unknown')).upper()
    return ticker or 'unknown', exchange, as_of, verified


def _hash_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def audit(paths, tokenizer_name=None):
    tokenizer = None
    target_lengths = {}
    system_prompt = None
    if tokenizer_name:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
        try:
            from .p2a_train import LABELS, SYSTEM
        except ImportError:
            from p2a_train import LABELS, SYSTEM
        system_prompt = SYSTEM
        target_lengths = {label: len(tokenizer.encode(value, add_special_tokens=False)) + 1
                          for label, value in LABELS.items()}
    reports = []
    global_by_split = []
    for dataset_path in paths:
        path = Path(dataset_path)
        stats = collections.Counter()
        labels = collections.Counter()
        exchanges = collections.defaultdict(collections.Counter)
        tickers = collections.Counter()
        ticker_gaps = collections.defaultdict(collections.Counter)
        ticker_dates = collections.Counter()
        prompt_hashes = collections.Counter()
        dates = []
        gaps = []
        over_limit = collections.Counter()
        token_lengths = []
        token_batch = []

        def count_token_batch():
            if not token_batch:
                return
            conversations, directions = zip(*token_batch)
            encoded = tokenizer.apply_chat_template(list(conversations), tokenize=True,
                                                   add_generation_prompt=True)
            for ids, direction in zip(encoded, directions):
                length = len(ids) + target_lengths[direction]
                token_lengths.append(length)
                if length > 4096:
                    over_limit[direction] += 1
            token_batch.clear()
        leaked_dates = []
        sector_keys = set()

        def inspect_keys(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    lowered = str(key).lower()
                    if any(word in lowered for word in ('sector', 'industry', 'ngành', 'nganh')):
                        sector_keys.add(str(key))
                    inspect_keys(value)
            elif isinstance(obj, list):
                for value in obj:
                    inspect_keys(value)

        with path.open(encoding='utf-8') as stream:
            for line_no, line in enumerate(stream, 1):
                row = json.loads(line)
                metadata = row.get('metadata') or {}
                label = metadata.get('label') or {}
                kind = metadata.get('kind', 'missing')
                direction = label.get('future_direction_120', 'missing')
                stats['rows'] += 1
                stats['kind_' + str(kind)] += 1
                labels[str(direction)] += 1
                if kind != 'bulk':
                    continue
                text = row.get('input', '')
                ticker, exchange, as_of, verified = read_identity(row)
                ticker_dates[(ticker, as_of)] += 1
                tickers[ticker] += 1
                exchanges[exchange]['bulk'] += 1
                exchanges[exchange]['label_' + str(direction)] += 1
                if as_of:
                    dates.append(as_of)
                    try:
                        cutoff = date.fromisoformat(as_of)
                    except ValueError:
                        stats['invalid_as_of'] += 1
                        cutoff = None
                    if cutoff:
                        later = []
                        for date_text in DATE_RE.findall(text):
                            try:
                                if date.fromisoformat(date_text) > cutoff:
                                    later.append(date_text)
                            except ValueError:
                                stats['invalid_prompt_date'] += 1
                        if later:
                            stats['rows_with_future_prompt_dates'] += 1
                            if len(leaked_dates) < 20:
                                leaked_dates.append({'line': line_no, 'ticker': ticker,
                                                     'as_of': as_of, 'dates': later[:5]})
                outcome = (label.get('future_outcomes') or {}).get('120') or {}
                endpoint = outcome.get('endpoint_date')
                if as_of and endpoint:
                    try:
                        gap = (date.fromisoformat(endpoint) - date.fromisoformat(as_of)).days
                        gaps.append(gap)
                        for threshold in THRESHOLDS:
                            if gap > threshold:
                                exchanges[exchange][f'gap_gt_{threshold}'] += 1
                                ticker_gaps[ticker][f'gap_gt_{threshold}'] += 1
                    except ValueError:
                        stats['invalid_endpoint_date'] += 1
                if any(term in text for term in ('future_direction_120', 'future_outcomes')):
                    stats['label_field_text_echo'] += 1
                inspect_keys(verified)
                prompt_hashes[_hash_text(text)] += 1
                if tokenizer and direction in ('UP', 'DOWN'):
                    messages = [{'role': 'system', 'content': system_prompt},
                                {'role': 'user', 'content': text}]
                    token_batch.append((messages, direction))
                    if len(token_batch) >= 128:
                        count_token_batch()
                if line_no % 20000 == 0:
                    print(f'AUDIT_PROGRESS file={path.name} lines={line_no}', flush=True)

        count_token_batch()

        gap_sorted = sorted(gaps)
        gap_summary = None
        if gap_sorted:
            quantile = lambda q: gap_sorted[min(len(gap_sorted) - 1,
                                                 int(q * (len(gap_sorted) - 1)))]
            gap_summary = {'count': len(gaps), 'min': gap_sorted[0], 'p10': quantile(.1),
                           'p50': quantile(.5), 'p90': quantile(.9), 'max': gap_sorted[-1]}
        exchange_report = {}
        for exchange, counts in sorted(exchanges.items()):
            exchange_report[exchange] = dict(counts)
        report = {
            'file': path.name, 'bytes': path.stat().st_size,
            'sha256': sha256(path),
            'rows': dict(stats), 'labels': dict(labels), 'tickers': len(tickers),
            'max_rows_per_ticker': max(tickers.values(), default=0),
            'ticker_rows_p50_p90': ([sorted(tickers.values())[int(.5 * (len(tickers) - 1))],
                                     sorted(tickers.values())[int(.9 * (len(tickers) - 1))]]
                                    if tickers else None),
            'duplicate_ticker_asof_rows': sum(v - 1 for v in ticker_dates.values() if v > 1),
            'duplicate_prompt_rows': sum(v - 1 for v in prompt_hashes.values() if v > 1),
            'endpoint_gap_days': gap_summary, 'exchange_counts': exchange_report,
            'tickers_with_gap_gt_200': sum(bool(x['gap_gt_200']) for x in ticker_gaps.values()),
            'tickers_with_gap_gt_365': sum(bool(x['gap_gt_365']) for x in ticker_gaps.values()),
            'date_range': [min(dates), max(dates)] if dates else None,
            'industry_sector_fields': sorted(sector_keys), 'future_prompt_date_examples': leaked_dates,
            'token_lengths': ({'count': len(token_lengths), 'over_4096': sum(over_limit.values()),
                              'over_4096_by_label': dict(over_limit), 'max': max(token_lengths)}
                             if token_lengths else None),
        }
        reports.append(report)
        global_by_split.append((set(ticker_dates), set(prompt_hashes)))
    if len(global_by_split) > 1:
        overlaps = {}
        for i, (left_td, left_hash) in enumerate(global_by_split):
            for j, (right_td, right_hash) in enumerate(global_by_split[i + 1:], i + 1):
                overlaps[f'{i}:{j}'] = {'ticker_asof': len(left_td & right_td),
                                         'prompt_hash': len(left_hash & right_hash)}
        return {'reports': reports, 'cross_split_overlaps': overlaps}
    return {'reports': reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', action='append', required=True,
                        help='JSONL path; repeat to compare splits')
    parser.add_argument('--tokenizer', help='optional exact HF/local tokenizer for 4096-token counts')
    parser.add_argument('--output', help='write JSON report; stdout otherwise')
    args = parser.parse_args()
    result = audit(args.input, args.tokenizer)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        Path(args.output).write_text(serialized, encoding='utf-8')
    else:
        print(serialized, end='')


if __name__ == '__main__':
    main()
