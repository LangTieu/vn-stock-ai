#!/usr/bin/env python3
"""Rebuild P2 direction labels from exchange-session and adjusted-price tables.

The canonical input tables are intentionally external inputs: this checkout does
not contain historical exchange calendars, point-in-time security universes, or
verified corporate-action-adjusted prices.
"""
import argparse
import bisect
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path

HORIZON_SESSIONS = 120
DEFAULT_FLAT_BAND_PCT = 2.0
EXCHANGE_RE = re.compile(r"(?:^|[_-])(HOSE|HNX|UPCOM|OTC)(?:[_-]|\.)", re.I)
BRIEF_RE = re.compile(r"^BRIEF:.*?mã\s+([A-Z0-9._-]+)\s+tại\s+(\d{4}-\d{2}-\d{2})", re.I)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _date(value, field):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f'invalid {field}: {value!r}') from error


def load_sessions(path):
    by_exchange = {}
    with Path(path).open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if not {'exchange', 'date'} <= set(reader.fieldnames or ()):
            raise ValueError('session calendar CSV requires exchange,date columns')
        for row in reader:
            exchange = row['exchange'].strip().upper()
            session = _date(row['date'], 'session date')
            days = by_exchange.setdefault(exchange, set())
            if session in days:
                raise ValueError(f'duplicate exchange session: {exchange} {session}')
            days.add(session)
    if not by_exchange:
        raise ValueError('session calendar is empty')
    ordered = {exchange: sorted(days) for exchange, days in by_exchange.items()}
    return {exchange: (days, {day: i for i, day in enumerate(days)})
            for exchange, days in ordered.items()}


def load_adjusted_prices(path):
    prices = {}
    with Path(path).open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        required = {'ticker', 'exchange', 'date', 'adjusted_total_return_close'}
        if not required <= set(reader.fieldnames or ()):
            raise ValueError('price CSV requires ticker,exchange,date,adjusted_total_return_close')
        for row in reader:
            ticker = row['ticker'].strip().upper()
            exchange = row['exchange'].strip().upper()
            day = _date(row['date'], 'price date')
            raw = row['adjusted_total_return_close'].strip()
            key = ticker, exchange, day
            if key in prices:
                raise ValueError(f'duplicate adjusted price row: {key}')
            if not raw:
                prices[key] = None
                continue
            value = float(raw)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'adjusted price must be positive: {key}')
            prices[key] = value
    if not prices:
        raise ValueError('adjusted-price table is empty')
    return prices


def row_identity(row):
    metadata = row.get('metadata') or {}
    data = row.get('input', '')
    match = BRIEF_RE.search(data.splitlines()[0] if data else '')
    verified = {}
    marker = 'VERIFIED_DATA\n'
    if marker in data:
        try:
            verified, _ = json.JSONDecoder().raw_decode(data.split(marker, 1)[1])
        except (TypeError, ValueError):
            pass
    ticker = str(verified.get('ticker') or (match.group(1) if match else '')).strip().upper()
    as_of_value = verified.get('as_of') or (match.group(2) if match else None)
    exchange = str(metadata.get('exchange') or '').strip().upper()
    source = ((verified.get('source') or {}).get('ohlcv') or '')
    if not exchange:
        source_match = EXCHANGE_RE.search(source)
        if source_match:
            exchange = source_match.group(1).upper()
    if not ticker or not as_of_value or not exchange:
        raise ValueError('row must identify ticker, exchange (metadata or source path), and as_of')
    return ticker, exchange, _date(as_of_value, 'as_of')


