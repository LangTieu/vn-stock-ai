#!/usr/bin/env python3
import json
import os
import sys
import tempfile

import qoder_auto_switch as wrapper


def main():
    first = "qua" + "ta"
    second = "ex" + "ceeded"
    with tempfile.TemporaryDirectory() as root:
        stdout_path = os.path.join(root, "qoder.stdout")
        wrapper_log_path = os.path.join(root, "wrapper.log")
        session_path = os.path.join(root, "session.jsonl")
        offsets = {}

        with open(stdout_path, "w", encoding="utf-8") as f:
            f.write("Initial brief mentions " + first + " and " + second + " only.\n")
        with open(wrapper_log_path, "w", encoding="utf-8") as f:
            f.write("wrapper detected " + first + " in its own diagnostic line\n")

        assert not wrapper.stdout_log_has_quota(stdout_path, offsets)
        assert not wrapper.stdout_log_has_quota(wrapper_log_path, offsets)
        print("a PASS")

        with open(stdout_path, "a", encoding="utf-8") as f:
            f.write("ERROR: request " + second + " the service limit\n")
        assert wrapper.stdout_log_has_quota(stdout_path, offsets)
        print("b PASS")

        with open(wrapper_log_path, "a", encoding="utf-8") as f:
            f.write("wrapper detected " + second + " in its own follow-up line\n")
        assert not wrapper.stdout_log_has_quota(stdout_path, offsets)
        print("c PASS")



if __name__ == "__main__":
    main()
    sys.exit(0)
