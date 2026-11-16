#!/usr/bin/env python3
"""Prepare, sign, publish, and verify the private P2a V2 train/validation dataset."""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from p2a_ablation_slices import make_slices
from p2a_train import dataset_label_spec, require_v2_training

DATASET_REPO_ID = 'Jerlob/vn-stock-ai-p2a-v2'
APPROVED_SOURCE_RUN_ID = 43691791091
TRAIN_FILE = 'train-v2.jsonl'
VALIDATION_FILE = 'validation-v2.jsonl'
MANIFEST_FILE = 'v2-dataset-manifest.json'
SIGNATURE_FILE = 'v2-dataset-manifest.sig'
METHOD = 'adjusted_total_return_close; 120 exchange sessions after as_of'
FLAT_BAND_PCT = 2.0
ALLOWED_PUBLISHED_FILES = {TRAIN_FILE, VALIDATION_FILE, MANIFEST_FILE, SIGNATURE_FILE}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path):
    digest = hashlib.md5()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _key_bytes(value, name):
    try:
        return base64.b64decode(value, validate=True)
    except Exception as error:
        raise ValueError(f'{name} must be base64 encoded') from error


def sign_manifest(manifest, private_key_b64, public_key_b64):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_bytes = _key_bytes(private_key_b64, 'private signing key')
    public_bytes = _key_bytes(public_key_b64, 'public signing key')
    if len(private_bytes) != 32 or len(public_bytes) != 32:
        raise ValueError('Ed25519 raw private seed and public key must each be 32 bytes')
    key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    actual_public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    if actual_public != public_bytes:
        raise ValueError('configured signing public key does not match private key')
    return {
        'algorithm': 'Ed25519',
        'public_key_sha256': hashlib.sha256(public_bytes).hexdigest(),
        'signature_base64': base64.b64encode(key.sign(canonical_json(manifest))).decode('ascii'),
    }


def verify_manifest_signature(manifest, signature, trusted_public_key_b64):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    public_bytes = _key_bytes(trusted_public_key_b64, 'trusted public key')
    if len(public_bytes) != 32 or signature.get('algorithm') != 'Ed25519':
        raise ValueError('unsupported V2 dataset signature format')
    if signature.get('public_key_sha256') != hashlib.sha256(public_bytes).hexdigest():
        raise ValueError('V2 dataset signing-key fingerprint mismatch')
    try:
        signature_bytes = base64.b64decode(signature['signature_base64'], validate=True)
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature_bytes, canonical_json(manifest))
    except Exception as error:
        raise ValueError('V2 dataset manifest signature verification failed') from error
    return True


def _count_rows(path):
    total = 0
    classes = {'UP': 0, 'DOWN': 0}
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            metadata = row.get('metadata') or {}
            if metadata.get('kind') != 'bulk' or metadata.get('p2a_label_version') != 2:
                raise ValueError(f'{Path(path).name} contains a non-bulk or non-v2 row')
            label = ((metadata.get('label') or {}).get('future_direction_120'))
            if label not in classes or metadata.get('p2a_label_status') != 'labeled':
                raise ValueError(f'{Path(path).name} includes a non-binary/censored train or validation row')
            classes[label] += 1
            total += 1
    if not total:
        raise ValueError(f'{Path(path).name} is empty')
    return {'rows': total, 'class_counts': classes}


