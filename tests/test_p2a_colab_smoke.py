import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_colab_smoke import run_smoke, should_fallback_to_tk5


class ColabSmokeFallbackTests(unittest.TestCase):
    def test_tk5_fallback_requires_tk2_assign_503(self):
        error = 'ColabRequestError: POST https://colab.research.google.com/tun/m/assign?x=1 -> 503 Service Unavailable'
        self.assertTrue(should_fallback_to_tk5('tk2', error))
        self.assertFalse(should_fallback_to_tk5('tk2', 'HTTP 401 invalid credentials'))
        self.assertFalse(should_fallback_to_tk5('tk2', 'GET /tun/m/assignments -> 503'))
        self.assertFalse(should_fallback_to_tk5('tk5', error))

    def test_smoke_refuses_v1_and_steps_over_50_before_colab_assignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'v1.jsonl'
            row={'input':'BRIEF: Mã AAA tại 2024-01-01',
                 'metadata':{'kind':'bulk','label':{'future_direction_120':'UP'}}}
            path.write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'refuses non-v2'):
                run_smoke(path, max_steps=2)
            with self.assertRaisesRegex(ValueError,'1 to 50'):
                run_smoke(path, max_steps=51)


if __name__ == '__main__':
    unittest.main()
