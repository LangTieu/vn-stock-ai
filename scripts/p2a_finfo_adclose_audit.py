#!/usr/bin/env python3
"""Audit VNDirect Finfo adjusted-close coverage for exact P1 endpoints."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

try:
    from .p2a_relabel import HORIZON_SESSIONS, row_identity
except ImportError:
    from p2a_relabel import HORIZON_SESSIONS, row_identity

BASE_URL = 'https://api-finfo.vndirect.com.vn/v4/stock_prices'
USER_AGENT = 'vn-stock-ai-p2a-adjusted-price-audit/1.0'
_request_lock = threading.Lock()
_last_request = 0.0


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def positive_finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def load_sessions(path):
    grouped = defaultdict(set)
    with Path(path).open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('exchange') and row.get('date'):
                grouped[row['exchange'].strip().upper()].add(date.fromisoformat(row['date']))
    sessions = {}
    for exchange, days in grouped.items():
        calendar = sorted(days)
        sessions[exchange] = (calendar, {day: index for index, day in enumerate(calendar)})
    return sessions


def load_requirements(p1_paths, sessions):
    requirements = []
    by_split = {}
    symbols = set()
    for path in p1_paths:
        path = Path(path)
        opener = gzip.open if path.suffix == '.gz' else open
        counts = Counter()
        with opener(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                if (row.get('metadata') or {}).get('kind') != 'bulk':
                    continue
                counts['p1_bulk_rows'] += 1
                ticker, exchange, as_of = row_identity(row)
                symbols.add(ticker)
                if exchange not in sessions or as_of not in sessions[exchange][1]:
                    counts['as_of_missing_session'] += 1
                    continue
                calendar, positions = sessions[exchange]
                end_index = positions[as_of] + HORIZON_SESSIONS
                if end_index >= len(calendar):
                    counts['horizon_not_matured'] += 1
                    continue
                endpoint = calendar[end_index]
                requirements.append((path.name, ticker, exchange, as_of, endpoint))
                counts['exact_session_endpoints_required'] += 1
        by_split[path.name] = counts
    return requirements, symbols, by_split


def fetch_symbol(symbol, request_interval=0.5, opener=None, base_url=BASE_URL):
    """Fetch one ticker's complete supported history, retaining observed fields only."""
    global _last_request
    opener = opener or urllib.request.urlopen
    output = []
    page = 1
    while True:
        query = urllib.parse.urlencode({
            'sort': 'date', 'size': 5000, 'page': page,
            'q': f'code:{symbol}~date:gte:2014-01-01~date:lte:2026-11-30',
        })
        request = urllib.request.Request(
            f'{base_url}?{query}',
            headers={'Accept': 'application/json', 'User-Agent': USER_AGENT},
        )
        for attempt in range(4):
            with _request_lock:
                delay = request_interval - (time.monotonic() - _last_request)
                if delay > 0:
                    time.sleep(delay)
                _last_request = time.monotonic()
            try:
                with opener(request, timeout=40) as response:
                    payload = json.loads(response.read().decode('utf-8'))
                break
            except urllib.error.HTTPError as error:
                if error.code != 429 and not 500 <= error.code < 600:
                    raise RuntimeError(f'Finfo HTTP {error.code} for ticker {symbol}') from None
                if attempt == 3:
                    raise RuntimeError(f'Finfo HTTP {error.code} after retries for ticker {symbol}') from None
                time.sleep(2 ** attempt)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == 3:
                    raise RuntimeError(f'Finfo {type(error).__name__} after retries for ticker {symbol}') from None
                time.sleep(2 ** attempt)
        rows = payload.get('data') or []
        output.extend(rows)
        total_pages = payload.get('totalPages') or 1
        if page >= int(total_pages):
            break
        page += 1
    return output


