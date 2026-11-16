#!/usr/bin/env python3
"""Read-only guard that refuses P2a work if the selected Colab profile is busy."""
import argparse
import os
import shutil

from p2a_eval_async import stage_profile
from vncolab import Client, authorized_session


def assert_no_active_assignments(assignments, profile):
    if assignments:
        raise RuntimeError(
            f'{profile} has {len(assignments)} active Colab assignment(s); refusing to allocate another runtime')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=('tk2','tk5'),default='tk2')
    args=parser.parse_args()
    home=stage_profile(args.profile)
    try:
        os.environ['VNCOLAB_HOME']=str(home)
        assignments=Client(authorized_session()).list_assignments()
        assert_no_active_assignments(assignments,args.profile)
        print(f'{args.profile}: no active Colab assignments')
    finally:
        shutil.rmtree(home,ignore_errors=True)


if __name__=='__main__':main()
