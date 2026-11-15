#!/usr/bin/env python3
"""Audit P1 coverage against gated HF OHLCV source without exporting prices."""
import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from p2a_relabel import row_identity

REPO_ID = 'datnkhptit/vn-stock-ohlcv'
REVISION = '97830e8d9ec0c44c067cacb950de424975ead742'
TRAIN_URL = 'https://huggingface.co/datasets/Jerlob/vn-stock-ai-p1/resolve/main/p1_train.jsonl.gz'
HOLDOUT_URL = 'https://huggingface.co/datasets/Jerlob/vn-stock-ai-p1/resolve/main/p1_holdout.jsonl'
TRAIN_MD5 = 'f6273e8a12e35fe1027f29ca2127b9c0'
HOLDOUT_MD5 = '5f48d9b13d2f2cce0a730067b2f3094c'
EXCHANGE_INDEX = {'VNINDEX': 'HOSE', 'HNXINDEX': 'HNX', 'UPCOMINDEX': 'UPCOM'}


def _row_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _price_columns(names):
    normalized = {str(name).strip().lower(): name for name in names}
    date_col = next((normalized[k] for k in ('date', 'trading_date', 'time', 'timestamp')
                     if k in normalized), None)
    close_col = next((normalized[k] for k in ('close_raw', 'close', 'raw_close')
                      if k in normalized), None)
    adjusted_col = next((normalized[k] for k in
                         ('close_adj', 'adjusted_close', 'adj_close', 'close_adjusted')
                         if k in normalized), None)
    exchange_col = next((normalized[k] for k in ('exchange', 'market', 'board')
                         if k in normalized), None)
    return date_col, close_col, adjusted_col, exchange_col


def _candidate_paths(paths, symbols):
    by_symbol = {}
    index_paths = {}
    for symbol in sorted(symbols):
        path = f'ohlcv/silver/{symbol}/ohlcv_daily.parquet'
        if path in paths:
            by_symbol[symbol] = path
    for index in EXCHANGE_INDEX:
        candidates = [path for path in paths if path.endswith(
            f'/silver/{index}/ohlcv_daily.parquet')]
        if f'ohlcv/silver/{index}/ohlcv_daily.parquet' in candidates:
            index_paths[index] = f'ohlcv/silver/{index}/ohlcv_daily.parquet'
        elif candidates:
            index_paths[index] = sorted(candidates)[0]
    return by_symbol, index_paths


