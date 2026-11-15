#!/usr/bin/env python3
"""Audit observed Drive OHLCV JSON against P1 without synthesizing sessions."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

try:
    from .p2a_relabel import HORIZON_SESSIONS, row_identity
except ImportError:
    from p2a_relabel import HORIZON_SESSIONS, row_identity

EXCHANGES = ('HOSE', 'HNX', 'UPCOM', 'OTC')
OHLCV_FIELDS = ('open', 'high', 'low', 'close', 'volume')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def load_drive_prices(paths):
    prices = {}
    sessions = defaultdict(set)
    reports = {}
    for exchange, path in paths.items():
        source = Path(path)
        with source.open(encoding='utf-8') as stream:
            document = json.load(stream)
        tickers = document.get('tickers') if isinstance(document, dict) else None
        if not isinstance(tickers, dict):
            raise ValueError(f'{source.name}: expected top-level tickers object')
        counts = Counter()
        by_year = Counter()
        fields = set()
        seen = set()
        dates = []
        ticker_count = 0
        for ticker, data in tickers.items():
            if not isinstance(data, dict):
                counts['invalid_ticker_object'] += 1
                continue
            bars = data.get('ohlcv')
            if not isinstance(bars, list):
                counts['missing_ohlcv_array'] += 1
                continue
            if bars:
                ticker_count += 1
            for bar in bars:
                if not isinstance(bar, dict):
                    counts['invalid_bar_object'] += 1
                    continue
                fields.update(str(key) for key in bar)
                counts['ohlcv_rows'] += 1
                try:
                    day = date.fromisoformat(str(bar['date'])[:10])
                except (KeyError, TypeError, ValueError):
                    counts['invalid_date'] += 1
                    continue
                values = {key: _number(bar.get(key)) for key in OHLCV_FIELDS}
                invalid = [key for key, value in values.items() if value is None]
                if invalid:
                    counts['invalid_numeric_rows'] += 1
                    counts['invalid_numeric_cells'] += len(invalid)
                    continue
                if any(values[key] <= 0 for key in ('open', 'high', 'low', 'close')):
                    counts['nonpositive_ohlc_rows'] += 1
                    continue
                if values['volume'] < 0:
                    counts['negative_volume_rows'] += 1
                    continue
                if not (values['low'] <= min(values['open'], values['close'])
                        <= max(values['open'], values['close']) <= values['high']):
                    counts['ohlc_order_mismatch_rows'] += 1
                key = (str(ticker).strip().upper(), exchange, day)
                if key in seen:
                    counts['duplicate_ticker_dates'] += 1
                    continue
                seen.add(key)
                prices[key] = values
                sessions[exchange].add(day)
                dates.append(day)
                by_year[day.year] += 1
        reports[exchange] = {
            'file': source.name, 'sha256': sha256(source), 'bytes': source.stat().st_size,
            'tickers_in_file': len(tickers), 'tickers_with_ohlcv': ticker_count,
            'rows_by_year': {str(year): count for year, count in sorted(by_year.items())},
            'observed_session_count': len(sessions[exchange]),
            'observed_date_range': ([min(dates).isoformat(), max(dates).isoformat()]
                                    if dates else None),
            'ohlcv_fields': sorted(fields), 'counts': dict(sorted(counts.items())),
        }
    return prices, sessions, reports


def load_p1_rows(paths):
    rows = []
    for path in paths:
        with Path(path).open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                if (row.get('metadata') or {}).get('kind') != 'bulk':
                    continue
                ticker, exchange, as_of = row_identity(row)
                rows.append((Path(path).name, ticker, exchange, as_of))
    return rows


def compare_to_index(calendar_path, sessions):
    if not calendar_path:
        return None
    observed_index = defaultdict(set)
    with gzip.open(calendar_path, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            exchange = row['exchange'].strip().upper()
            day = date.fromisoformat(row['date'])
            if exchange in EXCHANGES:
                observed_index[exchange].add(day)
    result = {}
    for exchange, index_days in observed_index.items():
        drive_days = {day for day in sessions.get(exchange, set()) if day.year >= 2017}
        result[exchange] = {
            'finhay_index_sessions': len(index_days),
            'drive_dates_2017_onward': len(drive_days),
            'drive_missing_vs_finhay_index': len(index_days - drive_days),
            'drive_extra_vs_finhay_index': len(drive_days - index_days),
        }
    return result


def coverage(p1_rows, prices, sessions):
    reports = []
    for p1_path in sorted({row[0] for row in p1_rows}):
        counts = Counter()
        by_year = Counter()
        by_exchange = Counter()
        tickers = set()
        for split, ticker, exchange, as_of in p1_rows:
            if split != p1_path:
                continue
            tickers.add(ticker)
            year = as_of.year
            counts['rows'] += 1
            by_year[(year, 'rows')] += 1
            by_exchange[(exchange, 'rows')] += 1
            calendar = sorted(sessions.get(exchange, set()))
            position = {day: index for index, day in enumerate(calendar)}
            if as_of not in position:
                counts['as_of_missing_observed_session'] += 1
                by_year[(year, 'as_of_missing_observed_session')] += 1
                continue
            end_index = position[as_of] + HORIZON_SESSIONS
            if end_index >= len(calendar):
                counts['horizon_not_yet_matured'] += 1
                by_year[(year, 'horizon_not_yet_matured')] += 1
                continue
            endpoint = calendar[end_index]
            start = prices.get((ticker, exchange, as_of))
            end = prices.get((ticker, exchange, endpoint))
            if start is None:
                counts['missing_start_raw_close'] += 1
                by_year[(year, 'missing_start_raw_close')] += 1
                continue
            if end is None:
                counts['missing_endpoint_raw_close'] += 1
                by_year[(year, 'missing_endpoint_raw_close')] += 1
                continue
            counts['raw_exact_120_session_endpoints'] += 1
            by_year[(year, 'raw_exact_120_session_endpoints')] += 1
            by_exchange[(exchange, 'raw_exact_120_session_endpoints')] += 1
        reports.append({
            'p1_file': p1_path, 'p1_tickers': len(tickers),
            'counts': dict(sorted(counts.items())),
            'by_year': {f'{year}:{metric}': count
                        for (year, metric), count in sorted(by_year.items())},
            'by_exchange': {f'{exchange}:{metric}': count
                            for (exchange, metric), count in sorted(by_exchange.items())},
        })
    return reports


def audit(paths, p1_paths, calendar_path=None):
    prices, sessions, source_reports = load_drive_prices(paths)
    p1_rows = load_p1_rows(p1_paths)
    result = {
        'method': 'Observed Drive OHLCV rows only; no dates or prices inferred; no adjusted prices in source JSON schema',
        'source_file_reports': source_reports,
        'p1_tickers_in_source_by_exchange': {
            exchange: len({ticker for _, ticker, item_exchange, _ in p1_rows
                           if item_exchange == exchange and
                           any(key[0] == ticker and key[1] == exchange for key in prices)})
            for exchange in EXCHANGES
        },
        'p1_coverage': coverage(p1_rows, prices, sessions),
        'session_comparison_to_finhay_index_2017_onward': compare_to_index(calendar_path, sessions),
        'adjusted_total_return_price_rows': 0,
        'passes_label_v2_data_gate': False,
        'raw_close_is_not_total_return': True,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hose', required=True)
    parser.add_argument('--hnx', required=True)
    parser.add_argument('--upcom', required=True)
    parser.add_argument('--otc', required=True)
    parser.add_argument('--p1-train', required=True)
    parser.add_argument('--p1-holdout', required=True)
    parser.add_argument('--finhay-index-sessions')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = audit({'HOSE': args.hose, 'HNX': args.hnx,
                    'UPCOM': args.upcom, 'OTC': args.otc},
                   [args.p1_train, args.p1_holdout], args.finhay_index_sessions)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8')
    print(json.dumps({
        'p1_train_rows': result['p1_coverage'][0]['counts'].get('rows', 0),
        'p1_holdout_rows': result['p1_coverage'][1]['counts'].get('rows', 0),
        'p1_train_exact_raw_endpoints': result['p1_coverage'][0]['counts'].get(
            'raw_exact_120_session_endpoints', 0),
        'p1_holdout_exact_raw_endpoints': result['p1_coverage'][1]['counts'].get(
            'raw_exact_120_session_endpoints', 0),
        'passes_label_v2_data_gate': result['passes_label_v2_data_gate'],
        'report': str(args.output),
    }, sort_keys=True))


if __name__ == '__main__':
    main()
