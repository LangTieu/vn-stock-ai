#!/usr/bin/env python3
"""Create a fixed, class-balanced P2a validation slice stratified by ticker/time."""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

BRIEF = re.compile(r"^BRIEF:.*?mã\s+([A-Z0-9._-]+)\s+tại\s+(\d{4}-\d{2}-\d{2})", re.I)
DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def row_strata(row):
    meta = row.get('metadata') or {}
    text = row.get('input', '')
    ticker = None
    as_of = meta.get('market_as_of') or meta.get('as_of')
    first = text.splitlines()[0] if text else ''
    match = BRIEF.search(first)
    if match:
        ticker = match.group(1).upper()
        as_of = as_of or match.group(2)
    if not ticker or not as_of:
        marker = 'VERIFIED_DATA\n'
        if marker in text:
            try:
                verified, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1])
            except (ValueError, TypeError):
                verified = {}
            ticker = ticker or verified.get('ticker') or verified.get('symbol')
            as_of = as_of or verified.get('as_of') or verified.get('date')
    if not ticker or not as_of:
        raise ValueError('Cannot stratify row: ticker/date missing from brief and VERIFIED_DATA')
    date_match = DATE.search(str(as_of))
    if not date_match:
        raise ValueError(f'Invalid as_of date for validation stratum: {as_of!r}')
    year, month = int(date_match.group(1)), int(date_match.group(2))
    quarter = (month - 1) // 3 + 1
    return str(ticker).upper(), f'{year}-Q{quarter}'


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path):
    digest = hashlib.md5()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def create_validation_slice(source, output, manifest, per_class=32, seed=42):
    if per_class < 1:
        raise ValueError('per_class must be positive')
    groups = {label: defaultdict(list) for label in ('UP', 'DOWN')}
    rows_seen = 0
    with Path(source).open(encoding='utf-8') as stream:
        for line_no, line in enumerate(stream):
            row = json.loads(line)
            meta = row.get('metadata') or {}
            if meta.get('kind') != 'bulk':
                continue
            label = (meta.get('label') or {}).get('future_direction_120')
            if label not in groups:
                continue
            ticker, quarter = row_strata(row)
            key = (ticker, quarter)
            digest = hashlib.sha256(f'{seed}\0{line}'.encode()).hexdigest()
            groups[label][key].append((digest, line_no, line))
            rows_seen += 1
    available = min(sum(map(len, groups[label].values())) for label in groups)
    count = min(per_class, available)
    if not count:
        raise ValueError('No UP/DOWN bulk holdout rows available for validation')

    selected = []
    selected_by_label = {}
    for label in ('UP', 'DOWN'):
        strata = groups[label]
        for values in strata.values():
            values.sort(key=lambda item: item[0])
        keys = sorted(strata)
        positions = {key: 0 for key in keys}
        chosen = []
        while len(chosen) < count:
            progressed = False
            for key in keys:
                pos = positions[key]
                if pos < len(strata[key]):
                    chosen.append((label, key, *strata[key][pos]))
                    positions[key] += 1
                    progressed = True
                    if len(chosen) == count:
                        break
            if not progressed:
                break
        selected.extend(chosen)
        selected_by_label[label] = len(chosen)

    selected.sort(key=lambda item: (item[0], item[1], item[2]))
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as stream:
        for _, _, _, line in selected:
            stream.write(line if line.endswith('\n') else line + '\n')
    ticker_counts = Counter(item[1][0] for item in selected)
    quarter_counts = Counter(item[1][1] for item in selected)
    manifest_data = {
        'method': 'deterministic round-robin across ticker x calendar-quarter strata, balanced UP/DOWN',
        'seed': seed,
        'per_class': count,
        'selected_count': len(selected),
        'class_counts': selected_by_label,
        'source_rows_up_down': rows_seen,
        'source_md5': md5_file(source),
        'source_sha256': sha256_file(source),
        'slice_sha256': sha256_file(out),
        'ticker_count': len(ticker_counts),
        'tickers': dict(sorted(ticker_counts.items())),
        'time_bucket_count': len(quarter_counts),
        'time_buckets': dict(sorted(quarter_counts.items())),
        'selected_row_hashes': [item[2] for item in selected],
    }
    Path(manifest).write_text(json.dumps(manifest_data, ensure_ascii=False,
                                        indent=2) + '\n', encoding='utf-8')
    return manifest_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--per-class', type=int, default=32)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(create_validation_slice(args.input, args.output, args.manifest,
                                             args.per_class, args.seed), ensure_ascii=False,
                     sort_keys=True))


if __name__ == '__main__':
    main()
