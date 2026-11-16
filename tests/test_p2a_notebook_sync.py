import ast
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_full_mode_requires_separate_validation_approval(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        eval_cell = ''.join(notebook['cells'][9]['source'])
        self.assertIn("P2A_FULL_VALIDATION_APPROVAL_REF", eval_cell)
        self.assertIn("'--full-validation-approval-ref'", eval_cell)

    def test_smoke_eval_limit_is_shared_and_emits_compact_ablation_metrics(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        eval_cell = ''.join(notebook['cells'][9]['source'])
        self.assertIn("os.environ.get('P2A_EVAL_LIMIT', '20')", eval_cell)
        self.assertIn("P2A_ABLATION_EVAL ", eval_cell)
        self.assertIn("['--limit', str(int(os.environ.get('P2A_EVAL_LIMIT', '20')))]", eval_cell)

    def test_eval_cell_imports_json_for_metrics_load(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        eval_cell = ''.join(notebook['cells'][9]['source'])
        self.assertTrue(eval_cell.startswith('import json\n'))
        self.assertIn('json.loads(Path(metrics_path).read_text())', eval_cell)

    def test_smoke_mode_honors_requested_step_limit_with_two_step_default(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        train_cell = ''.join(notebook['cells'][7]['source'])
        self.assertIn("'--max-steps', MAX_STEPS or '2'", train_cell)

    def test_colab_workflow_has_controlled_ablation_gate_and_caps_trials(self):
        workflow = (ROOT / '.github/workflows/run-colab.yml').read_text()
        self.assertEqual(workflow.count('p2a-v2-ablation:'), 1)
        self.assertIn('p2a_ablation_steps', workflow)
        self.assertIn('max 50; default 12', workflow)
        self.assertIn('source_run_id', workflow)
        self.assertIn('"$HOME/vncolab-venv/bin/python" scripts/p2a_colab_assignment_check.py --profile tk2', workflow)

    def test_campaign_completion_signal_handles_github_token_event_suppression(self):
        workflow = (ROOT / '.github/workflows/run-colab.yml').read_text()
        coordinator = (ROOT / '.github/workflows/p2-campaign.yml').read_text()
        self.assertIn('Signal P2 coordinator after run completion', workflow)
        self.assertIn('github.rest.repos.createDispatchEvent', workflow)
        self.assertIn('contents: write', workflow)
        self.assertIn('repository_dispatch:', coordinator)
        self.assertIn('p2-campaign-run-completed', coordinator)
        self.assertIn('gh run view "$WORKFLOW_RUN_ID"', coordinator)

    def test_coordinator_replay_installs_checkpoint_dependency_and_sets_git_identity(self):
        workflow = (ROOT / '.github/workflows/p2-campaign.yml').read_text()
        identity = 'git config user.name "github-actions[bot]"'
        source_record = 'record_result=$(python3 scripts/p2_campaign_ledger.py record'
        self.assertLess(workflow.index(identity), workflow.index(source_record))
        self.assertIn("source_conclusion=$(jq -r '.conclusion // \"\"' /tmp/p2-campaign-event.json)",
                      workflow)
        self.assertIn('[ "$source_conclusion" = success ]', workflow)
        self.assertIn('python3 -m pip install --quiet "huggingface_hub==0.30.2"', workflow)
        self.assertIn("(.run_id|tostring) == $run_id and .head_sha == $head_sha", workflow)

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

    def test_v2_setup_and_training_cells_execute_with_pinned_environment(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        cells = [''.join(notebook['cells'][index]['source']) for index in (1, 3, 7)]
        train_sha = 'a' * 64
        holdout_sha = 'b' * 64
        revision = '4e00aefe775509fdd69fe1e70c6232468d4041d8'
        env = {
            'MODE': 'full',
            'TRAIN_URL': f'hf://Jerlob/vn-stock-ai-p2a-v2@{revision}/train-v2.jsonl',
            'HOLDOUT_URL': f'hf://Jerlob/vn-stock-ai-p2a-v2@{revision}/validation-v2.jsonl',
            'TRAIN_MD5': 'c' * 32,
            'HOLDOUT_MD5': 'd' * 32,
            'P2A_TRAIN_SHA256': train_sha,
            'P2A_HOLDOUT_SHA256': holdout_sha,
            'P2A_LABEL_VERSION': '2',
            'P2A_V2_DATASET_REPO': 'Jerlob/vn-stock-ai-p2a-v2',
            'P2A_V2_DATASET_REVISION': revision,
            'OUTPUT_DIR': '/tmp/p2a-notebook-test',
            'MAX_STEPS': '50',
            'SAVE_STEPS': '25',
        }
        namespace = {}
        fake_train = types.ModuleType('p2a_train')
        fake_train.dataset_path = lambda _url, target, _md5: target
        class CompletedProcess:
            stdout = ()
            def wait(self):
                return 0
        with patch.dict(os.environ, env, clear=True), \
                patch.dict(sys.modules, {'p2a_train': fake_train}), \
                patch.object(subprocess, 'Popen', return_value=CompletedProcess()) as popen:
            exec(cells[0], namespace)
            exec(cells[1], namespace)
            exec(cells[2], namespace)
        self.assertEqual(namespace['TRAIN_SHA256'], train_sha)
        self.assertEqual(namespace['HOLDOUT_SHA256'], holdout_sha)
        self.assertIn(train_sha, popen.call_args.args[0])


    def test_training_notebook_has_no_legacy_dataset_defaults(self):
        notebook = json.loads((ROOT / 'notebooks/p2a_train.ipynb').read_text())
        settings = ''.join(notebook['cells'][1]['source'])
        setup = ''.join(notebook['cells'][3]['source'])
        self.assertIn('TRAIN_URL = os.environ.get("TRAIN_URL", "")', settings)
        self.assertIn('HOLDOUT_URL = os.environ.get("HOLDOUT_URL", "")', settings)
        self.assertNotIn('Jerlob/vn-stock-ai-p1', settings)
        self.assertIn('P2A_LABEL_VERSION != "2"', setup)
        self.assertIn('legacy P1 defaults are disabled', setup)
        self.assertIn("'--train-sha256', TRAIN_SHA256", ''.join(notebook['cells'][7]['source']))
        self.assertIn("'--holdout-sha256', HOLDOUT_SHA256", ''.join(notebook['cells'][9]['source']))
        self.assertNotIn('HOLDOUT_MD5 as DEFAULT_HOLDOUT_MD5', ''.join(notebook['cells'][7]['source']))

    def test_full_colab_job_verifies_pinned_private_v2_revision_before_runtime(self):
        workflow = (ROOT / '.github/workflows/run-colab.yml').read_text()
        self.assertIn('Verify pinned private V2 dataset before Colab assignment', workflow)
        self.assertIn('p2a_v2_dataset.py verify', workflow)
        self.assertIn('hf://Jerlob/vn-stock-ai-p2a-v2@', workflow)
        self.assertIn('SKIP_EVAL=1', workflow)


if __name__ == '__main__':
    unittest.main()