def audit(p1_paths, sessions_path, output_dir, fetcher=fetch_symbol, workers=2):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sessions = load_sessions(sessions_path)
    requirements, symbols, by_split = load_requirements(p1_paths, sessions)
    needed = defaultdict(set)
    for _, ticker, exchange, start, end in requirements:
        needed[ticker].update(((exchange, start), (exchange, end)))

    prices = {}
    fetch_errors = Counter()
    api_rows = Counter()
    exchange_mismatches = Counter()
    invalid_adjusted = Counter()

    def collect(symbol):
        try:
            return symbol, fetcher(symbol), None
        except Exception as error:  # Audit all symbols and preserve a failure report.
            return symbol, [], f'{type(error).__name__}: {error}'

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(collect, symbol) for symbol in sorted(symbols)]
        for future in as_completed(futures):
            symbol, rows, error = future.result()
            if error:
                fetch_errors[error.split(':', 1)[0]] += 1
                continue
            for row in rows:
                day_value = row.get('date')
                try:
                    day = date.fromisoformat(str(day_value)[:10])
                except (TypeError, ValueError):
                    continue
                api_exchange = str(row.get('floor') or row.get('exchange') or '').strip().upper()
                aliases = {'HSX': 'HOSE'}
                api_exchange = aliases.get(api_exchange, api_exchange)
                for exchange, required_day in needed[symbol]:
                    if required_day != day:
                        continue
                    if api_exchange and api_exchange != exchange:
                        exchange_mismatches[(exchange, api_exchange)] += 1
                        continue
                    key = (symbol, exchange, day)
                    if key in prices:
                        continue
                    api_rows[exchange] += 1
                    adjusted = positive_finite(row.get('adClose'))
                    if adjusted is None:
                        invalid_adjusted[exchange] += 1
                    prices[key] = {
                        'close': positive_finite(row.get('close')),
                        'adClose': adjusted,
                    }

    split_reports = {}
    adjusted_returns = Counter()
    endpoints_writer_path = output_dir / 'finfo-adclose-endpoints.csv.gz'
    with gzip.open(endpoints_writer_path, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            'ticker', 'exchange', 'date', 'close', 'adClose',
        ])
        writer.writeheader()
        written = set()
        for (ticker, exchange, day), price in sorted(prices.items()):
            writer.writerow({
                'ticker': ticker, 'exchange': exchange, 'date': day.isoformat(),
                'close': price['close'] if price['close'] is not None else '',
                'adClose': price['adClose'] if price['adClose'] is not None else '',
            })
            written.add((ticker, exchange, day))

    for path in p1_paths:
        split = Path(path).name
        counts = by_split[split]
        returns = Counter()
        for _, ticker, exchange, start, end in (r for r in requirements if r[0] == split):
            start_price = prices.get((ticker, exchange, start), {}).get('adClose')
            end_price = prices.get((ticker, exchange, end), {}).get('adClose')
            if start_price is None:
                counts['missing_start_adClose'] += 1
                continue
            if end_price is None:
                counts['missing_endpoint_adClose'] += 1
                continue
            counts['adjusted_price_endpoints_available'] += 1
            value = (end_price / start_price - 1) * 100
            returns['UP' if value > 2 else 'DOWN' if value < -2 else 'FLAT'] += 1
            adjusted_returns['UP' if value > 2 else 'DOWN' if value < -2 else 'FLAT'] += 1
        split_reports[split] = {
            'p1_sha256': sha256(path),
            'counts': dict(sorted(counts.items())),
            'adClose_return_bands_diagnostic_only': dict(sorted(returns.items())),
        }

    report = {
        'method': 'Finfo adClose exact as_of and 120th observed future exchange session endpoints; diagnostics only, labels not generated',
        'api': BASE_URL,
        'horizon_sessions': HORIZON_SESSIONS,
        'symbols_requested': len(symbols),
        'required_endpoint_rows': len(requirements),
        'p1_sha256': {Path(path).name: sha256(path) for path in p1_paths},
        'sessions_sha256': sha256(sessions_path),
        'api_endpoint_rows_by_exchange': dict(sorted(api_rows.items())),
        'invalid_or_missing_adClose_by_exchange': dict(sorted(invalid_adjusted.items())),
        'exchange_mismatches': {f'{expected}:{observed}': count
                                for (expected, observed), count in sorted(exchange_mismatches.items())},
        'fetch_errors_by_type': dict(sorted(fetch_errors.items())),
        'adClose_return_bands_diagnostic_only': dict(sorted(adjusted_returns.items())),
        'p1_reports': split_reports,
        'labels_generated': False,
        'passes': False,
        'gate_note': 'This coverage audit does not certify vendor license, current exchange adjustment implementation, or point-in-time universe/sector history.',
        'endpoint_prices_sha256': sha256(endpoints_writer_path),
    }
    (output_dir / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--p1', action='append', required=True)
    parser.add_argument('--sessions', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 4:
        parser.error('--workers must be between 1 and 4')
    report = audit(args.p1, args.sessions, args.output_dir, workers=args.workers)
    print(json.dumps({
        'symbols_requested': report['symbols_requested'],
        'required_endpoint_rows': report['required_endpoint_rows'],
        'fetch_errors_by_type': report['fetch_errors_by_type'],
        'labels_generated': False,
        'passes': False,
    }, sort_keys=True))
    if report['fetch_errors_by_type']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