def prepare_dataset(source_train, source_manifest, source_run_id, output_dir):
    source_train, source_manifest, output = Path(source_train), Path(source_manifest), Path(output_dir)
    if int(source_run_id) != APPROVED_SOURCE_RUN_ID:
        raise ValueError(f'V2 dataset preparation is restricted to audited source run {APPROVED_SOURCE_RUN_ID}')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('publication staging directory must be empty')
    source_info = json.loads(source_manifest.read_text(encoding='utf-8'))
    if source_info.get('label_version') != 2:
        raise ValueError('source label artifact manifest is not version 2')
    if source_info.get('output_sha256') != sha256_file(source_train):
        raise ValueError('source V2 train checksum does not match its audited manifest')
    source_spec = dataset_label_spec(source_train)
    require_v2_training(source_spec)
    if source_spec.get('label_method') != METHOD or source_spec.get('flat_band_pct') != FLAT_BAND_PCT:
        raise ValueError('source V2 labels do not match the approved method and FLAT band')

    split = make_slices(source_train, output, validation_year=2024,
                        train_per_class=100000, validation_per_class=100000, seed=42)
    (output / 'split-manifest.json').unlink(missing_ok=True)
    train_path, validation_path = output / 'train-v2.jsonl', output / 'validation-v2.jsonl'
    (output / 'train-v2.manifest.json').unlink(missing_ok=True)
    (output / 'validation-v2.manifest.json').unlink(missing_ok=True)
    if not split.get('passes') or split.get('external_holdout_used_for_selection') is not False:
        raise ValueError('internal time split failed its leakage/holdout checks')
    train_spec, validation_spec = dataset_label_spec(train_path), dataset_label_spec(validation_path)
    for path, spec in ((train_path, train_spec), (validation_path, validation_spec)):
        require_v2_training(spec)
        if spec.get('label_method') != METHOD or spec.get('flat_band_pct') != FLAT_BAND_PCT:
            raise ValueError(f'{path.name} has incompatible label semantics')
    manifest = {
        'schema_version': 1,
        'dataset_id': DATASET_REPO_ID,
        'source_label_run_id': int(source_run_id),
        'source_train_sha256': sha256_file(source_train),
        'label_version': 2,
        'label_method': METHOD,
        'horizon_sessions': 120,
        'flat_band_pct': FLAT_BAND_PCT,
        'censor_policy': 'exact adjusted endpoints only; unavailable exact 120th-session endpoint rows are censored',
        'training_policy': 'binary UP/DOWN rows; FLAT and censored rows excluded',
        'validation_policy': 'all labeled UP/DOWN rows with as_of in 2024; reused in short ablation, not a pristine test',
        'external_holdout_included': False,
        'raw_adjusted_price_table_included': False,
        'split': {
            'validation_year': 2024,
            'train_target_endpoint_max': split['actual_split']['train_target_endpoint_max'],
            'validation_as_of_min': split['actual_split']['validation_as_of_min'],
            'train_target_before_validation_as_of': split['actual_split']['train_target_before_validation_as_of'],
        },
        'files': {
            TRAIN_FILE: {'sha256': sha256_file(train_path), 'md5': md5_file(train_path), **_count_rows(train_path)},
            VALIDATION_FILE: {'sha256': sha256_file(validation_path), 'md5': md5_file(validation_path), **_count_rows(validation_path)},
        },
    }
    (output / MANIFEST_FILE).write_bytes(canonical_json(manifest) + b'\n')
    return manifest


def _validate_publish_staging(root):
    root = Path(root)
    if {p.name for p in root.iterdir() if p.is_file()} != {TRAIN_FILE, VALIDATION_FILE, MANIFEST_FILE}:
        raise ValueError('staging must contain only train-v2.jsonl, validation-v2.jsonl, and the dataset manifest')
    manifest = json.loads((root / MANIFEST_FILE).read_text(encoding='utf-8'))
    if manifest.get('dataset_id') != DATASET_REPO_ID or manifest.get('label_version') != 2:
        raise ValueError('V2 dataset manifest/repository mismatch')
    if manifest.get('raw_adjusted_price_table_included') is not False or manifest.get('external_holdout_included') is not False:
        raise ValueError('raw adjusted prices or external holdout are forbidden in publication')
    for name in (TRAIN_FILE, VALIDATION_FILE):
        if sha256_file(root / name) != manifest['files'][name]['sha256']:
            raise ValueError(f'{name} checksum mismatch')
        spec = dataset_label_spec(root / name)
        require_v2_training(spec)
        if spec.get('label_method') != METHOD or spec.get('flat_band_pct') != FLAT_BAND_PCT:
            raise ValueError(f'{name} semantic labels mismatch')
    return manifest


def validate_remote_file_allowlist(remote_files):
    remote_files = set(remote_files)
    missing = ALLOWED_PUBLISHED_FILES - remote_files
    extra = remote_files - ALLOWED_PUBLISHED_FILES - {'.gitattributes'}
    if missing or extra:
        raise ValueError(f'published repo file allowlist mismatch: missing={sorted(missing)} extra={sorted(extra)}')


