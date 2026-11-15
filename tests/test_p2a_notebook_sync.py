import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TrainingNotebookSyncTests(unittest.TestCase):
    def test_embedded_scripts_match_canonical_sources(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        expected = {
            '/content/p2a_train.py': 'scripts/p2a_train.py',
            '/content/p2a_numerics.py': 'scripts/p2a_numerics.py',
            '/content/p2a_validation.py': 'scripts/p2a_validation.py',
            '/content/p2a_eval.py': 'scripts/p2a_eval.py',
        }
        embedded = {}
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                        or node.func.attr != 'write_text' or not node.args):
                    continue
                try:
                    target = ast.literal_eval(node.func.value.args[0])
                    content = ast.literal_eval(node.args[0])
                except (IndexError, TypeError, ValueError):
                    continue
                if target in expected:
                    embedded[target] = content
        for target, path in expected.items():
            with self.subTest(target=target):
                self.assertEqual(embedded.get(target), (ROOT / path).read_text())

    def test_full_mode_marks_evaluation_as_full_holdout(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        eval_cell = ''.join(notebook['cells'][9]['source'])
        self.assertIn("['--full-holdout'] if MODE == 'full'", eval_cell)

    def test_smoke_eval_limit_is_shared_and_emits_compact_ablation_metrics(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        eval_cell = ''.join(notebook['cells'][9]['source'])
        self.assertIn("os.environ.get('P2A_EVAL_LIMIT', '20')", eval_cell)
        self.assertIn("P2A_ABLATION_EVAL ", eval_cell)

    def test_colab_workflow_has_controlled_ablation_gate_and_caps_trials(self):
        workflow = (ROOT / '.github/workflows/run-colab.yml').read_text()
        self.assertEqual(workflow.count('p2a-v2-ablation:'), 1)
        self.assertIn('p2a_ablation_steps', workflow)
        self.assertIn('max 50; default 12', workflow)
        self.assertIn('source_run_id', workflow)

    def test_notebook_exposes_verified_dataset_hashes_and_ablation_settings(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        settings = ''.join(notebook['cells'][1]['source'])
        train = ''.join(notebook['cells'][7]['source'])
        for name in ('TRAIN_MD5', 'HOLDOUT_MD5'):
            self.assertIn(name, settings)
            self.assertIn(name, train)
        for name in ('--lora-r', '--lora-alpha', '--lora-dropout', '--learning-rate',
                     '--gradient-accumulation-steps', '--target-modules', '--seed'):
            self.assertIn(name, train)
        self.assertIn('SEED = os.environ.get("SEED", "42")', settings)


if __name__ == '__main__':
    unittest.main()
