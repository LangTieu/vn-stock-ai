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


def test_done_marker():
    cases = [
        ("guard sentence", "Do not mark ALL DONE until all 1,564 tickers have been attempted and outputs are verified.\n", "ALL DONE", False),
        ("bare marker", "Status: complete\nALL DONE\n", "ALL DONE", True),
        ("surrounding whitespace", "  ALL DONE  \n", "ALL DONE", True),
        ("no marker", "Status: IN PROGRESS\n", "ALL DONE", False),
        ("marker argument whitespace", "ALL DONE\n", "  ALL DONE  ", True),
    ]
    with tempfile.TemporaryDirectory() as root:
        done_path = os.path.join(root, "done.txt")
        for name, content, done_text, expected in cases:
            with open(done_path, "w", encoding="utf-8") as f:
                f.write(content)
            assert wrapper.done_marker_ok(done_path, done_text) is expected, name
            print(f"done marker {name} PASS")
        missing_path = os.path.join(root, "missing.txt")
        assert wrapper.done_marker_ok(missing_path, "ALL DONE") is False
        print("done marker missing file PASS")
        assert wrapper.done_marker_ok(None, "ALL DONE") is True
        assert wrapper.done_marker_ok(missing_path, "") is True
        print("done marker optional arguments PASS")


if __name__ == "__main__":
    main()
    test_done_marker()
    sys.exit(0)
