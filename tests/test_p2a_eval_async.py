import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.p2a_eval_async import build_remote_job


class AsyncEvalBundleTests(unittest.TestCase):
    def test_remote_eval_bundle_includes_numerical_guard_dependency(self):
        source = build_remote_job(50, False, '/tmp/p2-eval')
        self.assertIn("Path('/content/p2a_numerics.py').write_text(", source)
        self.assertIn('def assert_finite_gradients', source)
        self.assertIn("Path('/content/p2a_validation.py').write_text(", source)

    def test_modal_image_bundles_numerical_guard_dependency(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/modal_p2a.py').read_text()
        self.assertIn('"/workspace/p2a_numerics.py"', source)


if __name__ == '__main__':
    unittest.main()
