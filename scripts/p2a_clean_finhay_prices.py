#!/usr/bin/env python3
"""Remove only impossible all-zero OHLC placeholders from a Finhay price snapshot."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

PRICE_FIELDS = ('open', 'high', 'low', 'close')
REQUIRED = {'security_id', 'ticker', 'exchange', 'date', *PRICE_FIELDS, 'volume',
            'adjusted_total_return_close'}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def clean(source, output, manifest):
    source, output, manifest = Path(source), Path(output), Path(manifest)
    if output.resolve() == source.resolve() or manifest.resolve() in {source.resolve(), output.resolve()}:
        raise ValueError('source, output and manifest paths must be distinct')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + f'.tmp-{os.getpid()}')
    counts = {'input_rows': 0, 'kept_rows': 0, 'removed_all_zero_ohlc': 0,
              'rejected_invalid_numeric': 0, 'rejected_bad_ohlc_order': 0}
    bad_examples = []
    try:
        with gzip.open(source, 'rt', encoding='utf-8', newline='') as input_stream, \
                gzip.open(temp, 'wt', encoding='utf-8', newline='') as output_stream:
            reader = csv.DictReader(input_stream)
            missing = sorted(REQUIRED - set(reader.fieldnames or ()))
            if missing:
                raise ValueError(f'input missing required columns: {missing}')
            writer = csv.DictWriter(output_stream, fieldnames=reader.fieldnames)
            writer.writeheader()
            for line_no, row in enumerate(reader, 2):
                counts['input_rows'] += 1
                try:
                    ohlc = {field: float(row[field]) for field in PRICE_FIELDS if row[field].strip()}
                except (TypeError, ValueError):
                    counts['rejected_invalid_numeric'] += 1
                    continue
                if set(ohlc) != set(PRICE_FIELDS):
                    counts['rejected_invalid_numeric'] += 1
                    continue
                if all(value == 0 for value in ohlc.values()):
                    counts['removed_all_zero_ohlc'] += 1
                    if len(bad_examples) < 20:
                        bad_examples.append({'line': line_no, 'ticker': row['ticker'],
                                             'exchange': row['exchange'], 'date': row['date'],
                                             'reason': 'all OHLC fields are zero'})
                    continue
                if any(not math.isfinite(value) or value <= 0 for value in ohlc.values()):
                    counts['rejected_invalid_numeric'] += 1
                    if len(bad_examples) < 20:
                        bad_examples.append({'line': line_no, 'ticker': row['ticker'],
                                             'exchange': row['exchange'], 'date': row['date'],
                                             'reason': 'nonpositive OHLC field'})
                    continue
                if not (ohlc['low'] <= min(ohlc['open'], ohlc['close'])
                        <= max(ohlc['open'], ohlc['close']) <= ohlc['high']):
                    counts['rejected_bad_ohlc_order'] += 1
                    continue
                writer.writerow(row)
                counts['kept_rows'] += 1
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    result = {'source': source.name, 'source_sha256': sha256(source),
              'output': output.name, 'output_sha256': sha256(output),
              'counts': counts, 'removed_examples': bad_examples,
              'cleaning_rule': 'only all-zero OHLC placeholders and malformed/nonpositive bars are excluded; raw source is retained'}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    tmp_manifest = manifest.with_name(manifest.name + f'.tmp-{os.getpid()}')
    tmp_manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')
    os.replace(tmp_manifest, manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    result = clean(args.input, args.output, args.manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
