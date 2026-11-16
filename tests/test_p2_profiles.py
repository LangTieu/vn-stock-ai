import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2_profile_check import verify_profile


class NamedProfileTests(unittest.TestCase):
    def test_profiles_are_named_and_must_be_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                verify_profile('train', 'train_tk4', directory)
        with self.assertRaisesRegex(ValueError, 'unknown Colab credential profile'):
            verify_profile('train', 'eval_tk2', '/tmp')

    def test_profile_identity_is_required_without_reading_a_token_value(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / 'train_tk4' / 'token.json'
            token.parent.mkdir()
            token.write_text('{"fixture": true}')
            token.chmod(0o600)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('P2_TRAIN_TK4_EMAIL', None)
                with self.assertRaisesRegex(RuntimeError, 'expected identity'):
                    verify_profile('train', 'train_tk4', directory)

    def test_insecure_profile_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / 'eval_tk2' / 'token.json'
            token.parent.mkdir()
            token.write_text('{"fixture": true}')
            token.chmod(0o644)
            with self.assertRaisesRegex(PermissionError, 'mode 0600'):
                verify_profile('eval', 'eval_tk2', directory)


if __name__ == '__main__':
    unittest.main()
