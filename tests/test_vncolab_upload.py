import base64
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from vncolab import upload_file_code


class VncolabPrivateUploadTests(unittest.TestCase):
    def test_file_transfer_chunks_reconstruct_exact_content(self):
        data = bytes(range(256)) * 11
        snippets = list(upload_file_code(data, '/content/p2a-v2-smoke.jsonl', chunk_bytes=1024))
        pieces = []
        for snippet in snippets:
            match = re.search(r"b64decode\('([^']*)', validate=True\)", snippet)
            self.assertIsNotNone(match)
            pieces.append(base64.b64decode(match.group(1), validate=True))
        self.assertEqual(b''.join(pieces), data)
        self.assertIn("open('wb')", snippets[0])
        self.assertIn("open('ab')", snippets[1])
        self.assertIn("Path('/content/p2a-v2-smoke.jsonl')", snippets[0])

    def test_transfer_only_allows_colab_content_paths(self):
        with self.assertRaisesRegex(ValueError, 'restricted to /content'):
            list(upload_file_code(b'x', '/tmp/not-colab.json'))
        with self.assertRaisesRegex(ValueError, 'restricted to /content'):
            list(upload_file_code(b'x', '/content/../tmp/file'))


if __name__ == '__main__':
    unittest.main()