def _p1_inputs(directory):
    from p2a_train import dataset_path, HOLDOUT_MD5 as EXPECTED_HOLDOUT_MD5
    from p2a_train import TRAIN_MD5 as EXPECTED_TRAIN_MD5

    root = Path(directory)
    train = dataset_path(TRAIN_URL, root / 'p1_train.jsonl', EXPECTED_TRAIN_MD5)
    holdout = dataset_path(HOLDOUT_URL, root / 'p1_holdout.jsonl', EXPECTED_HOLDOUT_MD5)
    rows = []
    for path in (train, holdout):
        with open(path, encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                if (row.get('metadata') or {}).get('kind') == 'bulk':
                    ticker, exchange, as_of = row_identity(row)
                    rows.append((Path(path).name, ticker, exchange, as_of))
    return rows


def _coverage(p1_rows, prices, sessions, source_symbols):
    reports = []
    positions_by_exchange = {
        exchange: {day: index for index, day in enumerate(calendar)}
        for exchange, calendar in sessions.items()
    }
    for split in ('p1_train.jsonl', 'p1_holdout.jsonl'):
        counts = Counter()
        by_year = Counter()
        by_exchange = Counter()
        for row_split, ticker, exchange, as_of in p1_rows:
            if row_split != split:
                continue
            year = as_of.year
            counts['rows'] += 1
            by_year[(year, 'rows')] += 1
            by_exchange[(exchange, 'rows')] += 1
            if ticker not in source_symbols:
                counts['ticker_not_in_source'] += 1
                by_year[(year, 'ticker_not_in_source')] += 1
                continue
            calendar = sessions.get(exchange, [])
            positions = positions_by_exchange.get(exchange, {})
            if as_of not in positions:
                counts['as_of_not_in_observed_calendar'] += 1
                by_year[(year, 'as_of_not_in_observed_calendar')] += 1
                continue
            end_i = positions[as_of] + 120
            if end_i >= len(calendar):
                counts['horizon_not_matured'] += 1
                by_year[(year, 'horizon_not_matured')] += 1
                continue
            endpoint = calendar[end_i]
            start_raw, start_adj = prices.get((ticker, exchange, as_of),
                                              prices.get((ticker, '', as_of), (None, None)))
            end_raw, end_adj = prices.get((ticker, exchange, endpoint),
                                          prices.get((ticker, '', endpoint), (None, None)))
            if start_raw is None or end_raw is None:
                counts['missing_raw_endpoint_quote'] += 1
                by_year[(year, 'missing_raw_endpoint_quote')] += 1
                continue
            counts['raw_exact_endpoints'] += 1
            by_year[(year, 'raw_exact_endpoints')] += 1
            by_exchange[(exchange, 'raw_exact_endpoints')] += 1
            if start_adj is not None and end_adj is not None:
                counts['adjusted_close_exact_endpoints'] += 1
                by_year[(year, 'adjusted_close_exact_endpoints')] += 1
                by_exchange[(exchange, 'adjusted_close_exact_endpoints')] += 1
        reports.append({
            'split': split, 'counts': dict(sorted(counts.items())),
            'by_year': {f'{year}:{metric}': count
                        for (year, metric), count in sorted(by_year.items())},
            'by_exchange': {f'{exchange}:{metric}': count
                            for (exchange, metric), count in sorted(by_exchange.items())},
        })
    return reports


def audit(output, p1_work):
    token = os.environ.get('HF_TOKEN')
    if not token:
        result = {'status': 'blocked', 'reason': 'HF_TOKEN unavailable; no gate terms accepted'}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'status': result['status'], 'reason': result['reason']}))
        return result

    from huggingface_hub import HfApi, snapshot_download
    api = HfApi(token=token)
    try:
        info = api.dataset_info(REPO_ID, revision=REVISION)
        paths = set(api.list_repo_files(REPO_ID, repo_type='dataset', revision=REVISION))
    except Exception as error:
        response = getattr(error, 'response', None)
        result = {'status': 'blocked', 'repo': REPO_ID, 'revision': REVISION,
                  'reason': type(error).__name__,
                  'http_status': getattr(response, 'status_code', None),
                  'gate_terms_accepted_by_this_job': False}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'status': result['status'], 'reason': result['reason'],
                          'http_status': result['http_status']}))
        return result

    p1_rows = _p1_inputs(p1_work)
    p1_symbols = {ticker for _, ticker, _, _ in p1_rows}
    symbol_paths, index_paths = _candidate_paths(paths, p1_symbols)
    selected_paths = sorted(set(symbol_paths.values()) | set(index_paths.values()))
    if not selected_paths:
        result = {'status': 'no_matching_source_files', 'repo': REPO_ID,
                  'revision': REVISION, 'p1_symbol_count': len(p1_symbols),
                  'p1_symbols_with_silver_file': 0,
                  'gate_terms_accepted_by_this_job': False}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'status': result['status'], 'p1_symbol_count': len(p1_symbols)}))
        return result

    import pyarrow.parquet as parquet
    source_prices = {}
    source_exchange_missing = 0
    sessions = defaultdict(set)
    row_count = 0
    adjusted_count = 0
    schemas = Counter()
    date_min, date_max = {}, {}
    with tempfile.TemporaryDirectory(prefix='p2a-hf-ohlcv-') as temporary:
        try:
            local = snapshot_download(repo_id=REPO_ID, repo_type='dataset', revision=REVISION,
                                      allow_patterns=selected_paths, token=token,
                                      local_dir=temporary)
        except Exception as error:
            response = getattr(error, 'response', None)
            result = {'status': 'blocked', 'repo': REPO_ID, 'revision': REVISION,
                      'reason': type(error).__name__,
                      'http_status': getattr(response, 'status_code', None),
                      'p1_ticker_count': len(p1_symbols),
                      'source_silver_files_selected': len(symbol_paths),
                      'gate_terms_accepted_by_this_job': False}
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({'status': result['status'], 'reason': result['reason'],
                              'http_status': result['http_status']}, sort_keys=True))
            return result
        for symbol, path in symbol_paths.items():
            table = parquet.read_table(Path(local) / path)
            date_col, close_col, adjusted_col, exchange_col = _price_columns(table.column_names)
            schemas[';'.join(table.column_names)] += 1
            if not date_col or not close_col:
                continue
            data = table.to_pydict()
            for i, value in enumerate(data[date_col]):
                day = _row_date(value)
                if day is None:
                    continue
                exchange = str(data[exchange_col][i]).upper() if exchange_col else ''
                if exchange in ('HOSE', 'HNX', 'UPCOM'):
                    sessions[exchange].add(day)
                    date_min[exchange] = min(date_min.get(exchange, day), day)
                    date_max[exchange] = max(date_max.get(exchange, day), day)
                else:
                    exchange = ''
                    source_exchange_missing += 1
                raw_close = data[close_col][i]
                try:
                    raw_close = float(raw_close)
                    if not (raw_close > 0 and raw_close < float('inf')):
                        raw_close = None
                except (TypeError, ValueError):
                    raw_close = None
                adjusted_close = data[adjusted_col][i] if adjusted_col else None
                try:
                    adjusted_close = float(adjusted_close)
                    if not (adjusted_close > 0 and adjusted_close < float('inf')):
                        adjusted_close = None
                except (TypeError, ValueError):
                    adjusted_close = None
                if adjusted_close is not None:
                    adjusted_count += 1
                if raw_close is not None and exchange in ('HOSE', 'HNX', 'UPCOM'):
                    source_prices[(symbol, exchange, day)] = (raw_close, adjusted_close)
                    row_count += 1
                elif raw_close is not None:
                    source_prices[(symbol, '', day)] = (raw_close, adjusted_close)
                    row_count += 1

        for index_symbol, exchange in EXCHANGE_INDEX.items():
            path = index_paths.get(index_symbol)
            if not path:
                continue
            table = parquet.read_table(Path(local) / path)
            date_col, _, _, _ = _price_columns(table.column_names)
            schemas[';'.join(table.column_names)] += 1
            if not date_col:
                continue
            for value in table[date_col].to_pylist():
                day = _row_date(value)
                if day:
                    sessions[exchange].add(day)
                    date_min[exchange] = min(date_min.get(exchange, day), day)
                    date_max[exchange] = max(date_max.get(exchange, day), day)

    ordered_sessions = {exchange: sorted(days) for exchange, days in sessions.items()}
    coverage = _coverage(p1_rows, source_prices, ordered_sessions, set(symbol_paths))
    result = {
        'status': 'audited', 'method': 'existing source OHLCV only; no prices or labels exported',
        'repo': REPO_ID, 'revision': info.sha, 'repo_license': (info.card_data.license
                                                                 if info.card_data else None),
        'repo_gated': info.gated, 'gate_terms_accepted_by_this_job': False,
        'p1_train_md5': TRAIN_MD5, 'p1_holdout_md5': HOLDOUT_MD5,
        'p1_bulk_row_count': len(p1_rows), 'p1_ticker_count': len(p1_symbols),
        'source_silver_files_selected': len(symbol_paths),
        'p1_tickers_with_silver_file': len(symbol_paths),
        'index_files_selected': {symbol: path for symbol, path in index_paths.items()},
        'observed_sessions_by_exchange': {ex: len(days) for ex, days in ordered_sessions.items()},
        'observed_date_range_by_exchange': {
            ex: [date_min[ex].isoformat(), date_max[ex].isoformat()]
            for ex in date_min
        },
        'source_price_rows_with_valid_raw_close': row_count,
        'source_price_rows_missing_exchange_field': source_exchange_missing,
        'rows_with_valid_close_adj_field': adjusted_count,
        'schemas': {hashlib.sha256(schema.encode()).hexdigest()[:16]: schema
                    for schema in sorted(schemas)},
        'coverage_at_exact_120_observed_sessions': coverage,
        'adjusted_price_semantics_verified_as_total_return': False,
        'exchange_for_missing_source_rows_uses_p1_snapshot': True,
        'point_in_time_universe_verified': False,
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')
    print(json.dumps({'status': result['status'], 'p1_ticker_count': len(p1_symbols),
                      'source_silver_files_selected': len(symbol_paths),
                      'source_price_rows': row_count,
                      'index_files_selected': len(index_paths),
                      'report': str(output)}, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--p1-work', default='/tmp/p2a-hf-p1')
    args = parser.parse_args()
    audit(args.output, args.p1_work)


if __name__ == '__main__':
    main()
