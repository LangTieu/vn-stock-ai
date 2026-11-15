#!/usr/bin/env python3
"""Build private P2a v2 labels from a Finfo endpoint audit; never exports prices."""
import argparse
import csv
import gzip
import json
import shutil
import tempfile
from pathlib import Path

try:
    from .p2a_relabel import relabel_file, sha256
except ImportError:
    from p2a_relabel import relabel_file, sha256


def build(train, holdout, sessions, endpoints, audit_path, output_dir):
    train, holdout, sessions = Path(train), Path(holdout), Path(sessions)
    endpoints, audit_path, output_dir = Path(endpoints), Path(audit_path), Path(output_dir)
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    if audit.get('fetch_errors_by_type'):
        raise ValueError(f"Finfo fetch errors remain: {audit['fetch_errors_by_type']}")
    expected_hashes = audit.get('p1_sha256') or {}
    for path in (train, holdout):
        expected = expected_hashes.get(path.name)
        if not expected or sha256(path) != expected:
            raise ValueError(f'P1 input hash does not match Finfo endpoint audit: {path.name}')
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='p2a-finfo-v2-') as temporary:
        tmp = Path(temporary)
        plain_sessions = tmp / 'exchange_sessions.csv'
        with gzip.open(sessions, 'rb') as source, plain_sessions.open('wb') as target:
            shutil.copyfileobj(source, target)
        adjusted_prices = tmp / 'adjusted_prices.csv'
        with gzip.open(endpoints, 'rt', encoding='utf-8', newline='') as source, \
                adjusted_prices.open('w', encoding='utf-8', newline='') as target:
            reader = csv.DictReader(source)
            writer = csv.DictWriter(target, fieldnames=[
                'ticker', 'exchange', 'date', 'adjusted_total_return_close',
            ])
            writer.writeheader()
            for row in reader:
                adjusted = (row.get('adClose') or '').strip()
                if not adjusted:
                    continue
                writer.writerow({
                    'ticker': row['ticker'], 'exchange': row['exchange'],
                    'date': row['date'], 'adjusted_total_return_close': adjusted,
                })

        manifests = {}
        for label, source_path in (('train', train), ('holdout', holdout)):
            plain_p1 = tmp / f'p1_{label}.jsonl'
            if source_path.suffix == '.gz':
                with gzip.open(source_path, 'rb') as source, plain_p1.open('wb') as target:
                    shutil.copyfileobj(source, target)
            else:
                shutil.copyfile(source_path, plain_p1)
            output_path = output_dir / f'p1_{label}_v2.jsonl'
            manifest_path = output_dir / f'p1_{label}_v2.manifest.json'
            result = relabel_file(plain_p1, output_path, manifest_path,
                                  plain_sessions, adjusted_prices)
            result['source'] = source_path.name
            result['source_sha256'] = sha256(source_path)
            result['calendar_sha256'] = audit['sessions_sha256']
            result['finfo_endpoint_audit_p1_sha256'] = expected_hashes[source_path.name]
            result['adclose_endpoint_prices_exported'] = False
            result['gate_status'] = 'label candidates only; full survivorship/sector gate is separate'
            manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                                     encoding='utf-8')
            manifests[label] = result

    summary = {
        'method': 'VNDirect Finfo adClose; exact 120th observed exchange session; unavailable endpoints censored',
        'source': 'VNDirect Finfo API via api-finfo.vndirect.com.vn',
        'audit_sha256': sha256(audit_path),
        'p1_sha256': expected_hashes,
        'session_calendar_sha256': audit['sessions_sha256'],
        'endpoint_prices_sha256': audit['endpoint_prices_sha256'],
        'labels_generated': True,
        'adclose_endpoint_prices_in_artifact': False,
        'passes': False,
        'blocked_by': ['point-in-time listing/universe history', 'point-in-time sector history'],
        'splits': manifests,
    }
    (output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                            encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', required=True)
    parser.add_argument('--holdout', required=True)
    parser.add_argument('--sessions', required=True)
    parser.add_argument('--endpoints', required=True)
    parser.add_argument('--audit', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    summary = build(args.train, args.holdout, args.sessions, args.endpoints,
                    args.audit, args.output_dir)
    print(json.dumps({
        'labels_generated': summary['labels_generated'],
        'passes': summary['passes'],
        'adclose_endpoint_prices_in_artifact': summary['adclose_endpoint_prices_in_artifact'],
        'counts': {split: result['counts'] for split, result in summary['splits'].items()},
    }, sort_keys=True))


if __name__ == '__main__':
    main()
