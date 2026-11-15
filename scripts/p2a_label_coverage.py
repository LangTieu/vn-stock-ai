#!/usr/bin/env python3
"""Measure how many P1 rows have exact v2 session endpoints in a source snapshot."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

try:
    from .p2a_relabel import HORIZON_SESSIONS, row_identity, sha256
except ImportError:
    from p2a_relabel import HORIZON_SESSIONS, row_identity, sha256


def load_sources(price_path, sessions_path):
    raw_prices = {}
    adjusted_prices = {}
    adjusted = 0
    with gzip.open(price_path, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            ticker, exchange = row['ticker'].upper(), row['exchange'].upper()
            day = date.fromisoformat(row['date'])
            raw = row.get('adjusted_total_return_close', '').strip()
            if raw:
                value = float(raw)
                adjusted_prices[(ticker, exchange, day)] = value
                adjusted += 1
            raw = row.get('close', '').strip()
            if raw:
                value = float(raw)
                if value > 0:
                    raw_prices[(ticker, exchange, day)] = value
    sessions = {}
    with gzip.open(sessions_path, 'rt', encoding='utf-8', newline='') as stream:
        grouped = {}
        for row in csv.DictReader(stream):
            grouped.setdefault(row['exchange'].upper(), set()).add(date.fromisoformat(row['date']))
    for exchange, days in grouped.items():
        calendar = sorted(days)
        sessions[exchange] = (calendar, {day: index for index, day in enumerate(calendar)})
    return raw_prices, adjusted_prices, sessions, adjusted


def coverage_report(p1_paths, prices_path, sessions_path):
    raw_prices, adjusted_prices, sessions, adjusted_rows = load_sources(prices_path, sessions_path)
    reports = []
    for p1_path in p1_paths:
        stats = Counter()
        raw_returns = Counter()
        by_year = Counter()
        by_exchange = Counter()
        with Path(p1_path).open(encoding='utf-8') as stream:
            for line_no, line in enumerate(stream, 1):
                row = json.loads(line)
                metadata = row.get('metadata') or {}
                if metadata.get('kind') != 'bulk':
                    continue
                label = (metadata.get('label') or {}).get('future_direction_120')
                if label not in ('UP', 'DOWN', 'FLAT'):
                    stats['unsupported_label'] += 1
                    continue
                ticker, exchange, as_of = row_identity(row)
                year = str(as_of.year)
                by_year[(year, 'p1_rows')] += 1
                by_exchange[(exchange, 'p1_rows')] += 1
                if exchange not in sessions or as_of not in sessions[exchange][1]:
                    stats['as_of_missing_session'] += 1
                    by_year[(year, 'as_of_missing_session')] += 1
                    continue
                calendar, index = sessions[exchange]
                end_index = index[as_of] + HORIZON_SESSIONS
                if end_index >= len(calendar):
                    stats['horizon_not_yet_matured'] += 1
                    by_year[(year, 'horizon_not_yet_matured')] += 1
                    continue
                end_date = calendar[end_index]
                start_key = (ticker, exchange, as_of)
                end_key = (ticker, exchange, end_date)
                start_close = raw_prices.get(start_key)
                end_close = raw_prices.get(end_key)
                if start_close is None:
                    stats['missing_start_price'] += 1
                    by_year[(year, 'missing_start_price')] += 1
                    continue
                if end_close is None:
                    stats['missing_endpoint_price'] += 1
                    by_year[(year, 'missing_endpoint_price')] += 1
                    continue
                stats['raw_price_endpoints_available'] += 1
                by_year[(year, 'raw_price_endpoints_available')] += 1
                by_exchange[(exchange, 'raw_price_endpoints_available')] += 1
                raw_return_pct = (end_close / start_close - 1) * 100
                raw_returns['UP' if raw_return_pct > 0 else
                            'DOWN' if raw_return_pct < 0 else 'ZERO'] += 1
                for threshold in (0.5, 1.0, 2.0, 5.0):
                    if abs(raw_return_pct) <= threshold:
                        raw_returns[f'abs_return_le_{threshold:g}_pct'] += 1
                if start_key in adjusted_prices and end_key in adjusted_prices:
                    stats['adjusted_price_endpoints_available'] += 1
                    by_year[(year, 'adjusted_price_endpoints_available')] += 1
                else:
                    stats['endpoint_is_raw_unadjusted_only'] += 1
        reports.append({
            'p1_file': Path(p1_path).name,
            'p1_sha256': sha256(p1_path),
            'rows': dict(sorted(stats.items())),
            'raw_price_only_return_diagnostic_not_a_final_label': dict(sorted(raw_returns.items())),
            'by_year': {f'{year}:{metric}': count for (year, metric), count in sorted(by_year.items())},
            'by_exchange': {f'{exchange}:{metric}': count
                            for (exchange, metric), count in sorted(by_exchange.items())},
        })
    return {
        'method': '120th later exchange session after as_of; raw-price-only diagnostics; no final labels generated',
        'horizon_sessions': HORIZON_SESSIONS,
        'prices_sha256': sha256(prices_path), 'sessions_sha256': sha256(sessions_path),
        'adjusted_close_rows': adjusted_rows,
        'p1_reports': reports,
        'passes': all(report['rows'].get('adjusted_price_endpoints_available', 0) > 0
                      for report in reports),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--p1', action='append', required=True)
    parser.add_argument('--prices', required=True)
    parser.add_argument('--sessions', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = coverage_report(args.p1, args.prices, args.sessions)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passes': report['passes'], 'adjusted_close_rows': report['adjusted_close_rows'],
                      'output': str(output)}, sort_keys=True))


if __name__ == '__main__':
    main()
