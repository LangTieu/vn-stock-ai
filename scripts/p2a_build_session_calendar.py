#!/usr/bin/env python3
"""Combine documented 2014-2016 closures with Finhay's observed index sessions."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

EXCHANGES = ('HOSE', 'HNX', 'UPCOM')
START = date(2014, 1, 1)
INDEX_CUTOFF = date(2017, 1, 1)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(closures_path, index_sessions_path, output_path, manifest_path):
    closures = defaultdict(dict)
    with Path(closures_path).open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        required = {'exchange', 'date', 'source_url', 'source_note'}
        if not required <= set(reader.fieldnames or ()):
            raise ValueError(f'closure CSV requires columns {sorted(required)}')
        for row in reader:
            exchange = row['exchange'].strip().upper()
            day = date.fromisoformat(row['date'])
            if day >= INDEX_CUTOFF or exchange not in EXCHANGES:
                raise ValueError(f'closure outside 2014-2016/exchanges: {exchange} {day}')
            if day in closures[exchange]:
                raise ValueError(f'duplicate closure: {exchange} {day}')
            closures[exchange][day] = (row['source_url'], row['source_note'])
    if set(closures) != set(EXCHANGES):
        raise ValueError(f'need sourced closures for all exchanges: {sorted(closures)}')

    observed = defaultdict(set)
    index_source = {}
    with gzip.open(index_sessions_path, 'rt', newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if not {'exchange', 'date'} <= set(reader.fieldnames or ()):
            raise ValueError('Finhay index session CSV requires exchange,date')
        for row in reader:
            exchange = row['exchange'].strip().upper()
            day = date.fromisoformat(row['date'])
            if exchange not in EXCHANGES:
                continue
            if day < INDEX_CUTOFF:
                raise ValueError(f'index rows before expected Finhay history range: {exchange} {day}')
            if day.weekday() >= 5:
                raise ValueError(f'index has weekend bar: {exchange} {day}')
            observed[exchange].add(day)
            index_source[(exchange, day)] = row.get('source_index') or ''

    rows = []
    early_counts = {}
    for exchange in EXCHANGES:
        if not observed[exchange]:
            raise ValueError(f'no Finhay index sessions for {exchange}')
        first_index = min(observed[exchange])
        if first_index > INDEX_CUTOFF + timedelta(days=14):
            raise ValueError(f'{exchange} index history begins too late: {first_index}')
        days = START
        early = []
        while days < first_index:
            if days.weekday() < 5 and days not in closures[exchange]:
                source_url = ','.join(sorted({url for url, _ in closures[exchange].values()}))
                early.append({'exchange': exchange, 'date': days.isoformat(),
                              'source_index': 'weekday_calendar_minus_cited_exchange_closures',
                              'source_reference': source_url})
            days += timedelta(days=1)
        early_counts[exchange] = len(early)
        rows.extend(early)
        for day in sorted(observed[exchange]):
            rows.append({'exchange': exchange, 'date': day.isoformat(),
                         'source_index': index_source[(exchange, day)],
                         'source_reference': 'Finhay daily exchange-index history'})

    rows.sort(key=lambda row: (row['exchange'], row['date']))
    keys = [(row['exchange'], row['date']) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate exchange/date rows after merge')
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, 'wt', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['exchange', 'date', 'source_index', 'source_reference'])
        writer.writeheader()
        writer.writerows(rows)
    years = Counter((row['exchange'], row['date'][:4]) for row in rows)
    manifest = {
        'method': '2014-2016 weekdays minus dated exchange-closure notices; 2017 onward observed Finhay index sessions',
        'sources': sorted({url for items in closures.values() for url, _ in items.values()}),
        'closures_sha256': sha256(closures_path),
        'finhay_index_sessions_sha256': sha256(index_sessions_path),
        'output_sha256': sha256(output_path),
        'rows_by_exchange_year': {f'{ex}:{year}': count for (ex, year), count in sorted(years.items())},
        'derived_weekday_rows_2014_2016': early_counts,
        'official_session_status': 'early dates are derived from cited exchange holiday notices and weekdays; later dates are observed index bars',
    }
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--closures', required=True)
    parser.add_argument('--finhay-index-sessions', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    report = build(args.closures, args.finhay_index_sessions, args.output, args.manifest)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
