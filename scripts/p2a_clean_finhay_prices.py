#!/usr/bin/env python3
"""Remove only impossible all-zero OHLC placeholders from a Finhay price snapshot."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
from collections import Counter
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
              'rejected_invalid_close': 0, 'blanked_invalid_nonclose_cells': 0,
              'ohlc_order_mismatch_rows': 0}
    quality_counts = Counter()
    bad_examples = []
    try:
        with gzip.open(source, 'rt', encoding='utf-8', newline='') as input_stream, \
                gzip.open(temp, 'wt', encoding='utf-8', newline='') as output_stream:
            reader = csv.DictReader(input_stream)
            missing = sorted(REQUIRED - set(reader.fieldnames or ()))
            if missing:
                raise ValueError(f'input missing required columns: {missing}')
            fieldnames = list(reader.fieldnames)
            if 'data_quality_flag' not in fieldnames:
                fieldnames.append('data_quality_flag')
            writer = csv.DictWriter(output_stream, fieldnames=fieldnames)
            writer.writeheader()
            for line_no, row in enumerate(reader, 2):
                counts['input_rows'] += 1
                parsed = {}
                for field in PRICE_FIELDS:
                    raw = row.get(field, '').strip()
                    try:
                        parsed[field] = float(raw) if raw else None
                    except (TypeError, ValueError):
                        parsed[field] = None
                if all(value == 0 for value in parsed.values()):
                    counts['removed_all_zero_ohlc'] += 1
                    quality_counts['removed_all_zero_ohlc'] += 1
                    if len(bad_examples) < 20:
                        bad_examples.append({'line': line_no, 'ticker': row['ticker'],
                                             'exchange': row['exchange'], 'date': row['date'],
                                             'reason': 'all OHLC fields are zero'})
                    continue
                close = parsed['close']
                if close is None or not math.isfinite(close) or close <= 0:
                    counts['rejected_invalid_close'] += 1
                    quality_counts['rejected_invalid_close'] += 1
                    continue
                flags = []
                for field in ('open', 'high', 'low'):
                    value = parsed[field]
                    if value is None or not math.isfinite(value) or value <= 0:
                        row[field] = ''
                        counts['blanked_invalid_nonclose_cells'] += 1
                        flags.append(f'invalid_{field}')
                if (parsed['open'] is not None and parsed['high'] is not None
                        and parsed['low'] is not None and all(math.isfinite(parsed[f])
                            and parsed[f] > 0 for f in ('open', 'high', 'low'))
                        and not (parsed['low'] <= min(parsed['open'], close)
                                 <= max(parsed['open'], close) <= parsed['high'])):
                    counts['ohlc_order_mismatch_rows'] += 1
                    flags.append('ohlc_order_mismatch')
                volume = row.get('volume', '').strip()
                if volume:
                    try:
                        volume_value = float(volume)
                    except ValueError:
                        volume_value = float('nan')
                    if not math.isfinite(volume_value) or volume_value < 0:
                        row['volume'] = ''
                        counts['blanked_invalid_nonclose_cells'] += 1
                        flags.append('invalid_volume')
                row['data_quality_flag'] = ';'.join(flags) if flags else 'ok'
                quality_counts[row['data_quality_flag']] += 1
                writer.writerow(row)
                counts['kept_rows'] += 1
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    result = {'source': source.name, 'source_sha256': sha256(source),
              'output': output.name, 'output_sha256': sha256(output),
              'counts': counts, 'quality_flag_counts': dict(sorted(quality_counts.items())),
              'removed_examples': bad_examples,
              'cleaning_rule': 'drop all-zero/no-close bars; preserve valid closes and flag nonclose OHLC/order issues; raw source retained'}
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
