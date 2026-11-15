import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_check_colab_overlap import other_active_runs


class ColabOverlapTests(unittest.TestCase):
    def test_ignores_current_run_but_blocks_other_active_runs(self):
        runs=[{'id':10,'status':'in_progress'}, {'id':11,'status':'queued'},
              {'id':12,'status':'completed'}]
        self.assertEqual(other_active_runs(runs,10),[runs[1]])
        self.assertEqual(other_active_runs(runs,11),[runs[0]])
        self.assertEqual(other_active_runs(runs,12),[runs[0],runs[1]])


if __name__=='__main__':
    unittest.main()
