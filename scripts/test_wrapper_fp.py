#!/usr/bin/env python3
import glob
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


def _attempt_failed(status, msg, code="http_error"):
    return {"ts": "2026-11-11T13:00:00.000Z", "seq": 1, "level": "error",
            "type": "model.request.attempt_failed", "turn_id": "t",
            "loop_id": "t:1", "request_id": "r",
            "data": {"request_index": 1, "attempt": 1, "max_attempts": 5,
                     "status": status, "error_status": status,
                     "error_code": code, "error_message": msg}}


def _event(ev_type, **kw):
    ev = {"ts": "2026-11-11T13:00:00.000Z", "seq": 1, "level": "info",
          "type": ev_type, "turn_id": "t"}
    ev.update(kw)
    return ev


def test_session_detector():
    """Detector moi: chi attempt_failed 401/402/429 moi doi model.

    Bare mentions "429"/"quota" trong prompt, tool-result, diagnostic,
    hook, compression KHONG trigger; attempt_failed 400/404/408 cung
    khong (ke ca khi message chua URL billing cua LiteLLM).
    """
    with tempfile.TemporaryDirectory() as root:
        config_dir = os.path.join(root, "cfg")
        workdir = "/data/home/parity-test"
        slug = "-" + workdir.strip("/").replace("/", "-")
        seg_dir = os.path.join(config_dir, "logs", "sessions", slug)
        os.makedirs(seg_dir)
        seg = os.path.join(seg_dir, "seg.jsonl")
        offsets = {}

        def append_event(event):
            with open(seg, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")

        # baseline: noi dung co san (ke ca attempt_failed 429 that) khong tinh
        append_event(_attempt_failed(
            429, "Custom provider request failed: 429 litellm.RateLimitError: "
                 "Rate limit reached for meta/muse-ember:free", "rate_limit"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session baseline PASS")

        # prompt append chua "429" -> khong trigger
        append_event(_event("input.prompt.submitted",
                            data={"prompt": "Fix the 429 handling and quota retry logic"}))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session prompt 429 PASS")

        # tool result chua 429, ke ca trong field "message" -> khong trigger
        append_event(_event("tool.execution.finished",
                            message='tool result: {"label":"foreign_room","status":429}'))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session tool-result 429 PASS")

        # diagnostic chua "quota exceeded" + so dong 429 -> khong trigger
        append_event(_event("tool.read.diagnostic",
                            text="line 429: quota exceeded in test fixture"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session diagnostic quota PASS")

        # hook/compression chua 429 -> khong trigger
        append_event(_event("compression.progress",
                            message="compacted 429 messages"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session compression 429 PASS")

        # attempt_failed 400 tool_choice (message co URL billing) -> khong trigger
        append_event(_attempt_failed(
            400, "Custom provider request failed: 400 litellm.BadRequestError: "
                 "The value of 'tool_choice' is not valid. Add credits at "
                 "https://platform.respan.ai/platform/settings/workspace/billing"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session attempt_failed 400 PASS")

        # attempt_failed 404 promotion paused -> khong trigger
        append_event(_attempt_failed(
            404, "Custom provider request failed: 404 litellm.NotFoundError: "
                 "The free promotion has paused due to high demand. Add credits at "
                 "https://platform.respan.ai/platform/settings/workspace/billing"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session attempt_failed 404 PASS")

        # attempt_failed 408 timeout -> khong trigger
        append_event(_attempt_failed(
            408, "Model stream timed out before response headers after 60s",
            "ETIMEDOUT"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        print("session attempt_failed 408 PASS")

        # attempt_failed 429 that -> PHAI trigger
        append_event(_attempt_failed(
            429, "Custom provider request failed: 429 litellm.RateLimitError: "
                 "Rate limit reached for meta/muse-ember:free on requests per "
                 "minute: Limit 10, Used 10", "rate_limit"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is True
        print("session attempt_failed 429 PASS")

        # attempt_failed 401 that -> PHAI trigger
        append_event(_attempt_failed(
            401, "Custom provider request failed: 401 litellm.AuthenticationError: "
                 "Invalid API key", "http_error"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is True
        print("session attempt_failed 401 PASS")

        # attempt_failed 402 that -> PHAI trigger
        append_event(_attempt_failed(
            402, "Custom provider request failed: 402 litellm.BadRequestError: "
                 "Payment required: out of credit", "http_error"))
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is True
        print("session attempt_failed 402 PASS")

        # attempt_failed khong co status nhung error_code rate_limit -> trigger
        ev = _attempt_failed(0, "Rate limit reached")
        del ev["data"]["status"]
        del ev["data"]["error_status"]
        ev["data"]["error_code"] = "rate_limit"
        append_event(ev)
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is True
        print("session attempt_failed no-status rate_limit PASS")

        # attempt_failed khong co status, message khop pattern quota -> trigger
        ev = _attempt_failed(0, "Rate limit reached for model")
        del ev["data"]["status"]
        del ev["data"]["error_status"]
        ev["data"]["error_code"] = "http_error"
        append_event(ev)
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is True
        print("session attempt_failed no-status message PASS")


def test_stdout_detector():
    """Stdout moi: chi dong loi CLI (error marker + pattern quota) moi tinh."""
    with tempfile.TemporaryDirectory() as root:
        stdout_path = os.path.join(root, "qoder.stdout")
        offsets = {}
        with open(stdout_path, "w", encoding="utf-8") as f:
            f.write("prompt says handle 429 and quota retries\n")
        assert not wrapper.stdout_log_has_quota(stdout_path, offsets)
        print("stdout baseline PASS")

        with open(stdout_path, "a", encoding="utf-8") as f:
            f.write("note: retry after 429 in 60s\n")
        assert not wrapper.stdout_log_has_quota(stdout_path, offsets)
        print("stdout bare 429 PASS")

        # dong stdout that trong vu parity (53 byte): loi chung, khong co
        # pattern quota -> khong trigger
        with open(stdout_path, "a", encoding="utf-8") as f:
            f.write("The request could not be completed. Please try again.\n")
        assert not wrapper.stdout_log_has_quota(stdout_path, offsets)
        print("stdout generic failure PASS")

        # dong loi that: RateLimitError + rate limit -> PHAI trigger
        with open(stdout_path, "a", encoding="utf-8") as f:
            f.write("litellm.RateLimitError: Rate limit reached for meta/muse-ember:free\n")
        assert wrapper.stdout_log_has_quota(stdout_path, offsets)
        print("stdout RateLimitError PASS")


def _gold_dir():
    candidates = []
    env = os.environ.get("WRAPPER_GOLD_DIR")
    if env:
        candidates.append(env)
    candidates.append(os.path.expanduser("~/workspace/parity_gold/ffe9c840"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", "parity_gold", "ffe9c840"))
    for c in candidates:
        if c and os.path.isdir(c) and glob.glob(os.path.join(c, "*.jsonl")):
            return c
    return None


def test_gold_replay():
    """Replay session JSONL that vu parity 11/11 (session ffe9c840).

    Cac trigger phut dau (prompt/tool-result/file-content chua "429")
    KHONG duoc ban; cac attempt_failed 429 that PHAI ban (17 event).
    Detector cu ban them 9 event 400/404 (nho chu "billing" trong footer
    LiteLLM) — detector moi khong duoc ban cac event do.
    """
    gold = _gold_dir()
    if not gold:
        print("gold replay SKIPPED (no gold dir; set WRAPPER_GOLD_DIR)")
        return
    files = sorted(glob.glob(os.path.join(gold, "*.jsonl")))
    assert files, "no gold segment files"
    lines = []
    for fp in files:
        with open(fp, errors="replace") as f:
            lines.extend(f.read().splitlines())
    assert len(lines) > 500, "gold fixture too small: %d lines" % len(lines)

    # nhan tung line: new = attempt_failed status 401/402/429;
    # old = QUOTA_RE tren message/error/text (logic cu).
    new_fire_idx = []
    old_fire_idx = []
    for i, line in enumerate(lines):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "model.request.attempt_failed":
            if wrapper._attempt_failed_is_quota(ev):
                new_fire_idx.append(i)
        if any(wrapper.QUOTA_RE.search(t) for t in wrapper._message_texts(ev)):
            old_fire_idx.append(i)
    assert len(new_fire_idx) == 17, (
        "gold: new detector fires %d lines, expected 17 (real 429s)"
        % len(new_fire_idx))
    assert len(old_fire_idx) == 26, (
        "gold: old detector fires %d lines, expected 26" % len(old_fire_idx))
    assert set(new_fire_idx) <= set(old_fire_idx), "new fires must be subset of old"
    assert len(set(old_fire_idx) - set(new_fire_idx)) == 9, (
        "gold: old-only fires should be 9 (the 400/404 events)")
    print("gold line labels PASS (new 17, old 26, old-only 9)")

    # replay qua ham public, theo batch 100 line nhu wrapper quet append
    with tempfile.TemporaryDirectory() as root:
        config_dir = os.path.join(root, "cfg")
        workdir = "/data/home/parity-test"
        slug = "-" + workdir.strip("/").replace("/", "-")
        seg_dir = os.path.join(config_dir, "logs", "sessions", slug)
        os.makedirs(seg_dir)
        seg = os.path.join(seg_dir, "seg.jsonl")
        open(seg, "w").close()
        offsets = {}
        assert wrapper.session_log_has_quota(config_dir, workdir, offsets) is False
        first_true_batch = None
        batch_results = []
        for b in range(0, len(lines), 100):
            batch = lines[b:b + 100]
            with open(seg, "a", encoding="utf-8") as f:
                f.write("\n".join(batch) + "\n")
            got = wrapper.session_log_has_quota(config_dir, workdir, offsets)
            batch_results.append(got)
            expected = any(i in set(new_fire_idx) for i in range(b, min(b + 100, len(lines))))
            assert got is expected, (
                "gold batch %d: got %s, expected %s" % (b // 100, got, expected))
            if got and first_true_batch is None:
                first_true_batch = b // 100
        # 429 that dau tien o line 526 cua segment 1 (global index 525)
        first_fire_line = min(new_fire_idx)
        assert first_fire_line == 525, (
            "gold: first real 429 at global line %d, expected 525" % first_fire_line)
        assert first_true_batch == 5, (
            "gold: first True batch %s, expected 5 (lines 501-600)" % first_true_batch)
        print("gold batch replay PASS (first True batch 5, %d True batches)"
              % sum(1 for r in batch_results if r))


if __name__ == "__main__":
    main()
    test_done_marker()
    test_session_detector()
    test_stdout_detector()
    test_gold_replay()
    sys.exit(0)
