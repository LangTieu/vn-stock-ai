import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_v2_dataset import (ALLOWED_PUBLISHED_FILES, APPROVED_SOURCE_RUN_ID,
                            DATASET_REPO_ID, MANIFEST_FILE,
                            TRAIN_FILE, VALIDATION_FILE, prepare_dataset,
                            sha256_file, sign_manifest, verify_manifest_signature,
                            _validate_publish_staging)


def make_row(ticker, day, direction, endpoint, version=2, status='labeled'):
    payload={'ticker':ticker,'as_of':day,'source':{'ohlcv':'daily_HOSE'}}
    return {'input':f'BRIEF: Mã {ticker} tại {day}\nVERIFIED_DATA\n'+json.dumps(payload),
            'metadata':{'kind':'bulk','exchange':'HOSE','market_as_of':day,
              'p2a_label_version':version,'p2a_label_status':status,
              'label':{'future_direction_120':direction,'method':'adjusted_total_return_close; 120 exchange sessions after as_of',
                'future_outcomes':{'120':{'endpoint_date':endpoint,'flat_band_pct':2.0}}}}}


class V2DatasetTests(unittest.TestCase):
    def test_prepare_builds_full_leakage_separated_v2_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source.jsonl'; rows=[]
            for i in range(40):
                day=date(2020,1,1)+timedelta(days=i)
                rows.append(make_row(f'TU{i}',day.isoformat(),'UP',(day+timedelta(days=120)).isoformat()))
                rows.append(make_row(f'TD{i}',day.isoformat(),'DOWN',(day+timedelta(days=120)).isoformat()))
            for i in range(20):
                day=date(2024,1,2)+timedelta(days=i)
                rows.append(make_row(f'VU{i}',day.isoformat(),'UP',(day+timedelta(days=120)).isoformat()))
                rows.append(make_row(f'VD{i}',day.isoformat(),'DOWN',(day+timedelta(days=120)).isoformat()))
            rows.append(make_row('FLAT','2020-01-02','FLAT','2020-05-01'))
            rows.append(make_row('CENS','2020-01-03',None,None,status='censored'))
            source.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            source_manifest=root/'source.manifest.json'
            source_manifest.write_text(json.dumps({
                'label_version': 2,
                'output_sha256': sha256_file(source),
                'method': 'adjusted_total_return_close; 120 exchange sessions after as_of',
                'flat_band_pct': 2.0,
            }))
            with self.assertRaisesRegex(ValueError, str(APPROVED_SOURCE_RUN_ID)):
                prepare_dataset(source,source_manifest,APPROVED_SOURCE_RUN_ID + 1,root/'wrong-source')
            out=root/'publish'; manifest=prepare_dataset(source,source_manifest,43691791091,out)
            self.assertEqual(manifest['dataset_id'],DATASET_REPO_ID)
            self.assertEqual(manifest['label_version'],2)
            self.assertFalse(manifest['external_holdout_included'])
            self.assertFalse(manifest['raw_adjusted_price_table_included'])
            self.assertEqual(manifest['files']['train-v2.jsonl']['rows'],80)
            self.assertEqual(manifest['files']['validation-v2.jsonl']['rows'],40)
            self.assertLess(manifest['split']['train_target_endpoint_max'],
                            manifest['split']['validation_as_of_min'])
            self.assertEqual(sha256_file(out/'train-v2.jsonl'),manifest['files']['train-v2.jsonl']['sha256'])
            self.assertEqual(sha256_file(out/'validation-v2.jsonl'),manifest['files']['validation-v2.jsonl']['sha256'])
            self.assertEqual({p.name for p in out.iterdir()},
                             {'train-v2.jsonl','validation-v2.jsonl','v2-dataset-manifest.json'})
            (out/'adjusted_prices.csv').write_text('private raw prices')
            with self.assertRaisesRegex(ValueError, 'contain only'):
                _validate_publish_staging(out)

    @unittest.skipUnless(__import__('importlib').util.find_spec('cryptography'), 'cryptography optional in local test env')
    def test_ed25519_signature_detects_manifest_mutation(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        import base64
        private=Ed25519PrivateKey.generate()
        seed=private.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,
                                   serialization.NoEncryption())
        public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        seed64=base64.b64encode(seed).decode(); public64=base64.b64encode(public).decode()
        manifest={'dataset_id':DATASET_REPO_ID,'label_version':2}
        sig=sign_manifest(manifest,seed64,public64)
        self.assertTrue(verify_manifest_signature(manifest,sig,public64))
        with self.assertRaisesRegex(ValueError,'signature verification failed'):
            verify_manifest_signature({**manifest,'label_version':1},sig,public64)

    def test_publisher_allowlist_excludes_raw_price_tables(self):
        source=Path(__file__).resolve().parents[1]/'scripts/p2a_v2_dataset.py'
        text=source.read_text()
        self.assertEqual(ALLOWED_PUBLISHED_FILES,
                         {TRAIN_FILE, VALIDATION_FILE, MANIFEST_FILE, 'v2-dataset-manifest.sig'})
        self.assertIn("'raw_adjusted_price_table_included': False",text)

    def test_fetch_copies_downloaded_file_to_a_different_output_directory(self):
        from p2a_v2_dataset import download_pinned_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cached = root / 'cache' / TRAIN_FILE
            cached.parent.mkdir()
            payload = b'{"metadata":{"kind":"bulk","p2a_label_version":2}}\n'
            cached.write_bytes(payload)
            output = root / 'colab-input'
            revision = 'a' * 40
            digest = hashlib.sha256(payload).hexdigest()
            dataset = {'files': {TRAIN_FILE: {'sha256': digest}}}
            manifest = {'files': {TRAIN_FILE: {'sha256': digest}}}
            hf_module = SimpleNamespace(
                hf_hub_download=lambda **kwargs: str(cached))
            with patch.dict(sys.modules, {'huggingface_hub': hf_module}), \
                    patch('p2a_v2_dataset.Path.home', return_value=root / 'home'), \
                    patch('p2a_v2_dataset.load_pinned_manifest',
                          return_value=({}, dataset, manifest, 'test-token')), \
                    patch('p2a_v2_dataset.dataset_label_spec', return_value={
                        'label_version': 2,
                        'label_method': 'adjusted_total_return_close; 120 exchange sessions after as_of',
                        'flat_band_pct': 2.0,
                    }), \
                    patch('p2a_v2_dataset.require_v2_training'):
                result = download_pinned_file('campaign.json', revision, TRAIN_FILE, output)

            target = output / TRAIN_FILE
            self.assertNotEqual(cached.resolve(), target.resolve())
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(result['path'], str(target))
            self.assertEqual(result['sha256'], digest)
            self.assertEqual(result['manifest'], manifest)


if __name__=='__main__': unittest.main()
