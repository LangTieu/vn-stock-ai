#!/usr/bin/env python3
"""Fetch P1 ticker OHLCV, corporate actions, exchange index sessions and listing snapshots.

The output deliberately leaves adjusted_total_return_close empty: Finhay's
documented market history endpoint does not specify corporate-action adjustment.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from p2a_relabel import row_identity

BASE_URL = 'https://open-api.fhsc.com.vn'
TRAIN_URL = 'https://huggingface.co/datasets/Jerlob/vn-stock-ai-p1/resolve/main/p1_train.jsonl.gz'
HOLDOUT_URL = 'https://huggingface.co/datasets/Jerlob/vn-stock-ai-p1/resolve/main/p1_holdout.jsonl'
TRAIN_MD5 = 'f6273e8a12e35fe1027f29ca2127b9c0'
HOLDOUT_MD5 = '5f48d9b13d2f2cce0a730067b2f3094c'
START_DATE = date(2014, 1, 1)
UTC_NOW = datetime.now(timezone.utc)
EXCHANGE_INDEX = {'HOSE': 'VNINDEX', 'HNX': 'HNXINDEX', 'UPCOM': 'UPCOMINDEX'}
P1_EXCHANGE = re.compile(r'(?:^|[_-])(HOSE|HNX|UPCOM|OTC)(?:[_-]|\.)', re.I)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, destination):
    request = urllib.request.Request(url, headers={'User-Agent': 'vn-stock-ai-p2a-data/1.0'})
    with urllib.request.urlopen(request, timeout=120) as response, Path(destination).open('wb') as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def md5_file(path):
    digest = hashlib.md5()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def seed_from_p1(train_path, holdout_path):
    symbols = {}
    row_count = 0
    for path in (train_path, holdout_path):
        opener = gzip.open if str(path).endswith('.gz') else open
        with opener(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                metadata = row.get('metadata') or {}
                if metadata.get('kind') != 'bulk':
                    continue
                ticker, exchange, as_of = row_identity(row)
                symbol = symbols.setdefault(ticker, {'exchanges': set(), 'as_of': []})
                symbol['exchanges'].add(exchange)
                symbol['as_of'].append(as_of.isoformat())
                row_count += 1
    return symbols, row_count


class FinhayClient:
    def __init__(self, api_key, min_interval=1.05):
        self.api_key = api_key
        self.min_interval = min_interval
        self.last_call = 0.0
        self.calls = 0
        self.failures = Counter()

    def get(self, path, params=None):
        url = BASE_URL + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        for attempt in range(7):
            delay = self.min_interval - (time.monotonic() - self.last_call)
            if delay > 0:
                time.sleep(delay)
            request = urllib.request.Request(url, headers={
                'X-FH-APIKEY': self.api_key,
                'Accept': 'application/json',
                'User-Agent': 'vn-stock-ai-p2a-data/1.0',
            })
            self.last_call = time.monotonic()
            self.calls += 1
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode('utf-8'))
                    return response.status, payload
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    raise RuntimeError(f'Finhay authentication/permission error HTTP {error.code}') from None
                if error.code == 429 or 500 <= error.code < 600:
                    self.failures[f'retry_http_{error.code}'] += 1
                    time.sleep(min(60, 2 ** attempt))
                    continue
                self.failures[f'http_{error.code}'] += 1
                return error.code, None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                self.failures['transport_or_json_retry'] += 1
                time.sleep(min(30, 2 ** attempt))
        self.failures['exhausted_retries'] += 1
        return None, None


def api_data(status, body):
    if status != 200 or not isinstance(body, dict) or str(body.get('error_code')) != '0':
        return None
    return body.get('data')


def write_csv_gz(path, columns, records):
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def get_events(client, symbol, start, end):
    events = []
    page = 1
    while True:
        status, body = client.get(f'/market/stocks/{urllib.parse.quote(symbol)}/events',
                                  {'from': start.isoformat(), 'to': end.isoformat(),
                                   'page': page, 'page_size': 50})
        data = api_data(status, body)
        if not isinstance(data, dict):
            return events, status if status != 200 else 'api_error'
        batch = data.get('events') or []
        events.extend(item for item in batch if isinstance(item, dict))
        pagination = data.get('pagination') or {}
        total_pages = pagination.get('total_pages')
        if not total_pages or page >= int(total_pages) or not batch:
            break
        page += 1
    return events, 200


def collect(output, work):
    api_key = os.environ.get('FINHAY_API_KEY')
    if not api_key:
        raise RuntimeError('FINHAY_API_KEY is unavailable in this workflow')
    output, work = Path(output), Path(work)
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    train_gz, train_jsonl = work / 'p1_train.jsonl.gz', work / 'p1_train.jsonl'
    holdout_jsonl = work / 'p1_holdout.jsonl'
    download(TRAIN_URL, train_gz)
    with gzip.open(train_gz, 'rb') as source, train_jsonl.open('wb') as destination:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            destination.write(chunk)
    download(HOLDOUT_URL, holdout_jsonl)
    if md5_file(train_jsonl) != TRAIN_MD5 or md5_file(holdout_jsonl) != HOLDOUT_MD5:
        raise RuntimeError('P1 source checksum mismatch; refusing to collect against changed data')

    symbols, p1_rows = seed_from_p1(train_jsonl, holdout_jsonl)
    client = FinhayClient(api_key)
    today = datetime.now(timezone.utc).date()
    report = {
        'collected_at': datetime.now(timezone.utc).isoformat(),
        'api_base': BASE_URL,
        'source_train_md5': TRAIN_MD5,
        'source_holdout_md5': HOLDOUT_MD5,
        'source_train_sha256': sha256_file(train_jsonl),
        'source_holdout_sha256': sha256_file(holdout_jsonl),
        'p1_bulk_rows': p1_rows,
        'p1_ticker_count': len(symbols),
        'p1_as_of_range': [min(v for s in symbols.values() for v in s['as_of']),
                           max(v for s in symbols.values() for v in s['as_of'])],
        'price_api_adjustment_semantics': 'undocumented; adjusted_total_return_close left blank',
        'session_calendar_basis': 'exchange index daily bars where available; not official calendar',
        'sector_membership_basis': 'current constituents snapshot; not point-in-time history',
        'request_count': 0,
        'failures': {},
    }

    catalog_status, catalog_body = client.get('/market/quotes/stocks')
    catalog = api_data(catalog_status, catalog_body)
    if not isinstance(catalog, list):
        raise RuntimeError(f'Finhay stock catalog failed with HTTP {catalog_status}')
    catalog_by_symbol = {str(item.get('symbol', '')).upper(): item
                         for item in catalog if isinstance(item, dict) and item.get('symbol')}
    all_symbols = sorted(set(symbols) | set(catalog_by_symbol))
    report['catalog_count'] = len(catalog_by_symbol)
    report['universe_scope'] = 'current catalog plus P1 historical tickers; not a full historical universe'

    collection_date = today.isoformat()
    sector_status, sector_body = client.get('/market/sectors', {'level': 1, 'page': 1, 'page_size': 50})
    sector_data = api_data(sector_status, sector_body)
    sectors = sector_data.get('items', []) if isinstance(sector_data, dict) else []
    current_sector = defaultdict(list)
    for sector in sectors:
        slug = sector.get('sector')
        if not slug:
            continue
        page = 1
        while True:
            status, body = client.get(f'/market/sectors/{slug}/constituents',
                                      {'page': page, 'page_size': 50})
            data = api_data(status, body)
            if not isinstance(data, dict):
                report['failures'][f'sector_{slug}_http_{status}'] = 1
                break
            items = data.get('items', [])
            for item in items:
                if item.get('symbol'):
                    current_sector[str(item['symbol']).upper()].append({
                        'sector_code': slug, 'sector_name': item.get('name') or sector.get('name'),
                        'exchange': item.get('exchange'), 'observed_at': data.get('updated_at') or collection_date,
                    })
            total_pages = data.get('total_pages')
            if not total_pages or page >= int(total_pages) or not items:
                break
            page += 1
    report['current_sector_count'] = len(current_sector)
    report['historical_sector_membership_available'] = False

    session_rows = []
    for exchange, index_symbol in EXCHANGE_INDEX.items():
        params = {'from': int(datetime(2014, 1, 1, tzinfo=timezone.utc).timestamp()),
                  'to': int(datetime.now(timezone.utc).timestamp()), 'resolution': '1D'}
        status, body = client.get(f'/market/quotes/indices/{index_symbol}/history', params)
        data = api_data(status, body)
        series = data.get('series', []) if isinstance(data, dict) else []
        if not series:
            report['failures'][f'index_{index_symbol}_http_{status}'] = 1
        for bar in series:
            if isinstance(bar, dict) and isinstance(bar.get('t'), (int, float)):
                session_rows.append({'exchange': exchange,
                                     'date': datetime.fromtimestamp(bar['t'], timezone.utc).date().isoformat(),
                                     'source_index': index_symbol})
    session_rows = sorted({(r['exchange'], r['date'], r['source_index']) for r in session_rows})
    write_csv_gz(output / 'exchange_sessions.csv.gz', ['exchange', 'date', 'source_index'],
                 [dict(zip(['exchange', 'date', 'source_index'], row)) for row in session_rows])
    report['index_session_rows'] = len(session_rows)
    report['index_session_date_range'] = ([min(row[1] for row in session_rows),
                                           max(row[1] for row in session_rows)] if session_rows else None)

    price_columns = ['security_id', 'ticker', 'exchange', 'date', 'open', 'high', 'low', 'close',
                     'volume', 'adjusted_total_return_close']
    action_columns = ['security_id', 'ticker', 'exchange', 'ex_date', 'record_date', 'action_type',
                      'description', 'rate_type', 'dividend_rate', 'dividend_value', 'ratio_display',
                      'ratio_base', 'ratio_entitled', 'details_json', 'source_event_id']
    security_columns = ['security_id', 'ticker', 'exchange', 'listing_date', 'delisting_date',
                        'active_from', 'active_to', 'sector_code', 'sector_name', 'sector_valid_from',
                        'sector_valid_to', 'sector_observed_at', 'metadata_basis']
    price_path = output / 'daily_prices.csv.gz'
    actions_path = output / 'corporate_actions.csv.gz'
    securities = []
    action_counts = Counter()
    prices_written = 0
    symbols_failed = Counter()
    with gzip.open(price_path, 'wt', encoding='utf-8', newline='') as price_stream, \
            gzip.open(actions_path, 'wt', encoding='utf-8', newline='') as actions_stream:
        price_writer = csv.DictWriter(price_stream, fieldnames=price_columns)
        action_writer = csv.DictWriter(actions_stream, fieldnames=action_columns)
        price_writer.writeheader()
        action_writer.writeheader()
        for index, symbol in enumerate(all_symbols, 1):
            p1_record = symbols.get(symbol)
            if not p1_record:
                continue
            observed_exchanges = sorted(p1_record['exchanges'])
            status, body = client.get(f'/market/stocks/{urllib.parse.quote(symbol)}/listing')
            listing = api_data(status, body)
            listing = listing if isinstance(listing, dict) else {}
            current_exchange = str(listing.get('exchange') or '').upper()
            if len(observed_exchanges) > 1 or (current_exchange and observed_exchanges
                                               and current_exchange not in observed_exchanges):
                exchange = 'UNKNOWN'
            else:
                exchange = current_exchange or (observed_exchanges[0] if observed_exchanges else 'UNKNOWN')
            status, body = client.get(f'/market/quotes/stocks/{urllib.parse.quote(symbol)}/history', {
                'from': int(datetime(2014, 1, 1, tzinfo=timezone.utc).timestamp()),
                'to': int(datetime.now(timezone.utc).timestamp()), 'resolution': '1D'})
            data = api_data(status, body)
            series = data.get('series', []) if isinstance(data, dict) else []
            if not series:
                symbols_failed['history'] += 1
            for bar in series:
                if not isinstance(bar, dict) or not isinstance(bar.get('t'), (int, float)):
                    continue
                price_writer.writerow({
                    'security_id': symbol, 'ticker': symbol, 'exchange': exchange,
                    'date': datetime.fromtimestamp(bar['t'], timezone.utc).date().isoformat(),
                    'open': bar.get('o'), 'high': bar.get('h'), 'low': bar.get('l'),
                    'close': bar.get('c'), 'volume': bar.get('v'),
                    'adjusted_total_return_close': '',
                })
                prices_written += 1
            events, event_status = get_events(client, symbol, START_DATE, today)
            if event_status != 200:
                symbols_failed['events'] += 1
            delisting_dates = []
            for event in events:
                action_type = event.get('event_type') or 'UNKNOWN'
                action_counts[action_type] += 1
                dates = event.get('dates') or {}
                details = event.get('details') or {}
                ex_date = dates.get('ex_date')
                if action_type == 'DELISTING' and ex_date:
                    delisting_dates.append(ex_date)
                ratio = details.get('ratio') or {}
                action_writer.writerow({
                    'security_id': symbol, 'ticker': symbol, 'exchange': exchange,
                    'ex_date': ex_date, 'record_date': dates.get('record_date'),
                    'action_type': action_type, 'description': event.get('description'),
                    'rate_type': details.get('rate_type'), 'dividend_rate': details.get('dividend_rate'),
                    'dividend_value': details.get('dividend_value'), 'ratio_display': ratio.get('display'),
                    'ratio_base': ratio.get('base'), 'ratio_entitled': ratio.get('entitled'),
                    'details_json': json.dumps(details, ensure_ascii=False, sort_keys=True),
                    'source_event_id': event.get('camast_id'),
                })
            for exchange_record in observed_exchanges or [exchange]:
                sector_records = current_sector.get(symbol) or [{}]
                for sector_record in sector_records:
                    securities.append({
                        'security_id': symbol, 'ticker': symbol,
                        'exchange': sector_record.get('exchange') or exchange_record,
                        'listing_date': listing.get('listing_date'),
                        'delisting_date': max(delisting_dates) if delisting_dates else None,
                        'active_from': listing.get('listing_date'),
                        'active_to': max(delisting_dates) if delisting_dates else None,
                        'sector_code': sector_record.get('sector_code'),
                        'sector_name': sector_record.get('sector_name'),
                        'sector_valid_from': None, 'sector_valid_to': None,
                        'sector_observed_at': sector_record.get('observed_at'),
                    'metadata_basis': 'P1 exchange observations and current listing/sector snapshots; no inferred historical transfer dates',
                    })
            if index % 100 == 0:
                print(f'FINHAY_COLLECT_PROGRESS ticker={index}/{len(all_symbols)} '
                      f'price_rows={prices_written} action_types={len(action_counts)}', flush=True)

    write_csv_gz(output / 'security_history.csv.gz', security_columns, securities)
    report.update({
        'p1_tickers_processed': len(symbols),
        'p1_tickers_with_history_failures': dict(symbols_failed),
        'daily_price_rows': prices_written,
        'corporate_action_counts': dict(sorted(action_counts.items())),
        'security_history_rows': len(securities),
        'adjusted_total_return_close_populated': 0,
        'reason_adjusted_close_blank': 'API history adjustment is undocumented; corporate action schema alone is insufficient to validate all factors',
        'exchange_sessions_are_official': False,
        'security_universe_is_complete_historical': False,
        'historical_sector_membership_available': False,
        'request_count': client.calls,
        'request_retries_and_failures': dict(client.failures),
        'created_files': {},
    })
    for name in ('exchange_sessions.csv.gz', 'daily_prices.csv.gz',
                 'corporate_actions.csv.gz', 'security_history.csv.gz'):
        path = output / name
        report['created_files'][name] = {'bytes': path.stat().st_size,
                                         'sha256': sha256_file(path)}
    (output / 'README.md').write_text(
        '# P2a Finhay market-data snapshot\n\n'
        f"Collected at {report['collected_at']} from `{BASE_URL}` using the read-only `X-FH-APIKEY` tier. "
        'No credentials are stored in these files.\n\n'
        '`daily_prices.csv.gz` contains raw Finhay daily OHLCV bars. '
        '`adjusted_total_return_close` is intentionally blank because the public API contract does not '
        'document its historical adjustment semantics. `corporate_actions.csv.gz` preserves event fields '
        'for later independently validated adjustment calculations.\n\n'
        '`exchange_sessions.csv.gz` is a proxy derived from daily index bars, not an official session calendar; '
        'Finhay session-status API returns current state only. Its history may start after 2014.\n\n'
        '`security_history.csv.gz` combines P1 sample tickers, listing responses, delisting events and the '
        'current sector constituents snapshot. Current sector membership is not historical point-in-time '
        'membership; historical universe coverage is incomplete. The gate must remain blocked until these '
        'limitations are resolved.\n', encoding='utf-8')
    report['created_files']['README.md'] = {
        'bytes': (output / 'README.md').stat().st_size,
        'sha256': sha256_file(output / 'README.md'),
    }
    (output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                          encoding='utf-8')
    print(json.dumps({'tickers': len(symbols), 'price_rows': prices_written,
                      'actions': sum(action_counts.values()), 'requests': client.calls,
                      'files': report['created_files']}, ensure_ascii=False, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='data/p2a-label-v2')
    parser.add_argument('--work', default='/tmp/p2a-finhay-work')
    args = parser.parse_args()
    collect(args.output, args.work)


if __name__ == '__main__':
    main()