def relabel_row(row, sessions, prices, flat_band_pct=DEFAULT_FLAT_BAND_PCT):
    ticker, exchange, as_of = row_identity(row)
    if exchange not in sessions:
        raise ValueError(f'no exchange calendar for {exchange}')
    calendar, positions = sessions[exchange]
    if as_of not in positions:
        raise ValueError(f'{ticker} {exchange} as_of {as_of} is not a trading session')
    start = bisect.bisect_right(calendar, as_of)
    if start + HORIZON_SESSIONS > len(calendar):
        endpoint = None
        reason = 'calendar_ends_before_horizon'
    else:
        endpoint = calendar[start + HORIZON_SESSIONS - 1]
        end_close = prices.get((ticker, exchange, endpoint))
        start_close = prices.get((ticker, exchange, as_of))
        if start_close is None:
            reason = 'missing_start_adjusted_close'
        elif end_close is None:
            reason = 'missing_endpoint_adjusted_close'
        else:
            reason = None

    metadata = row.setdefault('metadata', {})
    label = metadata.setdefault('label', {})
    result = {'method': 'adjusted_total_return_close; 120 exchange sessions after as_of',
              'horizon_sessions': HORIZON_SESSIONS, 'exchange': exchange,
              'as_of': as_of.isoformat(), 'endpoint_date': endpoint.isoformat() if endpoint else None,
              'flat_band_pct': flat_band_pct}
    if reason:
        label['future_direction_120'] = None
        result.update({'status': 'censored', 'reason': reason, 'return_pct': None})
    else:
        return_pct = (end_close / start_close - 1) * 100
        if return_pct > flat_band_pct:
            direction = 'UP'
        elif return_pct < -flat_band_pct:
            direction = 'DOWN'
        else:
            direction = 'FLAT'
        label['future_direction_120'] = direction
        result.update({'status': 'labeled', 'return_pct': round(return_pct, 8)})
    label['future_outcomes'] = {'120': result}
    label['method'] = result['method']
    metadata['p2a_label_version'] = 2
    metadata['p2a_label_status'] = result['status']
    return row, result


def relabel_file(source, output, manifest_path, calendar_path, prices_path,
                 flat_band_pct=DEFAULT_FLAT_BAND_PCT):
    if not math.isfinite(flat_band_pct) or flat_band_pct < 0:
        raise ValueError('flat band must be finite and non-negative')
    protected = {Path(source).resolve(), Path(calendar_path).resolve(), Path(prices_path).resolve()}
    output_path = Path(output)
    manifest_path = Path(manifest_path)
    if output_path.resolve() in protected or manifest_path.resolve() in protected:
        raise ValueError('output and manifest must not overwrite any source input')
    if output_path.resolve() == manifest_path.resolve():
        raise ValueError('output and manifest must use separate paths')
    sessions = load_sessions(calendar_path)
    prices = load_adjusted_prices(prices_path)
    for ticker, exchange, day in prices:
        if exchange not in sessions or day not in sessions[exchange][1]:
            raise ValueError(f'adjusted price is not on its exchange calendar: {ticker} {exchange} {day}')
    stats = Counter()
    source_path = Path(source)
    if source_path.resolve() == output_path.resolve():
        raise ValueError('output must be a new path; source is never overwritten')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_name(output_path.name + f'.tmp-{os.getpid()}')
    try:
        with source_path.open(encoding='utf-8') as input_stream, \
                temp_output.open('w', encoding='utf-8') as output_stream:
            for line_no, line in enumerate(input_stream, 1):
                try:
                    row = json.loads(line)
                    if (row.get('metadata') or {}).get('kind') != 'bulk':
                        output_stream.write(line if line.endswith('\n') else line + '\n')
                        stats['preserved_non_bulk'] += 1
                        continue
                    row, label = relabel_row(row, sessions, prices, flat_band_pct)
                except Exception as error:
                    raise ValueError(f'{source}:{line_no}: {error}') from error
                stats[label['status']] += 1
                if label['status'] == 'labeled':
                    stats['class_' + row['metadata']['label']['future_direction_120']] += 1
                else:
                    stats['censored_' + label['reason']] += 1
                output_stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
        os.replace(temp_output, output_path)
    finally:
        temp_output.unlink(missing_ok=True)
    manifest = {
        'label_version': 2,
        'method': 'adjusted_total_return_close; 120 exchange sessions after as_of',
        'horizon_sessions': HORIZON_SESSIONS,
        'flat_band_pct': flat_band_pct,
        'source': str(source), 'source_sha256': sha256(source),
        'calendar_sha256': sha256(calendar_path), 'adjusted_prices_sha256': sha256(prices_path),
        'output_sha256': sha256(output), 'counts': dict(sorted(stats.items())),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_manifest = manifest_path.with_name(manifest_path.name + f'.tmp-{os.getpid()}')
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
    os.replace(temp_manifest, manifest_path)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='source P1 JSONL; never overwritten')
    parser.add_argument('--output', required=True, help='new JSONL output path')
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--calendar-csv', required=True, help='exchange,date CSV')
    parser.add_argument('--prices-csv', required=True,
                        help='ticker,exchange,date,adjusted_total_return_close CSV')
    parser.add_argument('--flat-band-pct', type=float, default=DEFAULT_FLAT_BAND_PCT)
    args = parser.parse_args()
    result = relabel_file(args.input, args.output, args.manifest, args.calendar_csv,
                          args.prices_csv, args.flat_band_pct)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