def publish_dataset(prepared_dir, repo_id, source_run_id, private_key_b64, public_key_b64):
    from huggingface_hub import HfApi
    from huggingface_hub.errors import RepositoryNotFoundError

    if repo_id != DATASET_REPO_ID:
        raise ValueError(f'publication is restricted to new repo {DATASET_REPO_ID}')
    if int(source_run_id) != APPROVED_SOURCE_RUN_ID:
        raise ValueError(f'V2 dataset publication is restricted to audited source run {APPROVED_SOURCE_RUN_ID}')
    root = Path(prepared_dir)
    manifest = _validate_publish_staging(root)
    if manifest.get('source_label_run_id') != int(source_run_id):
        raise ValueError('prepared source run ID does not match the requested audited source run')
    signature = sign_manifest(manifest, private_key_b64, public_key_b64)
    (root / SIGNATURE_FILE).write_text(json.dumps(signature, sort_keys=True) + '\n', encoding='utf-8')
    token = os.environ.get('HF_TOKEN')
    if not token:
        raise RuntimeError('HF_TOKEN is required for private dataset publication')
    api = HfApi(token=token)
    try:
        info = api.repo_info(repo_id=repo_id, repo_type='dataset')
        if not getattr(info, 'private', False):
            raise ValueError('existing target dataset repo is public; refusing publication')
        if api.list_repo_files(repo_id=repo_id, repo_type='dataset'):
            raise ValueError('existing target V2 dataset repo is nonempty; refusing overwrite')
    except RepositoryNotFoundError:
        api.create_repo(repo_id=repo_id, repo_type='dataset', private=True, exist_ok=False)
    commit = api.upload_folder(repo_id=repo_id, repo_type='dataset', folder_path=str(root),
                               allow_patterns=sorted(ALLOWED_PUBLISHED_FILES),
                               commit_message=f'Publish V2 train/internal validation from run {source_run_id}')
    revision = getattr(commit, 'oid', '')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RuntimeError('HF upload did not return an immutable commit revision')
    info = api.repo_info(repo_id=repo_id, repo_type='dataset', revision=revision)
    if not getattr(info, 'private', False):
        raise RuntimeError('published V2 dataset revision is not private')
    remote = set(api.list_repo_files(repo_id=repo_id, repo_type='dataset', revision=revision))
    validate_remote_file_allowlist(remote)
    return {'repo_id': repo_id, 'private': True, 'revision': revision,
            'source_label_run_id': int(source_run_id), 'files': manifest['files'],
            'manifest_file': MANIFEST_FILE, 'signature_file': SIGNATURE_FILE,
            'signing_public_key_b64': public_key_b64}



def load_pinned_manifest(campaign_manifest_path, revision, token=None):
    from huggingface_hub import HfApi, hf_hub_download

    campaign = json.loads(Path(campaign_manifest_path).read_text(encoding='utf-8'))
    dataset = campaign.get('dataset') or {}
    if dataset.get('repo_id') != DATASET_REPO_ID or not re.fullmatch(r'[0-9a-f]{40}', str(revision or '')):
        raise ValueError('expected the configured private V2 dataset repo and a 40-char immutable revision')
    if dataset.get('revision') != revision:
        raise ValueError('requested revision differs from docs/p2-campaign.json pin')
    token = token or os.environ.get('HF_TOKEN')
    if not token:
        raise RuntimeError('HF_TOKEN is required to read the private V2 dataset')
    api = HfApi(token=token)
    info = api.repo_info(repo_id=DATASET_REPO_ID, repo_type='dataset', revision=revision)
    if not getattr(info, 'private', False):
        raise ValueError('configured V2 dataset repository is not private')
    cache_dir = Path.home() / '.cache' / 'vnstock-ai' / 'p2-v2-manifests' / revision
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = hf_hub_download(repo_id=DATASET_REPO_ID, repo_type='dataset', filename=MANIFEST_FILE,
                                    revision=revision, token=token, local_dir=cache_dir)
    signature_path = hf_hub_download(repo_id=DATASET_REPO_ID, repo_type='dataset', filename=SIGNATURE_FILE,
                                     revision=revision, token=token, local_dir=cache_dir)
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest.get('dataset_id') != DATASET_REPO_ID or manifest.get('label_version') != 2:
        raise ValueError('pinned dataset manifest is not P2a V2')
    if manifest.get('source_label_run_id') != dataset.get('source_label_run_id'):
        raise ValueError('pinned dataset source run does not match docs/p2-campaign.json')
    public_key = dataset.get('signing_public_key_b64')
    if not public_key:
        raise ValueError('campaign manifest has no trusted V2 signing public key')
    verify_manifest_signature(manifest, json.loads(Path(signature_path).read_text(encoding='utf-8')), public_key)
    if dataset.get('label_version') != 2 or dataset.get('label_method') != METHOD or dataset.get('flat_band_pct') != FLAT_BAND_PCT:
        raise ValueError('campaign V2 label contract is invalid')
    for name in (TRAIN_FILE, VALIDATION_FILE):
        pinned = (dataset.get('files') or {}).get(name)
        if isinstance(pinned, dict):
            pinned = pinned.get('sha256')
        signed = manifest.get('files', {}).get(name, {}).get('sha256')
        if not pinned or pinned != signed:
            raise ValueError(f'campaign manifest lacks or disagrees on pinned SHA-256 for {name}')
        expected_md5 = (dataset.get('file_md5') or {}).get(name)
        signed_md5 = manifest.get('files', {}).get(name, {}).get('md5')
        if not expected_md5 or expected_md5 != signed_md5:
            raise ValueError(f'campaign manifest lacks or disagrees on pinned MD5 for {name}')
    return campaign, dataset, manifest, token


