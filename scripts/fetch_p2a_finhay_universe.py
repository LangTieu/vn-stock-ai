#!/usr/bin/env python3
"""Fetch Finhay's current supported-symbol and current-sector snapshots."""
import argparse
import csv
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = 'https://open-api.fhsc.com.vn'


class Client:
    def __init__(self, key):
        self.key = key
        self.last = 0
        self.calls = 0

    def get(self, path, params=None):
        url = BASE + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        for attempt in range(6):
            wait = 1.05 - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.calls += 1
            request = urllib.request.Request(url, headers={
                'X-FH-APIKEY': self.key, 'Accept': 'application/json',
                'User-Agent': 'vn-stock-ai-p2a-current-universe/1.0'})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    return response.status, json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    return error.code, None
                time.sleep(min(60, 2 ** attempt))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                if attempt == 5:
                    return None, None
                time.sleep(min(30, 2 ** attempt))


def data_of(status, body):
    if status != 200 or not isinstance(body, dict) or str(body.get('error_code')) != '0':
        return None
    return body.get('data')


def write_gzip_csv(path, columns, rows):
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def collect(output):
    key = os.environ.get('FINHAY_API_KEY')
    if not key:
        raise SystemExit('FINHAY_API_KEY is unavailable in this workflow')
    client = Client(key)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(timezone.utc).isoformat()
    status, body = client.get('/market/quotes/stocks')
    catalog = data_of(status, body)
    if not isinstance(catalog, list):
        raise RuntimeError(f'Finhay catalog failed with HTTP {status}')
    symbols = {str(row.get('symbol', '')).upper(): row for row in catalog
               if isinstance(row, dict) and row.get('symbol')}
    sector_records = []
    by_symbol = defaultdict(list)
    status, body = client.get('/market/sectors', {'level': 1, 'page': 1, 'page_size': 50})
    data = data_of(status, body)
    if not isinstance(data, dict):
        raise RuntimeError(f'Finhay sector list failed with HTTP {status}')
    for sector in data.get('items') or []:
        slug = sector.get('sector')
        if not slug:
            continue
        page, page_size = 1, 50
        while True:
            status, body = client.get(f'/market/sectors/{urllib.parse.quote(slug)}/constituents',
                                      {'page': page, 'page_size': page_size})
            page_data = data_of(status, body)
            if not isinstance(page_data, dict):
                raise RuntimeError(f'Finhay sector constituents failed for {slug} HTTP {status}')
            items = page_data.get('items') or []
            for item in items:
                symbol = str(item.get('symbol', '')).upper()
                if not symbol:
                    continue
                record = {
                    'security_id': symbol, 'ticker': symbol, 'exchange': item.get('exchange'),
                    'sector_code': slug, 'sector_name': item.get('name') or sector.get('name'),
                    'weight_percent': item.get('weight_percent'), 'market_cap': item.get('market_cap'),
                    'observed_at': page_data.get('updated_at') or observed,
                }
                sector_records.append(record)
                by_symbol[symbol].append(record)
            total = page_data.get('total')
            current_page_size = int(page_data.get('page_size') or page_size)
            if not items or (total is not None and page * current_page_size >= int(total)):
                break
            if total is None and len(items) < current_page_size:
                break
            page += 1
    universe = []
    for symbol, info in sorted(symbols.items()):
        memberships = by_symbol.get(symbol) or [{}]
        for member in memberships:
            universe.append({
                'security_id': symbol, 'ticker': symbol,
                'exchange': member.get('exchange') or 'UNKNOWN', 'name': info.get('name'),
                'sector_code': member.get('sector_code'), 'sector_name': member.get('sector_name'),
                'observed_at': member.get('observed_at') or observed,
                'temporal_scope': 'current snapshot only; not historical point-in-time membership',
            })
    sector_path = output / 'finhay_current_sector_constituents.csv.gz'
    universe_path = output / 'finhay_current_universe.csv.gz'
    write_gzip_csv(sector_path, ['security_id','ticker','exchange','sector_code','sector_name',
                                 'weight_percent','market_cap','observed_at'], sector_records)
    write_gzip_csv(universe_path, ['security_id','ticker','exchange','name','sector_code','sector_name',
                                   'observed_at','temporal_scope'], universe)
    manifest = {
        'collected_at': observed, 'source': BASE,
        'catalog_symbols': len(symbols), 'current_sector_constituent_rows': len(sector_records),
        'current_symbols_with_sector': len(by_symbol),
        'historical_sector_membership_endpoint': 'not documented/available in this API collection',
        'files': {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)}
                  for p in (sector_path, universe_path)},
        'request_count': client.calls,
        'files_temporal_scope': 'current snapshot, not point-in-time history',
    }
    (output / 'finhay-current-universe-manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'catalog_symbols': len(symbols),
                      'current_sector_rows': len(sector_records),
                      'symbols_with_sector': len(by_symbol), 'requests': client.calls,
                      'files': manifest['files']}, ensure_ascii=False, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='data/p2a-label-v2')
    args = parser.parse_args()
    collect(args.output)


if __name__ == '__main__':
    main()
