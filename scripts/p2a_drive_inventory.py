#!/usr/bin/env python3
"""Read-only inventory of P2 source JSONs in Google Drive; never exports price data."""
import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

EXPECTED = {f'train_2014_2026_{exchange}.json'
            for exchange in ('HOSE', 'HNX', 'UPCOM', 'OTC')}
QUERY = "trashed = false and (" + ' or '.join(
    [f"name = '{name}'" for name in sorted(EXPECTED)] + ["name contains 'finhay_train_'"]
) + ')'
DATE_KEYS = {'date', 'time', 'timestamp', 'tradingdate', 'trading_date', 'asof', 'as_of'}
SYMBOL_KEYS = {'ticker', 'symbol', 'code', 'stock_code', 'organ_code'}
PRICE_KEYS = {'open', 'high', 'low', 'close', 'o', 'h', 'l', 'c'}


def _parse_date(value):
    if isinstance(value, (int, float)) and value > 0:
        timestamp = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace('Z', '+00:00')).date()
        except ValueError:
            return None


def _inspect_json(path):
    report = {
        'sha256': _sha256(path), 'bytes': path.stat().st_size,
        'top_level_type': None, 'json_objects': 0, 'ohlcv_objects': 0,
        'row_objects_with_date_and_ohlc': 0, 'field_names': set(),
        'field_types': Counter(), 'date_ranges': {}, 'distinct_symbol_count': 0,
        'json_decode_error': None,
    }
    dates = {}
    symbols = set()

    def walk(value):
        if isinstance(value, dict):
            report['json_objects'] += 1
            keys = {str(key).strip().lower() for key in value}
            for key, item in value.items():
                key_normalized = str(key).strip().lower()
                if not isinstance(item, (dict, list)):
                    report['field_names'].add(str(key))
                    report['field_types'][f'{key_normalized}:{type(item).__name__}'] += 1
                if key_normalized in DATE_KEYS:
                    date_values = item if isinstance(item, list) else [item]
                    for date_value in date_values:
                        parsed = _parse_date(date_value)
                        if parsed:
                            dates.setdefault(key_normalized, []).append(parsed)
                if key_normalized in SYMBOL_KEYS and isinstance(item, str) and item.strip():
                    symbols.add(item.strip().upper())
            if len(keys & PRICE_KEYS) >= 3:
                report['ohlcv_objects'] += 1
                if keys & DATE_KEYS:
                    report['row_objects_with_date_and_ohlc'] += 1
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    try:
        with path.open(encoding='utf-8') as stream:
            document = json.load(stream)
        report['top_level_type'] = type(document).__name__
        walk(document)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        report['json_decode_error'] = type(error).__name__
    report['distinct_symbol_count'] = len(symbols)
    report['field_names'] = sorted(report['field_names'])[:250]
    report['field_types'] = dict(sorted(report['field_types'].items())[:250])
    report['date_ranges'] = {
        key: [min(values).isoformat(), max(values).isoformat()]
        for key, values in sorted(dates.items()) if values
    }
    return report


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_api_error(response):
    try:
        error = response.json().get('error') or {}
    except (ValueError, AttributeError):
        error = {}
    reasons = sorted({item.get('reason', '') for item in error.get('errors', [])
                      if item.get('reason')})
    message = str(error.get('message') or '')
    message = re.sub(r'(?i)bearer\s+\S+|ya29\.[A-Za-z0-9._-]+', '[REDACTED]', message)
    return {'http_status': response.status_code, 'api_reasons': reasons,
            'api_message': message[:400]}


def inventory(token_file, output, quota_project=None):
    import requests
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials

    credentials = Credentials.from_authorized_user_file(str(token_file))
    if not credentials.valid:
        if not credentials.expired or not credentials.refresh_token:
            raise RuntimeError('Google Drive OAuth credentials cannot be refreshed')
        credentials.refresh(Request())
    client_project = str(getattr(credentials, 'client_id', '') or '').split('-', 1)[0]
    selected_project = quota_project or (client_project if client_project.isdigit() else None)
    if selected_project:
        credentials = credentials.with_quota_project(selected_project)
    session = AuthorizedSession(credentials)
    query = QUERY
    page_token = None
    files = []
    access_error = None
    try:
        while True:
            params = {
                'q': query, 'pageSize': 1000,
                'fields': 'nextPageToken,files(id,name,mimeType,size,modifiedTime,driveId)',
                'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true',
                'corpora': 'allDrives',
            }
            if page_token:
                params['pageToken'] = page_token
            response = session.get('https://www.googleapis.com/drive/v3/files',
                                   params=params, timeout=60)
            if response.status_code == 400:
                params.pop('corpora', None)
                response = session.get('https://www.googleapis.com/drive/v3/files',
                                       params=params, timeout=60)
            if response.status_code != 200:
                access_error = _safe_api_error(response)
                break
            payload = response.json()
            files.extend(payload.get('files') or [])
            page_token = payload.get('nextPageToken')
            if not page_token:
                break
    except requests.RequestException as error:
        access_error = {'transport_error': type(error).__name__}

    records = []
    with tempfile.TemporaryDirectory(prefix='p2a-drive-read-') as temporary:
        for index, item in enumerate(files):
            name = item.get('name', '')
            if name not in EXPECTED and not re.fullmatch(r'finhay_train_.*\.json', name, re.I):
                continue
            target = Path(temporary) / f'{index}.json'
            response = session.get(
                f"https://www.googleapis.com/drive/v3/files/{item['id']}",
                params={'alt': 'media', 'supportsAllDrives': 'true'},
                timeout=180, stream=True)
            if response.status_code != 200:
                records.append({'name': name, 'mime_type': item.get('mimeType'),
                                'download_error': f'HTTP {response.status_code}'})
                continue
            with target.open('wb') as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)
            record = {'name': name, 'mime_type': item.get('mimeType'),
                      'modified_time': item.get('modifiedTime'),
                      **_inspect_json(target)}
            records.append(record)
    result = {
        'method': 'Google Drive API read-only metadata and structural inventory; source data not exported',
        'oauth_drive_file_scope_present': credentials.has_scopes(
            ['https://www.googleapis.com/auth/drive.file']),
        'quota_project_source': ('caller-provided' if quota_project else
                                 'OAuth client project' if client_project.isdigit() else None),
        'quota_project_configured': bool(getattr(credentials, 'quota_project_id', None)),
        'drive_api_access_error': access_error,
        'expected_file_names': sorted(EXPECTED),
        'matching_file_count': len(records),
        'files': records,
        'access_error': access_error,
        'missing_expected_files': sorted(
            name for name in EXPECTED if not any(file['name'] == name for file in records)),
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')
    print(json.dumps({
        'matching_file_count': len(records),
        'exact_source_file_count': sum(file['name'] in EXPECTED for file in records),
        'missing_expected_file_count': len(result['missing_expected_files']),
        'schemas_valid': access_error is None and all(
            not file.get('json_decode_error') and not file.get('download_error')
            for file in records),
        'report': str(output),
    }, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--quota-project', default=None,
                        help='Google Cloud quota project with serviceusage.services.use for this OAuth user')
    args = parser.parse_args()
    inventory(args.token_file, args.output, args.quota_project)


if __name__ == '__main__':
    main()
