#!/usr/bin/env python3
"""Safe P2 training operations: inspect/backup checkpoints, rotate Colab auth, resume."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = "LangTieu/vn-stock-ai"
CHECKPOINT_REPO = "Jerlob/vn-stock-ai-p2a-checkpoints"
WORKFLOW = ".github/workflows/run-colab.yml"
REQUIRED = {"optimizer.pt", "scheduler.pt", "trainer_state.json", "rng_state.pth",
            "adapter_config.json"}
ADAPTER_WEIGHTS = {"adapter_model.safetensors", "adapter_model.bin"}
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.profile",
          "https://www.googleapis.com/auth/userinfo.email",
          "https://www.googleapis.com/auth/cloud-platform",
          "https://www.googleapis.com/auth/colaboratory",
          "https://www.googleapis.com/auth/drive.file"]


def checkpoint_steps(files):
    contents = {}
    for name in files:
        match = re.fullmatch(r"checkpoints/(checkpoint-(\d+))/(.+)", name)
        if match:
            contents.setdefault((int(match.group(2)), match.group(1)), set()).add(match.group(3))
    complete = []
    for (step, name), paths in contents.items():
        if REQUIRED <= paths and paths & ADAPTER_WEIGHTS:
            complete.append((step, name))
    return sorted(complete)


def hf_api():
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN is required for Hugging Face checkpoint operations")
    from huggingface_hub import HfApi
    return HfApi(token=token)


def latest_checkpoint(api, repo_id=CHECKPOINT_REPO):
    complete = checkpoint_steps(api.list_repo_files(repo_id=repo_id, repo_type="model"))
    if not complete:
        raise RuntimeError(f"No complete resume checkpoint in {repo_id}")
    return complete[-1][1]


def validate_local_checkpoint(root):
    root = Path(root)
    missing = sorted(name for name in REQUIRED if not (root / name).is_file())
    if not any((root / name).is_file() for name in ADAPTER_WEIGHTS):
        missing.append("adapter_model.(safetensors|bin)")
    if missing:
        raise RuntimeError(f"Incomplete checkpoint {root}: missing {', '.join(missing)}")
    return root


def cmd_latest(args):
    name = latest_checkpoint(hf_api(), args.repo)
    print(name)


def cmd_backup_hf(args):
    from huggingface_hub import snapshot_download
    api = hf_api()
    name = latest_checkpoint(api, args.repo)
    remote = f"checkpoints/{name}"
    snapshot = Path(snapshot_download(repo_id=args.repo, repo_type="model",
                                     allow_patterns=[f"{remote}/*"], token=os.environ["HF_TOKEN"]))
    source = validate_local_checkpoint(snapshot / remote)
    destination = Path(args.destination).expanduser() / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        validate_local_checkpoint(destination)
        print(f"BACKUP_EXISTS {destination}")
        return
    temp = destination.with_name(destination.name + f".tmp-{os.getpid()}")
    shutil.copytree(source, temp)
    validate_local_checkpoint(temp)
    os.replace(temp, destination)
    print(f"CHECKPOINT_BACKED_UP {remote} destination={destination}")


def cmd_backup_run(args):
    destination = Path(args.destination).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "run", "download", str(args.run_id), "-R", REPO,
                    "-n", "p2a-output", "-D", str(destination)], check=True)
    archives = list(destination.glob("p2a-output-*.zip"))
    if not archives:
        raise RuntimeError(f"No p2a-output archive in run {args.run_id} artifacts")
    import zipfile
    extracted = destination / "extracted"
    extracted.mkdir(exist_ok=True)
    for archive in archives:
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                target = (extracted / member.filename).resolve()
                if extracted.resolve() not in target.parents and target != extracted.resolve():
                    raise RuntimeError("Unsafe path in downloaded workflow artifact")
            zipped.extractall(extracted)
    checkpoints = sorted(extracted.glob("**/checkpoint-*"),
                         key=lambda p: int(p.name.rsplit("-", 1)[1]) if p.name.rsplit("-", 1)[-1].isdigit() else -1)
    valid = []
    for checkpoint in checkpoints:
        try:
            validate_local_checkpoint(checkpoint)
            valid.append(checkpoint)
        except RuntimeError:
            continue
    if not valid:
        raise RuntimeError(f"No complete checkpoints in run {args.run_id} artifact")
    latest = valid[-1]
    print(f"RUN_CHECKPOINT_BACKED_UP run={args.run_id} checkpoint={latest}")


def verify_account_token(path, expected_email):
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    path = Path(path)
    info = json.loads(path.read_text())
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        if not creds.expired or not creds.refresh_token:
            raise RuntimeError("candidate Colab credential is invalid and cannot refresh")
        creds.refresh(Request())
    response = AuthorizedSession(creds).get(
        "https://www.googleapis.com/oauth2/v1/userinfo?alt=json", timeout=30)
    response.raise_for_status()
    email = response.json().get("email", "")
    if email.lower() != expected_email.lower():
        raise RuntimeError(f"account mismatch: expected {expected_email}, received {email or '<no email>'}")
    path.write_text(creds.to_json())
    path.chmod(0o600)
    return email


def cmd_rotate(args):
    home = Path(args.home).expanduser()
    current = home / "token.json"
    candidate = home / f"token.json.{args.account.lower()}"
    if not candidate.is_file():
        raise RuntimeError(f"candidate token file not found: {candidate}")
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=home, prefix="token-candidate-", delete=False) as f:
        staged = Path(f.name)
    try:
        shutil.copyfile(candidate, staged)
        staged.chmod(0o600)
        email = verify_account_token(staged, args.expected_email)
        backup = None
        if current.exists():
            backup = home / f"token.json.backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
            shutil.copy2(current, backup)
            backup.chmod(0o600)
        os.replace(staged, current)
        current.chmod(0o600)
        print(f"COLAB_ACCOUNT_ROTATED account={args.account.upper()} email={email} "
              f"backup={backup or 'none'} token_path={current}")
    finally:
        if staged.exists():
            staged.unlink()


def gh_json(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


def completed_failed_run(run_id):
    failed = gh_json(f"repos/{REPO}/actions/runs/{run_id}")
    if failed.get("path") != WORKFLOW or failed.get("status") != "completed" or \
            failed.get("conclusion") not in ("failure", "cancelled", "timed_out"):
        raise RuntimeError("source run must be a completed failed/cancelled/timed-out run of run-colab.yml")
    return failed


def ensure_no_active_runs():
    runs = gh_json(f"repos/{REPO}/actions/runs?per_page=100")
    active = [run for run in runs.get("workflow_runs", [])
              if run.get("path") == WORKFLOW and run.get("status") in ("queued", "in_progress")]
    if active:
        raise RuntimeError("refusing duplicate dispatch; active run(s): "
                           + ", ".join(str(run["id"]) for run in active))


def dispatch_checkpoint_resume(run_id, checkpoint, args):
    ensure_no_active_runs()
    payload = {"ref": "main", "inputs": {
        "notebook": "notebooks/p2a_train.ipynb", "mode": "full", "executor": args.executor,
        "gpu": "T4", "timeout": "28800", "max_steps": str(args.max_steps),
        "save_steps": str(args.save_steps), "resume_checkpoint": checkpoint,
        "download_remote": "/content/p2a-checkpoints/full",
        "download_local": "p2a-output-full.zip", "runner": "colab-driver"}}
    subprocess.run(["gh", "api", "--method", "POST",
                    f"repos/{REPO}/actions/workflows/run-colab.yml/dispatches", "--input", "-"],
                   input=json.dumps(payload), text=True, check=True, stdout=subprocess.DEVNULL)
    print(f"RESUME_DISPATCHED source_run={run_id} checkpoint={checkpoint} "
          f"executor={args.executor} max_steps={args.max_steps}")


def cmd_dispatch_resume(args):
    completed_failed_run(args.failed_run_id)
    ensure_no_active_runs()
    checkpoint = latest_checkpoint(hf_api(), args.repo)
    dispatch_checkpoint_resume(args.failed_run_id, checkpoint, args)


def cmd_recover_503(args):
    completed_failed_run(args.failed_run_id)
    ensure_no_active_runs()
    checkpoint = latest_checkpoint(hf_api(), args.repo)
    log = subprocess.check_output(["gh", "run", "view", str(args.failed_run_id),
                                   "-R", REPO, "--log"], text=True, stderr=subprocess.STDOUT)
    if "503" not in log or "/tun/m/assign" not in log:
        raise RuntimeError("run log does not confirm an assign 503; refusing account rotation")
    rotate_args = argparse.Namespace(home=args.home, account=args.account,
                                     expected_email=args.expected_email)
    cmd_rotate(rotate_args)
    dispatch_checkpoint_resume(args.failed_run_id, checkpoint, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True, dest="command")
    latest = sub.add_parser("latest", help="show newest complete checkpoint path in HF")
    latest.add_argument("--repo", default=CHECKPOINT_REPO)
    latest.set_defaults(func=cmd_latest)
    backup = sub.add_parser("backup-hf", help="download newest complete HF checkpoint to LV1")
    backup.add_argument("--repo", default=CHECKPOINT_REPO)
    backup.add_argument("--destination", default="~/p2a-checkpoints")
    backup.set_defaults(func=cmd_backup_hf)
    run_backup = sub.add_parser("backup-run", help="download and extract a run's p2a-output artifact")
    run_backup.add_argument("run_id", type=int)
    run_backup.add_argument("--destination", default="~/p2a-backups")
    run_backup.set_defaults(func=cmd_backup_run)
    rotate = sub.add_parser("rotate-token", help="switch Colab account after confirming persistent 503")
    rotate.add_argument("account", choices=["tk2", "tk3", "tk1"])
    rotate.add_argument("--expected-email", required=True)
    rotate.add_argument("--home", default="~/.config/vncolab")
    rotate.set_defaults(func=cmd_rotate)
    resume = sub.add_parser("dispatch-resume", help="resume one completed failed run from latest HF checkpoint")
    resume.add_argument("failed_run_id", type=int)
    resume.add_argument("--repo", default=CHECKPOINT_REPO)
    resume.add_argument("--executor", choices=["lv1", "machine1"], default="lv1")
    resume.add_argument("--max-steps", type=int, default=50)
    resume.add_argument("--save-steps", type=int, default=25)
    resume.set_defaults(func=cmd_dispatch_resume)
    recover = sub.add_parser("recover-503", help="verify assign 503, rotate to an explicit account, resume latest HF checkpoint")
    recover.add_argument("failed_run_id", type=int)
    recover.add_argument("account", choices=["tk2", "tk3", "tk1"])
    recover.add_argument("--expected-email", required=True)
    recover.add_argument("--home", default="~/.config/vncolab")
    recover.add_argument("--repo", default=CHECKPOINT_REPO)
    recover.add_argument("--executor", choices=["lv1", "machine1"], default="lv1")
    recover.add_argument("--max-steps", type=int, default=50)
    recover.add_argument("--save-steps", type=int, default=25)
    recover.set_defaults(func=cmd_recover_503)
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as error:
        print(f"p2-ops: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
