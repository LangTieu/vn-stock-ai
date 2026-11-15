#!/usr/bin/env python3
"""Validate generated Finhay source artifacts without assuming undocumented semantics."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


REQUIRED = {
    'exchange_sessions.csv.gz': {'exchange', 'date'},
    'daily_prices.csv.gz': {'security_id', 'ticker', 'exchange', 'date', 'open', 'high',
                            'low', 'close', 'volume', 'adjusted_total_return_close'},
    'corporate_actions.csv.gz': {'security_id', 'ticker', 'exchange', 'ex_date', 'record_date',
                                 'action_type', 'details_json'},
    'security_history.csv.gz': {'security_id', 'ticker', 'exchange', 'listing_date',
                                'delisting_date', 'sector_code', 'sector_valid_from',
                                'sector_valid_to'},
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _reader(path):
    stream = gzip.open(path, 'rt', encoding='utf-8', newline='')
    return csv.DictReader(stream), stream


def validate(root, expected_p1_tickers=None):
    root = Path(root)
    report = {'directory': str(root), 'files': {}, 'errors': [], 'warnings': [], 'gate': {}}
    sessions = defaultdict(set)
    session_counts = Counter()
    session_duplicate_rows = 0
    session_source = Counter()
    session_sources_by_exchange = defaultdict(Counter)
    path = root / 'exchange_sessions.csv.gz'
    reader, stream = _reader(path)
    missing = sorted(REQUIRED[path.name] - set(reader.fieldnames or ()))
    if missing:
        report['errors'].append(f'{path.name} missing columns {missing}')
    else:
        for line_no, row in enumerate(reader, 2):
            exchange = row['exchange'].strip().upper()
            try:
                day = date.fromisoformat(row['date'])
            except ValueError:
                report['errors'].append(f'{path.name}:{line_no} invalid date')
                continue
            if day in sessions[exchange]:
                session_duplicate_rows += 1
            sessions[exchange].add(day)
            session_counts[exchange] += 1
            session_source[row.get('source_index') or 'unspecified'] += 1
            session_sources_by_exchange[exchange][row.get('source_index') or 'unspecified'] += 1
    stream.close()
    report['files'][path.name] = {'sha256': sha256(path), 'sessions_by_exchange':
                                  {k: len(v) for k, v in sorted(sessions.items())},
                                  'duplicate_session_rows': session_duplicate_rows,
                                  'sources': dict(session_source),
                                  'sources_by_exchange': {ex: dict(v) for ex, v in sorted(
                                      session_sources_by_exchange.items())}}

    ticker_dates = defaultdict(set)
    prices_by_exchange = Counter()
    price_dates_by_exchange = defaultdict(list)
    adjusted_present = Counter()
    off_calendar = Counter()
    bad_prices = 0
    path = root / 'daily_prices.csv.gz'
    reader, stream = _reader(path)
    missing = sorted(REQUIRED[path.name] - set(reader.fieldnames or ()))
    if missing:
        report['errors'].append(f'{path.name} missing columns {missing}')
    else:
        for line_no, row in enumerate(reader, 2):
            ticker, exchange = row['ticker'].strip().upper(), row['exchange'].strip().upper()
            try:
                day = date.fromisoformat(row['date'])
            except ValueError:
                report['errors'].append(f'{path.name}:{line_no} invalid date')
                continue
            key = (exchange, ticker)
            if day in ticker_dates[key]:
                report['errors'].append(f'{path.name}:{line_no} duplicate ticker-date')
            ticker_dates[key].add(day)
            prices_by_exchange[exchange] += 1
            price_dates_by_exchange[exchange].append(day)
            if row['adjusted_total_return_close'].strip():
                adjusted_present[exchange] += 1
            if sessions.get(exchange) and day not in sessions[exchange]:
                off_calendar[exchange] += 1
            for column in ('open', 'high', 'low', 'close', 'volume'):
                raw = row.get(column, '').strip()
                if raw:
                    try:
                        value = float(raw)
                        if column != 'volume' and value <= 0:
                            bad_prices += 1
                    except ValueError:
                        bad_prices += 1
    stream.close()
    price_tickers = {ticker for _, ticker in ticker_dates}
    report['files'][path.name] = {
        'sha256': sha256(path), 'rows': sum(prices_by_exchange.values()),
        'tickers': len(price_tickers), 'rows_by_exchange': dict(prices_by_exchange),
        'adjusted_total_return_rows_by_exchange': dict(adjusted_present),
        'prices_not_on_calendar_by_exchange': dict(off_calendar), 'invalid_numeric_values': bad_prices,
        'price_date_range_by_exchange': {
            exchange: [min(days).isoformat(), max(days).isoformat()]
            for exchange, days in sorted(price_dates_by_exchange.items()) if days
        },
        'session_date_range_by_exchange': {
            exchange: [min(days).isoformat(), max(days).isoformat()]
            for exchange, days in sorted(sessions.items()) if days
        },
    }

    actions_by_ticker = Counter()
    action_types = Counter()
    missing_action_dates = Counter()
    path = root / 'corporate_actions.csv.gz'
    reader, stream = _reader(path)
    missing = sorted(REQUIRED[path.name] - set(reader.fieldnames or ()))
    if missing:
        report['errors'].append(f'{path.name} missing columns {missing}')
    else:
        for line_no, row in enumerate(reader, 2):
            ticker = row['ticker'].strip().upper()
            actions_by_ticker[ticker] += 1
            action_types[row['action_type'] or 'UNKNOWN'] += 1
            if not row['ex_date']:
                missing_action_dates[row['action_type'] or 'UNKNOWN'] += 1
            try:
                json.loads(row['details_json'] or '{}')
            except ValueError:
                report['errors'].append(f'{path.name}:{line_no} invalid details_json')
    stream.close()
    report['files'][path.name] = {'sha256': sha256(path),
                                  'rows': sum(actions_by_ticker.values()),
                                  'tickers_with_actions': len(actions_by_ticker),
                                  'action_types': dict(action_types),
                                  'missing_ex_date_by_type': dict(missing_action_dates)}

    history_symbols = set()
    history_valid_intervals = 0
    history_current_sector = 0
    path = root / 'security_history.csv.gz'
    reader, stream = _reader(path)
    missing = sorted(REQUIRED[path.name] - set(reader.fieldnames or ()))
    if missing:
        report['errors'].append(f'{path.name} missing columns {missing}')
    else:
        for row in reader:
            symbol = row['security_id'].strip().upper()
            if symbol:
                history_symbols.add(symbol)
            if row['sector_code']:
                history_current_sector += 1
            if row['sector_valid_from'] or row['sector_valid_to']:
                history_valid_intervals += 1
    stream.close()
    report['files'][path.name] = {'sha256': sha256(path), 'rows': len(history_symbols),
                                  'symbols': len(history_symbols),
                                  'current_sector_rows': history_current_sector,
                                  'historical_sector_intervals': history_valid_intervals}

    expected = set(expected_p1_tickers or ())
    missing_prices = sorted(expected - price_tickers)
    report['p1_ticker_coverage'] = {
        'expected_tickers': len(expected), 'price_tickers': len(price_tickers),
        'missing_expected_tickers': len(missing_prices),
        'missing_examples': missing_prices[:30],
    }
    report['gate'] = {
        'source_artifacts_schema_valid': not report['errors'],
        'official_exchange_session_calendar': False,
        'sourced_early_closures_plus_observed_index_sessions': all(
            any('weekday_calendar_minus_cited_exchange_closures' in source
                for source in session_sources_by_exchange[exchange])
            and any(source in {'VNINDEX', 'HNXINDEX', 'UPCOMINDEX'}
                    for source in session_sources_by_exchange[exchange])
            for exchange in ('HOSE', 'HNX', 'UPCOM')),
        'documented_adjusted_total_return_price': bool(adjusted_present),
        'historical_universe_point_in_time': False,
        'historical_sector_membership_point_in_time': history_valid_intervals > 0,
        'complete_p1_ticker_price_coverage': not missing_prices if expected else False,
        'passes': False,
    }
    if session_duplicate_rows:
        report['errors'].append(f'duplicate exchange session rows: {session_duplicate_rows}')
    if bad_prices:
        report['errors'].append(f'invalid numeric price/volume cells: {bad_prices}')
    if off_calendar:
        report['warnings'].append(f'price bars outside supplied session date set: {dict(off_calendar)}')
    if not adjusted_present:
        report['warnings'].append('Adjusted total-return price is blank/unavailable; do not relabel as adjusted.')
    if expected and missing_prices:
        report['warnings'].append('Some P1 tickers have no Finhay price history.')
    report['gate']['passes'] = (not report['errors']
                                and report['gate']['sourced_early_closures_plus_observed_index_sessions']
                                and report['gate']['documented_adjusted_total_return_price']
                                and report['gate']['historical_universe_point_in_time']
                                and report['gate']['historical_sector_membership_point_in_time']
                                and report['gate']['complete_p1_ticker_price_coverage'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='data/p2a-label-v2')
    parser.add_argument('--p1-train')
    parser.add_argument('--p1-holdout')
    parser.add_argument('--output', default='validation.json')
    args = parser.parse_args()
    expected = set()
    if args.p1_train or args.p1_holdout:
        if not (args.p1_train and args.p1_holdout):
            parser.error('--p1-train and --p1-holdout must be supplied together')
        for path in (args.p1_train, args.p1_holdout):
            with Path(path).open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if (row.get('metadata') or {}).get('kind') != 'bulk':
                        continue
                    from p2a_relabel import row_identity
                    ticker, _, _ = row_identity(row)
                    expected.add(ticker)
    report = validate(args.data_dir, expected)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passes': report['gate']['passes'],
                      'errors': len(report['errors']), 'warnings': len(report['warnings']),
                      'report': str(output)}, sort_keys=True))


if __name__ == '__main__':
    main()
