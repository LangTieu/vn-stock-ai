import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from p2a_colab_assignment_check import assert_no_active_assignments


class ColabAssignmentCheckTests(unittest.TestCase):
    def test_allows_empty_profile(self):
        assert_no_active_assignments([], 'tk2')

    def test_refuses_to_allocate_when_profile_has_assignments(self):
        with self.assertRaisesRegex(RuntimeError,'tk2 has 1 active Colab assignment'):
            assert_no_active_assignments([{'endpoint':'redacted'}], 'tk2')


if __name__=='__main__':unittest.main()
