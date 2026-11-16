#!/usr/bin/env python3
"""Build sessions only from observed exchange-index and stock-price rows."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

EXCHANGES = ('HOSE', 'HNX', 'UPCOM')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(closures_path, index_sessions_path, output_path, manifest_path, price_sessions_path=None):
    closures = defaultdict(set)
    closure_sources = set()
    with Path(closures_path).open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        required = {'exchange', 'date', 'source_url', 'source_note'}
        if not required <= set(reader.fieldnames or ()):
            raise ValueError(f'closure CSV requires columns {sorted(required)}')
        for row in reader:
            exchange = row['exchange'].strip().upper()
            day = date.fromisoformat(row['date'])
            if exchange not in EXCHANGES:
                raise ValueError(f'closure for unknown exchange: {exchange} {day}')
            if day in closures[exchange]:
                raise ValueError(f'duplicate closure: {exchange} {day}')
            closures[exchange].add(day)
            closure_sources.add(row['source_url'])
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
            if day.weekday() >= 5:
                raise ValueError(f'index has weekend bar: {exchange} {day}')
            if day in closures[exchange]:
                raise ValueError(f'index row falls on a sourced exchange closure: {exchange} {day}')
            observed[exchange].add(day)
            index_source[(exchange, day)] = row.get('source_index') or ''

    row_map = {}
    for exchange in EXCHANGES:
        for day in sorted(observed[exchange]):
            row_map[(exchange, day.isoformat())] = {
                'exchange': exchange, 'date': day.isoformat(),
                'source_index': index_source[(exchange, day)],
                'source_reference': 'Finhay daily exchange-index history'}

    price_rows_examined = 0
    new_sessions_from_prices = 0
    rejected_price_rows = 0
    if price_sessions_path:
        with gzip.open(price_sessions_path, 'rt', newline='', encoding='utf-8') as stream:
            reader = csv.DictReader(stream)
            if not {'exchange', 'date', 'open', 'high', 'low', 'close'} <= set(reader.fieldnames or ()):
                raise ValueError('Finhay daily prices must contain exchange,date,OHLC columns')
            for row in reader:
                price_rows_examined += 1
                exchange = row['exchange'].strip().upper()
                if exchange not in EXCHANGES:
                    continue
                try:
                    day = date.fromisoformat(row['date'])
                    close = float(row['close'])
                except (TypeError, ValueError):
                    rejected_price_rows += 1
                    continue
                if not math.isfinite(close) or close <= 0 or day.weekday() >= 5:
                    rejected_price_rows += 1
                    continue
                if day in closures[exchange]:
                    raise ValueError(f'price row falls on a sourced exchange closure: {exchange} {day}')
                key = exchange, day.isoformat()
                current = row_map.get(key)
                if current:
                    if 'Finhay stock OHLCV bar' not in current['source_index']:
                        current['source_index'] += '+Finhay stock OHLCV bar'
                        current['source_reference'] += '; Finhay daily stock OHLCV history'
                else:
                    row_map[key] = {'exchange': exchange, 'date': day.isoformat(),
                                    'source_index': 'Finhay stock OHLCV bar',
                                    'source_reference': 'Finhay daily stock OHLCV history'}
                    new_sessions_from_prices += 1

    rows = list(row_map.values())

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
    date_ranges = {}
    for exchange in EXCHANGES:
        dates = [row['date'] for row in rows if row['exchange'] == exchange]
        if dates:
            date_ranges[exchange] = [dates[0], dates[-1]]
    manifest = {
        'method': 'observed exchange-index session rows plus observed stock-price dates; no inferred dates',
        'sources': sorted(closure_sources),
        'closures_sha256': sha256(closures_path),
        'finhay_index_sessions_sha256': sha256(index_sessions_path),
        'finhay_daily_prices_sha256': sha256(price_sessions_path) if price_sessions_path else None,
        'output_sha256': sha256(output_path),
        'rows_by_exchange_year': {f'{ex}:{year}': count for (ex, year), count in sorted(years.items())},
        'observed_date_range_by_exchange': date_ranges,
        'sourced_closures_used_as_sessions': 0,
        'stock_price_rows_examined': price_rows_examined,
        'new_sessions_added_from_stock_prices': new_sessions_from_prices,
        'rejected_stock_price_rows_without_valid_close_or_date': rejected_price_rows,
        'session_provenance': 'each output date comes from an observed index row or positive-close stock-price row',
        'official_session_status': 'not an official calendar; observed dates only',
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
    parser.add_argument('--finhay-daily-prices', help='optional daily prices CSV.GZ to add observed exchange trading dates missing from the index series')
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    report = build(args.closures, args.finhay_index_sessions, args.output, args.manifest,
                   args.finhay_daily_prices)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