def verify_pinned_dataset(campaign_manifest_path, revision, token=None):
    campaign, dataset, manifest, _ = load_pinned_manifest(campaign_manifest_path, revision, token)
    return {'repo_id': dataset['repo_id'], 'revision': revision,
            'files': manifest['files'], 'label_version': manifest['label_version'],
            'label_method': manifest['label_method'], 'flat_band_pct': manifest['flat_band_pct']}


def download_pinned_file(campaign_manifest_path, revision, filename, output_dir, token=None):
    from huggingface_hub import hf_hub_download
    if filename not in (TRAIN_FILE, VALIDATION_FILE):
        raise ValueError('only the pinned V2 train/validation JSONL files may be downloaded')
    _, dataset, manifest, token = load_pinned_manifest(campaign_manifest_path, revision, token)
    expected_value = dataset['files'][filename]
    expected = expected_value.get('sha256') if isinstance(expected_value, dict) else expected_value
    cache_dir = Path.home() / '.cache' / 'vnstock-ai' / 'p2-v2-data' / revision
    cache_dir.mkdir(parents=True, exist_ok=True)
    downloaded = Path(hf_hub_download(repo_id=DATASET_REPO_ID, repo_type='dataset', filename=filename,
                                      revision=revision, token=token, local_dir=cache_dir))
    if sha256_file(downloaded) != expected:
        raise ValueError(f'pinned V2 dataset SHA-256 mismatch: {filename}')
    spec = dataset_label_spec(downloaded); require_v2_training(spec)
    if spec.get('label_method') != METHOD or spec.get('flat_band_pct') != FLAT_BAND_PCT:
        raise ValueError(f'V2 label semantics mismatch: {filename}')
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    target = output / filename
    if downloaded.resolve() != target.resolve():
        shutil.copyfile(downloaded, target)
    return {'path': str(target), 'sha256': expected, 'md5': md5_file(target),
            'revision': revision, 'repo_id': DATASET_REPO_ID, 'manifest': manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--train', required=True); prepare.add_argument('--source-manifest', required=True)
    prepare.add_argument('--source-run-id', type=int, required=True); prepare.add_argument('--output-dir', required=True)
    publish = sub.add_parser('publish')
    publish.add_argument('--prepared-dir', required=True); publish.add_argument('--source-run-id', type=int, required=True)
    publish.add_argument('--repo-id', default=DATASET_REPO_ID); publish.add_argument('--output', required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('--campaign-manifest', default='docs/p2-campaign.json')
    verify.add_argument('--revision', required=True)
    fetch = sub.add_parser('fetch')
    fetch.add_argument('--campaign-manifest', default='docs/p2-campaign.json')
    fetch.add_argument('--revision', required=True)
    fetch.add_argument('--file', choices=(TRAIN_FILE, VALIDATION_FILE), required=True)
    fetch.add_argument('--output-dir', required=True)
    fetch.add_argument('--github-output')
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare_dataset(args.train, args.source_manifest, args.source_run_id, args.output_dir)
    elif args.command == 'publish':
        result = publish_dataset(args.prepared_dir, args.repo_id, args.source_run_id,
                                 os.environ['P2A_V2_DATASET_SIGNING_PRIVATE_KEY_B64'],
                                 os.environ['P2A_V2_DATASET_SIGNING_PUBLIC_KEY_B64'])
    elif args.command == 'verify':
        result = verify_pinned_dataset(args.campaign_manifest, args.revision)
    else:
        result = download_pinned_file(args.campaign_manifest, args.revision, args.file, args.output_dir)
        if args.github_output:
            key = 'TRAIN' if args.file == TRAIN_FILE else 'VALIDATION'
            with Path(args.github_output).open('a', encoding='utf-8') as out:
                out.write(f"{key}_PATH={result['path']}\n")
                out.write(f"{key}_SHA256={result['sha256']}\n")
                out.write(f"{key}_MD5={result['md5']}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
