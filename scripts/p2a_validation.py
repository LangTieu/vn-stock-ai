#!/usr/bin/env python3
"""Create a deterministic, class-balanced, ticker/quarter-stratified P2a slice."""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

BRIEF = re.compile(r"^BRIEF:.*?mã\s+([A-Z0-9._-]+)\s+tại\s+(\d{4}-\d{2}-\d{2})", re.I)
DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def row_strata(row):
    metadata = row.get('metadata') or {}
    text = row.get('input', '')
    ticker = None
    as_of = metadata.get('market_as_of') or metadata.get('as_of')
    first_line = text.splitlines()[0] if text else ''
    match = BRIEF.search(first_line)
    if match:
        ticker, as_of = match.group(1).upper(), as_of or match.group(2)
    if not ticker or not as_of:
        marker = 'VERIFIED_DATA\n'
        if marker in text:
            try:
                verified, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1])
            except (TypeError, ValueError):
                verified = {}
            ticker = ticker or verified.get('ticker') or verified.get('symbol')
            as_of = as_of or verified.get('as_of') or verified.get('date')
    if not ticker or not as_of:
        raise ValueError('Cannot stratify row: ticker/date missing from BRIEF and VERIFIED_DATA')
    date_match = DATE.search(str(as_of))
    if not date_match:
        raise ValueError(f'Invalid date for validation stratum: {as_of!r}')
    year, month = int(date_match.group(1)), int(date_match.group(2))
    return str(ticker).upper(), f'{year}-Q{(month - 1) // 3 + 1}'


def file_hash(path, algorithm='sha256'):
    digest = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def create_slice(source, output, manifest, per_class=32, seed=42):
    if per_class < 1:
        raise ValueError('per_class must be positive')
    grouped = {label: defaultdict(list) for label in ('UP', 'DOWN')}
    eligible = 0
    with Path(source).open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream):
            row = json.loads(line)
            metadata = row.get('metadata') or {}
            if metadata.get('kind') != 'bulk':
                continue
            label = (metadata.get('label') or {}).get('future_direction_120')
            if label not in grouped:
                continue
            ticker, quarter = row_strata(row)
            key = ticker, quarter
            row_hash = hashlib.sha256(f'{seed}\0{line}'.encode()).hexdigest()
            grouped[label][key].append((row_hash, line_number, line))
            eligible += 1
    sample_count = min(per_class, *(sum(map(len, grouped[label].values()))
                                   for label in ('UP', 'DOWN')))
    if sample_count == 0:
        raise ValueError('Holdout has no eligible UP/DOWN bulk examples')
    selected = []
    class_counts = {}
    for label in ('UP', 'DOWN'):
        strata = grouped[label]
        for candidates in strata.values():
            candidates.sort(key=lambda item: item[0])
        keys = sorted(strata)
        positions = {key: 0 for key in keys}
        chosen = []
        while len(chosen) < sample_count:
            progressed = False
            for key in keys:
                pos = positions[key]
                if pos < len(strata[key]):
                    chosen.append((label, key, *strata[key][pos]))
                    positions[key] += 1
                    progressed = True
                    if len(chosen) == sample_count:
                        break
            if not progressed:
                break
        class_counts[label] = len(chosen)
        selected.extend(chosen)
    selected.sort(key=lambda item: (item[0], item[1], item[2]))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', encoding='utf-8') as stream:
        for item in selected:
            line = item[4]
            stream.write(line if line.endswith('\n') else line + '\n')
    ticker_counts = Counter(item[1][0] for item in selected)
    quarter_counts = Counter(item[1][1] for item in selected)
    result = {
        'method': 'fixed-seed round-robin by ticker x calendar-quarter; equal UP/DOWN',
        'seed': seed, 'per_class': sample_count,
        'selected_count': len(selected), 'eligible_bulk_up_down': eligible,
        'class_counts': class_counts,
        'source_md5': file_hash(source, 'md5'),
        'source_sha256': file_hash(source),
        'slice_sha256': file_hash(output),
        'ticker_count': len(ticker_counts), 'tickers': dict(sorted(ticker_counts.items())),
        'time_bucket_count': len(quarter_counts),
        'time_buckets': dict(sorted(quarter_counts.items())),
        'selected_row_hashes': [item[2] for item in selected],
    }
    Path(manifest).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--per-class', type=int, default=32)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    result = create_slice(args.input, args.output, args.manifest, args.per_class, args.seed)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
