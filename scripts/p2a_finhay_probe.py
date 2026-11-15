#!/usr/bin/env python3
"""Probe documented Finhay market endpoints without logging credentials or raw bodies."""
import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = 'https://open-api.fhsc.com.vn'
START = int(datetime(2014, 1, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime.now(timezone.utc).timestamp())


class Probe:
    def __init__(self, api_key):
        self.api_key = api_key
        self.calls = 0
        self.last_call = 0.0

    def get(self, path, params=None):
        wait = 1.05 - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        url = BASE_URL + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            'X-FH-APIKEY': self.api_key,
            'Accept': 'application/json',
            'User-Agent': 'vn-stock-ai-p2a-data-audit/1.0',
        })
        self.last_call = time.monotonic()
        self.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            return error.code, None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None, None


def records(payload, *path):
    value = payload
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def probe_one(client, name, path, params=None, collection_paths=()):
    status, body = client.get(path, params)
    result = {'http_status': status}
    if not isinstance(body, dict):
        result['response_json'] = False
        return result
    result['error_code'] = str(body.get('error_code', ''))
    payload = body.get('data', body.get('result', body))
    result['payload_type'] = type(payload).__name__
    if isinstance(payload, list):
        result['payload_count'] = len(payload)
        result['first_item_keys'] = sorted(payload[0].keys()) if payload and isinstance(payload[0], dict) else []
    if isinstance(payload, dict):
        result['payload_keys'] = sorted(payload.keys())
        for label, path_parts in collection_paths:
            values = payload if not path_parts else records(payload, *path_parts)
            if isinstance(values, list):
                result[label] = {'count': len(values),
                                 'first_item_keys': sorted(values[0].keys())
                                 if values and isinstance(values[0], dict) else []}
                if name == 'stock_history' and values:
                    times = [item.get('t') for item in values if isinstance(item, dict)
                             and isinstance(item.get('t'), (int, float))]
                    if times:
                        result[label]['first_utc'] = datetime.fromtimestamp(
                            min(times), timezone.utc).date().isoformat()
                        result[label]['last_utc'] = datetime.fromtimestamp(
                            max(times), timezone.utc).date().isoformat()
                if name == 'stock_events' and values:
                    kinds = {}
                    dates = []
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        kinds[item.get('event_type', 'unknown')] = \
                            kinds.get(item.get('event_type', 'unknown'), 0) + 1
                        day = records(item, 'dates', 'ex_date')
                        if day:
                            dates.append(day)
                    result[label]['event_types'] = kinds
                    result[label]['ex_date_range'] = [min(dates), max(dates)] if dates else None
                    result[label]['action_examples'] = [
                        {'event_type': item.get('event_type'),
                         'dates': item.get('dates'), 'details': item.get('details')}
                        for item in values[:12] if isinstance(item, dict)]
    else:
        result['payload_keys'] = []
    return result


def run_probe(api_key):
    client = Probe(api_key)
    unix_params = {'from': START, 'to': END, 'resolution': '1D'}
    date_params = {'from': '2017-01-01', 'to': datetime.now(timezone.utc).date().isoformat(),
                   'page': 1, 'page_size': 50}
    checks = {
        'stock_catalog': ('/market/quotes/stocks', {'page': 1, 'page_size': 5},
                          [('items', ('items',))]),
        'stock_history': ('/market/quotes/stocks/VNM/history', unix_params,
                          [('series', ('series',))]),
        'upcom_index_history': ('/market/quotes/indices/UPCOMINDEX/history', unix_params,
                                [('series', ('series',))]),
        'hose_session_now': ('/trading/market/session', {'exchange': 'HOSE'}, []),
        'hnx_session_now': ('/trading/market/session', {'exchange': 'HNX'}, []),
        'upcom_session_now': ('/trading/market/session', {'exchange': 'UPCOM'}, []),
        'stock_listing': ('/market/stocks/VNM/listing', None, []),
        'stock_events': ('/market/stocks/VNM/events', date_params,
                         [('events', ('events',))]),
        'cash_dividend_events': ('/market/stocks/VNM/events',
                                 {**date_params, 'page_size': 10, 'event_type': 'CASH_DIVIDEND'},
                                 [('events', ('events',))]),
        'stock_dividend_events': ('/market/stocks/VNM/events',
                                  {**date_params, 'page_size': 10, 'event_type': 'STOCK_DIVIDEND'},
                                  [('events', ('events',))]),
        'stock_split_events': ('/market/stocks/VNM/events',
                               {**date_params, 'page_size': 10, 'event_type': 'STOCK_SPLIT'},
                               [('events', ('events',))]),
        'sector_list': ('/market/sectors', {'level': 1, 'page': 1, 'page_size': 50},
                        [('items', ('items',))]),
        'financials_constituents': ('/market/sectors/financials/constituents',
                                    {'page': 1, 'page_size': 5},
                                    [('items', ('items',))]),
        'financials_sector_history': ('/market/sectors/financials/performance/history',
                                      {'from': '2021-11-15',
                                       'to': datetime.now(timezone.utc).date().isoformat()},
                                      [('items', ('items',))]),
    }
    report = {
        'base_url': BASE_URL,
        'collected_at': datetime.now(timezone.utc).isoformat(),
        'requested_price_range': ['2014-01-01', datetime.now(timezone.utc).date().isoformat()],
        'checks': {},
        'credential_values_written': False,
    }
    for name, (path, params, collections) in checks.items():
        report['checks'][name] = probe_one(client, name, path, params, collections)
        print(f"FINHAY_PROBE {name} http={report['checks'][name]['http_status']} "
              f"json={report['checks'][name].get('response_json', True)}", flush=True)
    report['request_count'] = client.calls
    exdate_start = int(datetime(2025, 5, 10, tzinfo=timezone.utc).timestamp())
    exdate_end = int(datetime(2025, 5, 20, tzinfo=timezone.utc).timestamp())
    status, body = client.get('/market/quotes/stocks/VNM/history', {
        'from': exdate_start, 'to': exdate_end, 'resolution': '1D'})
    data = api_data(status, body)
    series = data.get('series', []) if isinstance(data, dict) else []
    report['cash_dividend_adjustment_sample'] = {
        'symbol': 'VNM', 'event_ex_date': '2025-05-14',
        'http_status': status,
        'series': [{'date': datetime.fromtimestamp(item['t'], timezone.utc).date().isoformat(),
                    'close': item.get('c')} for item in series
                   if isinstance(item, dict) and isinstance(item.get('t'), (int, float))],
        'api_documentation_confirms_adjustment_semantics': False,
    }
    report['request_count'] = client.calls
    report['findings'] = {
        'market_read_auth': 'X-FH-APIKEY',
        'trading_session_endpoint_is_current_only': True,
        'price_adjustment_semantics_documented': False,
        'historical_sector_membership_endpoint_documented': False,
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    api_key = os.environ.get('FINHAY_API_KEY')
    if not api_key:
        raise SystemExit('FINHAY_API_KEY is not available to this workflow')
    report = run_probe(api_key)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'FINHAY_PROBE_REPORT_SAVED {output}', flush=True)


if __name__ == '__main__':
    main()
