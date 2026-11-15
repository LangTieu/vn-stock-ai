#!/usr/bin/env python3
"""Normalize the liaison-provided Drive JSON files without inferring prices or dates."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

EXCHANGES = ('HOSE', 'HNX', 'UPCOM', 'OTC')
PRICE_FIELDS = ('open', 'high', 'low', 'close')
PRICE_COLUMNS = ('security_id', 'ticker', 'exchange', 'date', 'open', 'high', 'low',
                 'close', 'volume', 'adjusted_total_return_close', 'data_quality_flag')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _value(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def normalize(files, output_dir):
    output_dir = Path(output_dir).resolve()
    repo_root = Path(__file__).resolve().parents[1]
    if output_dir == repo_root or repo_root in output_dir.parents:
        raise ValueError('Raw market-data outputs must be outside the repository checkout')
    output_dir.mkdir(parents=True, exist_ok=True)
    price_path = output_dir / 'daily_prices.csv.gz'
    sessions_path = output_dir / 'exchange_sessions.csv.gz'
    manifest_path = output_dir / 'manifest.json'
    counts_by_exchange = Counter()
    quality_by_exchange = Counter()
    session_days = {exchange: set() for exchange in EXCHANGES}
    ticker_counts = {}
    date_bounds = {}
    sources = {}
    keys = set()
    temp_price = price_path.with_name(price_path.name + f'.tmp-{os.getpid()}')
    try:
        with gzip.open(temp_price, 'wt', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=PRICE_COLUMNS)
            writer.writeheader()
            for exchange, source in files.items():
                source = Path(source)
                raw = json.loads(source.read_text(encoding='utf-8'))
                tickers = raw.get('tickers') if isinstance(raw, dict) else None
                if not isinstance(tickers, dict):
                    raise ValueError(f'{source.name}: expected top-level tickers object')
                ticker_counts[exchange] = {
                    'tickers_in_source': len(tickers),
                    'tickers_with_ohlcv': sum(bool(item.get('ohlcv'))
                                               for item in tickers.values()
                                               if isinstance(item, dict)),
                }
                sources[exchange] = {
                    'file': source.name, 'sha256': sha256(source),
                    'bytes': source.stat().st_size,
                    'source_description': raw.get('source'),
                    'declared_range': [raw.get('from'), raw.get('to')],
                }
                for ticker, item in tickers.items():
                    if not isinstance(item, dict) or not isinstance(item.get('ohlcv'), list):
                        counts_by_exchange[(exchange, 'missing_ohlcv_array')] += 1
                        continue
                    for bar in item['ohlcv']:
                        counts_by_exchange[(exchange, 'source_rows')] += 1
                        try:
                            day = date.fromisoformat(str(bar.get('date', ''))[:10])
                        except (TypeError, ValueError):
                            counts_by_exchange[(exchange, 'invalid_date_rows')] += 1
                            continue
                        parsed = {field: _value(bar.get(field)) for field in PRICE_FIELDS}
                        volume = _value(bar.get('volume'))
                        if all(parsed[field] == 0 for field in PRICE_FIELDS):
                            counts_by_exchange[(exchange, 'removed_all_zero_ohlc')] += 1
                            continue
                        close = parsed['close']
                        flags = []
                        if close is None or close <= 0:
                            counts_by_exchange[(exchange, 'invalid_close_rows')] += 1
                            flags.append('invalid_close')
                            close = None
                        for field in ('open', 'high', 'low'):
                            if parsed[field] is None or parsed[field] <= 0:
                                parsed[field] = None
                                counts_by_exchange[(exchange, f'invalid_{field}_cells')] += 1
                                flags.append(f'invalid_{field}')
                        if volume is None or volume < 0:
                            counts_by_exchange[(exchange, 'invalid_volume_cells')] += 1
                            flags.append('invalid_volume')
                            volume = None
                        if close is not None and all(parsed[f] is not None for f in ('open', 'high', 'low')):
                            if not (parsed['low'] <= min(parsed['open'], close)
                                    <= max(parsed['open'], close) <= parsed['high']):
                                counts_by_exchange[(exchange, 'ohlc_order_mismatch_rows')] += 1
                                flags.append('ohlc_order_mismatch')
                        if day.weekday() >= 5:
                            counts_by_exchange[(exchange, 'weekend_source_rows')] += 1
                            flags.append('weekend_date')
                            close = None
                        key = (str(ticker).strip().upper(), exchange, day)
                        if key in keys:
                            raise ValueError(f'duplicate ticker/date row in {source.name}')
                        keys.add(key)
                        quality = ';'.join(flags) if flags else 'ok'
                        quality_by_exchange[(exchange, quality)] += 1
                        writer.writerow({
                            'security_id': key[0], 'ticker': key[0], 'exchange': exchange,
                            'date': day.isoformat(), 'open': parsed['open'] or '',
                            'high': parsed['high'] or '', 'low': parsed['low'] or '',
                            'close': close if close is not None else '',
                            'volume': volume if volume is not None else '',
                            'adjusted_total_return_close': '', 'data_quality_flag': quality,
                        })
                        counts_by_exchange[(exchange, 'normalized_rows')] += 1
                        if close is not None:
                            session_days[exchange].add(day)
                            current = date_bounds.get(exchange)
                            if current is None:
                                date_bounds[exchange] = [day, day]
                            else:
                                date_bounds[exchange] = [min(current[0], day), max(current[1], day)]
        os.replace(temp_price, price_path)
    finally:
        temp_price.unlink(missing_ok=True)

    with gzip.open(sessions_path, 'wt', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['exchange', 'date', 'source_index', 'source_reference'])
        writer.writeheader()
        for exchange in EXCHANGES:
            for day in sorted(session_days[exchange]):
                writer.writerow({'exchange': exchange, 'date': day.isoformat(),
                                 'source_index': 'Drive observed stock OHLCV bar',
                                 'source_reference': sources[exchange]['file']})
    report = {
        'method': 'Normalize supplied OHLCV rows; observed positive-close dates only; no date/price inference',
        'source_file_reports': sources,
        'tickers_by_exchange': ticker_counts,
        'row_counts_by_exchange': {f'{ex}:{name}': count
                                   for (ex, name), count in sorted(counts_by_exchange.items())},
        'quality_flag_counts': {f'{ex}:{flag}': count
                                for (ex, flag), count in sorted(quality_by_exchange.items())},
        'observed_sessions_by_exchange': {ex: len(days) for ex, days in session_days.items()},
        'observed_date_range_by_exchange': {
            ex: [bounds[0].isoformat(), bounds[1].isoformat()]
            for ex, bounds in sorted(date_bounds.items())
        },
        'adjusted_total_return_rows': 0,
        'adjustment_status': 'raw OHLCV only; adjusted_total_return_close intentionally blank',
        'daily_prices_sha256': sha256(price_path),
        'exchange_sessions_sha256': sha256(sessions_path),
    }
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
    print(json.dumps({'output_dir': str(output_dir),
                      'observed_sessions_by_exchange': report['observed_sessions_by_exchange'],
                      'adjusted_total_return_rows': 0,
                      'daily_prices_sha256': report['daily_prices_sha256'],
                      'exchange_sessions_sha256': report['exchange_sessions_sha256']},
                     ensure_ascii=False, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for exchange in EXCHANGES:
        parser.add_argument(f'--{exchange.lower()}', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    normalize({exchange: getattr(args, exchange.lower()) for exchange in EXCHANGES},
              args.output_dir)


if __name__ == '__main__':
    main()
