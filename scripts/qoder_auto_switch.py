#!/usr/bin/env python3
"""Qoder auto-switch: khi model het token/quota thi tu dong chuyen model khac.

Van de (Henrry 08:09 10/11): Qoder lam do roi im lang — do model het token.
Giai phap: wrapper nay chay Qoder, theo doi process + log; neu session chet
hoac log xuat hien loi quota/rate-limit thi resume CUNG session do (UUID)
bang model tiep theo trong danh sach xoay vong, cu the cho toi khi xong viec
hoac het model.

Cach dung (chay TREN MAY co Qoder, vd IB1):
  python3 qoder_auto_switch.py \
    --config-dir /data/home/.qoder-acct1 \
    --workdir /data/home/p3-finish \
    --prompt-file /data/home/p3-finish/BRIEF.md \
    --models "GLM 5.3 Flash (Router),DeepSeek V4.1 Flash (Router),FOSTA Sol (Router),FOSTA Astra (Router),FOSTA Luna (Router),Gonka GLM (Router),Gonka DeepSeek (Router),Gonka MiniMax (Router),IteraCompute Qwen (Router),Cerebras (Router),HY4 (Router),Router Free (BeatAPI + Cerebras),DeepSeek V4.1 Flash (BeatAPI Free),GLM 5.3 Flash (BeatAPI Free),HY4 (BeatAPI Free)" \
    --log-file /data/home/p3-finish/qoder-autoswitch.log

Quy tac:
- Moi model chi dung khi Qoder nhan no (ten day du trong settings.json).
- Resume dung `qodercli -p -r UUID -m MODEL --config-dir DIR` (KHONG them
  --session-id — them vao se fork thay vi resume).
- Moi lan doi model ghi log: thoi gian, model cu -> model moi, ly do.
- Het model ma van chua xong -> thoat 2, bao ro "het model".
- Qoder thoat 0 CHI DUOC TIN khi file --done-file chua chuoi --done-text
  (vd STATE.md chua "ALL DONE"). Thoat 0 ma khong co marker = Qoder dung
  giua chung (gap 10/11: GLM Router dinh 429 1 req/phut, model tra end_turn
  rong, Qoder thoat 0 trong khi chua lam gi) -> resume model tiep theo.
- Khong bao gio ghi gia tri key/token vao log.
- Session UUID tim o ca projects/<slug>/*.jsonl (transcript, dang tin nhat)
  lan sites/sessions/*.json; loi quota quet ca stdout log lan file JSONL
  session moi nhat trong logs/sessions/<slug>/.
- Resume LUON kem prompt tiep tuc (--continue-prompt, mac dinh "Continue the
  task...") — resume khong co prompt thi Qoder ket thuc session ngay (exit 42)
  vi khong co tin nhan moi de tra loi (gap 10/11: 7 lan resume lien tiep
  deu exit 42 sau ~40s).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

DEFAULT_MODELS = [
    "Tuoke 6.1 Sol (Router)",
    "Tuoke 6 Sol (Router)",
    "GLM 5.3 Flash (Router)",
    "DeepSeek V4.1 Flash (Router)",
    "FOSTA Sol (Router)",
    "FOSTA Astra (Router)",
    "FOSTA Luna (Router)",
    "Gonka GLM (Router)",
    "Gonka DeepSeek (Router)",
    "Gonka MiniMax (Router)",
    "IteraCompute Qwen (Router)",
    "Cerebras (Router)",
    "HY4 (Router)",
    "Router Free (BeatAPI + Cerebras)",
    "DeepSeek V4.1 Flash (BeatAPI Free)",
    "GLM 5.3 Flash (BeatAPI Free)",
    "HY4 (BeatAPI Free)",
]

# Pattern nhan biet het token/quota/rate-limit (khong phan biet hoa/thuong).
QUOTA_PATTERNS = [
    r"rate.?limit", r"\b429\b", r"too many requests",
    r"quota", r"exceeded", r"insufficient", r"out of credit",
    r"no credit", r"credit limit", r"\b402\b", r"payment required",
    r"token limit", r"context limit", r"max_tokens",
    r"model not available", r"not available", r"service unavailable",
    r"\b401\b", r"unauthorized", r"authentication",
    r"insufficient_quota", r"billing", r"exhausted",
]
QUOTA_RE = re.compile("|".join(QUOTA_PATTERNS), re.IGNORECASE)


def log(msg, logf):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(logf, "a") as f:
        f.write(line + "\n")


def newest_session_uuid(config_dir, since_ts, workdir=None):
    """Tim session UUID moi nhat duoc tao sau since_ts.

    Chi quet transcript cua CHINH workdir nay (projects/<slug>/) — quet het
    projects/ se vot nham session cua task khac chay song song (gap 10/11:
    2 wrapper cung config dir, UUID cua task kia bi nham la cua minh).
    Fallback: sites/sessions/*.json (khong phan biet workdir — chi dung khi
    khong tim thay transcript).
    """
    best = None
    best_mtime = since_ts
    if workdir:
        slug = "-" + workdir.strip("/").replace("/", "-")
        sp = os.path.join(config_dir, "projects", slug)
        if os.path.isdir(sp):
            for fn in os.listdir(sp):
                if not fn.endswith(".jsonl"):
                    continue
                p = os.path.join(sp, fn)
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    continue
                if mt > best_mtime:
                    best_mtime = mt
                    best = fn[:-6]
            if best:
                return best
    sdir = os.path.join(config_dir, "sites", "sessions")
    if not os.path.isdir(sdir):
        return best
    for fn in os.listdir(sdir):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(sdir, fn)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt > best_mtime:
            best_mtime = mt
            best = fn[:-5]
    return best


def newest_session_log(config_dir, workdir):
    """File JSONL log moi nhat cua session trong logs/sessions/<slug>/."""
    slug = "-" + workdir.strip("/").replace("/", "-")
    base = os.path.join(config_dir, "logs", "sessions", slug)
    best = None
    best_mtime = 0
    if not os.path.isdir(base):
        return None
    for root, _dirs, files in os.walk(base):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            p = os.path.join(root, fn)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if mt > best_mtime:
                best_mtime = mt
                best = p
    return best


def session_log_has_quota(config_dir, workdir):
    """True neu file log session moi nhat chua pattern quota/rate-limit."""
    p = newest_session_log(config_dir, workdir)
    if not p:
        return False
    try:
        size = os.path.getsize(p)
        with open(p, "r", errors="replace") as f:
            f.seek(max(0, size - 500000))
            return bool(QUOTA_RE.search(f.read()))
    except OSError:
        return False


def done_marker_ok(done_file, done_text):
    """True neu done_file ton tai va chua done_text."""
    if not done_file or not done_text:
        return True  # khong yeu cau marker -> tin exit 0 nhu cu
    try:
        with open(done_file, "r", errors="replace") as f:
            return done_text in f.read()
    except OSError:
        return False


def run_qoder(cmd, log_path):
    """Chay Qoder, output append vao log_path. Tra ve Popen."""
    lf = open(log_path, "ab")
    proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                            start_new_session=True)
    return proc, lf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-dir", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS),
                    help="comma-separated model display names, in order")
    ap.add_argument("--log-file", required=True)
    ap.add_argument("--check-interval", type=int, default=30)
    ap.add_argument("--stall-minutes", type=int, default=10,
                    help="no log growth + quota pattern -> coi nhu ket")
    ap.add_argument("--max-switches", type=int, default=0,
                    help="0 = xoay het danh sach 1 vong")
    ap.add_argument("--done-file", default="",
                    help="file phai chua done-text thi exit 0 moi tinh la xong")
    ap.add_argument("--done-text", default="",
                    help="chuoi phai co trong done-file (vd 'ALL DONE')")
    ap.add_argument("--resume-uuid", default="",
                    help="resume session cu nay thay vi chay moi")
    ap.add_argument("--continue-prompt", default="",
                    help="prompt gui kem khi resume (vd 'Continue the task...')")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("ERR: danh sach models rong")
        return 2
    max_switches = args.max_switches or (len(models) - 1)
    prompt = open(args.prompt_file, encoding="utf-8").read().strip()
    if not prompt:
        print("ERR: prompt file rong")
        return 2

    logf = args.log_file
    os.makedirs(os.path.dirname(logf) or ".", exist_ok=True)
    log("autoswitch bat dau: %d model, workdir=%s" % (len(models), args.workdir), logf)

    switches = 0
    idx = 0
    session_uuid = None
    proc = None
    log_handle = None
    log_size = 0
    log_mtime = 0
    stall_since = None

    def launch(model, resume_uuid=None):
        nonlocal session_uuid
        before = time.time()
        if resume_uuid:
            # Resume PHAI kem prompt tiep tuc — resume khong co prompt thi
            # Qoder khong co gi de lam, ket thuc session ngay (exit 42).
            cont = args.continue_prompt or (
                "Continue the task from where the previous session stopped. "
                "Check STATE.md and the current state of the files, then "
                "continue with the next unfinished step. When all steps are "
                "done, write 'ALL DONE' in STATE.md.")
            cmd = ["qodercli", "-p", "-r", resume_uuid, "-m", model,
                   "--config-dir", args.config_dir,
                   "-w", args.workdir,
                   "--permission-mode", "bypass_permissions", cont]
        else:
            cmd = ["qodercli", "-p", "-m", model,
                   "--config-dir", args.config_dir,
                   "-w", args.workdir,
                   "--permission-mode", "bypass_permissions", prompt]
        log("launch model '%s'%s" % (model, " (resume %s)" % resume_uuid if resume_uuid else " (moi)"), logf)
        p, lf = run_qoder(cmd, logf)
        # doi chut de session file xuat hien, roi ghi UUID (chi quet
        # transcript cua workdir nay — tranh vot nham session task khac)
        time.sleep(10)
        uuid = newest_session_uuid(args.config_dir, before, args.workdir)
        if uuid:
            session_uuid = uuid
            log("session UUID: %s" % uuid, logf)
        else:
            log("WARN: khong tim thay session UUID moi", logf)
        return p, lf

    proc, log_handle = launch(models[0], resume_uuid=args.resume_uuid or None)
    if args.resume_uuid:
        session_uuid = args.resume_uuid
    log_size = os.path.getsize(logf) if os.path.exists(logf) else 0
    log_mtime = time.time()

    while True:
        time.sleep(args.check_interval)
        rc = proc.poll()
        # quet ca stdout log lan file log session cua Qoder tim quota pattern
        # (loi 429 nam trong session JSONL, khong hien ra stdout)
        if rc is None and session_log_has_quota(args.config_dir, args.workdir):
            log("phat hien loi quota/rate-limit trong session log Qoder", logf)
            proc.kill()
            proc.wait(timeout=30)
            rc = -99
        # doc phan log moi de tim quota pattern + cap nhat stall
        try:
            cur_size = os.path.getsize(logf)
        except OSError:
            cur_size = log_size
        if cur_size > log_size:
            log_size = cur_size
            log_mtime = time.time()
            stall_since = None
            # quet doan log moi tim quota pattern
            try:
                with open(logf, "r", errors="replace") as f:
                    f.seek(max(0, cur_size - 200000))
                    tail = f.read()
                if QUOTA_RE.search(tail):
                    log("phat hien loi quota/rate-limit trong log", logf)
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait(timeout=30)
                    rc = -99  # danh dau chet do quota
            except OSError:
                pass
        else:
            # log khong tang — kiem tra stall
            if stall_since is None:
                stall_since = time.time()
            elif time.time() - stall_since > args.stall_minutes * 60:
                try:
                    with open(logf, "r", errors="replace") as f:
                        f.seek(max(0, cur_size - 200000))
                        tail = f.read()
                    if QUOTA_RE.search(tail):
                        log("stall %d phut + quota pattern -> ket" % args.stall_minutes, logf)
                        if proc.poll() is None:
                            proc.kill()
                            proc.wait(timeout=30)
                        rc = -99
                    else:
                        log("stall %d phut nhung khong co quota pattern — doi tiep" % args.stall_minutes, logf)
                        stall_since = time.time()
                except OSError:
                    pass

        if rc is None:
            continue  # van chay tot
        # process da dung (0 = xong, khac 0 / -99 = loi)
        try:
            log_handle.close()
        except Exception:
            pass
        if rc == 0:
            if done_marker_ok(args.done_file, args.done_text):
                log("Qoder thoat 0 + marker '%s' co trong %s — XONG VIEC (model '%s')"
                    % (args.done_text, args.done_file, models[idx]), logf)
                return 0
            log("Qoder thoat 0 NHUNG khong co marker '%s' trong %s — coi nhu "
                "chua xong, doi model" % (args.done_text, args.done_file), logf)
            rc = -98  # dung giua chung
        # loi: doi model
        if switches >= max_switches:
            log("HET MODEL (da doi %d lan) — dung, bao loi" % switches, logf)
            return 2
        reason = {-99: "quota/rate-limit",
                  -98: "thoat 0 nhung chua xong (thieu done marker)"}.get(
                      rc, "exit code %s" % rc)
        idx = (idx + 1) % len(models)
        switches += 1
        log("doi model %d/%d: '%s' -> '%s' (ly do: %s)"
            % (switches, max_switches, models[idx - 1] if idx > 0 else models[-1],
               models[idx], reason), logf)
        if session_uuid:
            proc, log_handle = launch(models[idx], resume_uuid=session_uuid)
        else:
            # khong co UUID -> chay moi voi cung prompt
            log("WARN: khong co session UUID, chay moi voi model '%s'" % models[idx], logf)
            proc, log_handle = launch(models[idx])
        log_size = os.path.getsize(logf) if os.path.exists(logf) else 0
        log_mtime = time.time()
        stall_since = None


if __name__ == "__main__":
    raise SystemExit(main())
