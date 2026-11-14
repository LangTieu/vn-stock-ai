# P2 training operations

**Current training contract:** use the same dataset URLs and checksums, `--limit`, `--max-length 4096`, two epochs, model/optimizer settings, and 50-step sessions. Save/upload every 25 steps. Never dispatch a second run while a `run-colab.yml` workflow run is queued or active. Checkpoints are resumable only when the adapter, optimizer, scheduler, trainer state, and RNG state are all present.

## 1. Colab runtime disconnect, preemption, or session timeout

**Signal:** GitHub run fails/cancels/times out after the Colab runtime was assigned; inspect the completed job log and keep its run ID. Do not infer checkpoint availability from the local Colab directory.

**Action:** On LV1 with `HF_TOKEN` configured and `gh` authenticated, run `python3 scripts/p2_ops.py dispatch-resume <failed-run-id>`. It requires the source workflow to be completed unsuccessfully, refuses if any `run-colab.yml` run is queued/active, finds the highest *complete* checkpoint in the private HF repo, and dispatches one full LV1 session with `resume_checkpoint=checkpoints/checkpoint-N`. It refuses to start from scratch if no complete HF checkpoint exists. Keep training parameters/data contract unchanged.

## 2. Persistent Colab assign 503 / account quota

**Signal:** `vncolab` logs repeated `HTTP 503` on `/tun/m/assign` after its bounded retry/backoff. This indicates Colab rejected allocation; it does not distinguish quota from temporary service capacity.

**Action:** On LV1, use the guarded recovery command after the failed run is complete. It checks that the GitHub log contains an assign 503, refuses if another run is active, requires a complete HF checkpoint, verifies the chosen account's Google userinfo email before replacing the token, backs up the old token mode 0600, then dispatches one resume run:

```sh
python3 scripts/p2_ops.py recover-503 <failed-run-id> tk3 \
  --expected-email expected-account@example.com
```
The account must be explicitly selected in the approved order (TK2 → TK3 → TK1); the helper never rotates accounts or retries on one account unattended. It resumes the highest complete HF checkpoint. If token filenames/email mapping differ, stop and correct them before rotation.

## 3. HF checkpoint upload errors

**Signal:** `CHECKPOINT_UPLOAD_RETRY` followed by `CHECKPOINT_UPLOAD_FAILED`, invalid-token 401, or missing files during remote listing verification. A `CHECKPOINT_UPLOADED` line means the HfApi upload succeeded and the complete resume file set was listed remotely.

**Action:** The trainer retries upload and verification three times with 5/10-second backoff. If HF still fails but the workflow completes normally, the workflow downloads `/content/p2a-checkpoints/<mode>` and stores `p2a-output` artifact. On LV1, fetch it with `python3 scripts/p2_ops.py backup-run <run-id>`, which extracts and validates complete checkpoints. Prefer the latest complete HF checkpoint for resume; if HF lacks it, resume from the validated extracted LV1 checkpoint using the notebook's local checkpoint directory. You can also download the latest complete HF checkpoint to LV1 using `python3 scripts/p2_ops.py backup-hf`.

**Hard limit:** the current `vncolab` protocol only downloads after notebook cells finish. If the Colab runtime or runner dies before that final download and the HF upload also fails, there is no supported live mid-run channel from Colab to LV1. Do not claim the ephemeral checkpoint is backed up; stop and report that loss risk. Do not retry the same run from step zero if any checkpoint is recoverable.

## 4. Loss diverges or becomes NaN/Inf

**Signal:** inspect streamed step/loss records; a single noisy loss is not sufficient. A sustained sharp rise or any NaN/Inf is a stop condition.

**Action:** Stop the run promptly through its approved workflow cancellation, retain the last verified checkpoint before divergence, and report the run ID, step, loss history, and checkpoint. Do not continue from the diverged checkpoint or alter learning rate/data/hyperparameters without an explicit decision. Investigate data/label validity, numerical stability, and optimizer state before proposing a parameter change.

## 5. LV1 runner offline or run queued

**Signal:** GitHub Actions API reports a queued run while `colab-driver-lv1` is offline, or a job has no `runner_name`.

**Action:** Check runner status before dispatching. Restore LV1's runner service and confirm it is online. If LV1 cannot be restored and IB1 is online, dispatch with `executor=machine1`. Never dispatch a parallel run while one is queued/active; use `python3 scripts/p2_ops.py dispatch-resume ...` only after confirming the previous run completed unsuccessfully.

## 6. HF token expires / 401

**Signal:** checkpoint upload retry/failure logs show 401/invalid credentials, or client setup fails. Training intentionally continues with local checkpoints.

**Action:** Prompt the owner to refresh the write token with access to `Jerlob/vn-stock-ai-p2a-checkpoints`; do not place the token in code/logs. Preserve the current run if possible. If it completes, retrieve and validate the `p2a-output` artifact to LV1. After a fresh token is installed in the workflow secret and LV1 environment, upload the validated checkpoint or resume it locally. Do not train from scratch when a valid local/HF checkpoint exists.

## 7. Asynchronous checkpoint evaluation

**Signal:** after a `CHECKPOINT_UPLOADED checkpoints/checkpoint-N ... verified_files=...` line, `vncolab` schedules evaluation only at steps divisible by 50. Step 50/100/... uses the fixed holdout slice (32 UP + 32 DOWN, round-robin stratified by ticker and calendar quarter, seed 42); steps divisible by 500 use the full holdout. Evaluation uses a separate Colab runtime, TK5 first and TK6 only after a confirmed `/tun/m/assign` 503. It never reuses the training Colab runtime. A local LV1 lock and queue serialize eval jobs and deduplicate a finished step.

**Metrics/output:** `scripts/p2a_eval.py` reports direction accuracy (primary), macro-F1, per-class F1/confusion matrix, Brier, ECE, generation accuracy/format. The fixed-slice manifest records the source MD5/SHA-256, slice SHA-256, seed, class counts, tickers, and quarter strata. Results are written under `~/p2-evaluations/` on LV1, consolidated to `trend.csv`/`trend.json`, and uploaded under `evaluations/` in the private HF checkpoint repo. The enclosing Actions run also uploads a `p2-evaluations` artifact at completion.

**Limitations:** the trainer step that predates these hooks is not retroactively evaluated. Current code triggers on future checkpoint upload events. GitHub runner remains occupied by the parent train job while its notebook runs; eval is a detached LV1 process using a different Colab profile/runtime. The train notebook waits for any triggered eval worker before the Actions job exits so runner cleanup does not kill it. If TK5 and TK6 both return persistent assign 503, that eval fails once and records the error; training is not stopped. Full final-campaign evaluation can be explicitly requested with `python3 scripts/p2a_eval_async.py --step <final-step> --full-holdout` after the final complete checkpoint is uploaded.

## Smoke-check helper commands

```sh
python3 scripts/p2_ops.py latest
python3 scripts/p2_ops.py backup-hf --destination ~/p2a-checkpoints
python3 scripts/p2_ops.py backup-run <completed-run-id> --destination ~/p2a-backups
python3 scripts/p2_ops.py dispatch-resume <failed-run-id>
```

Account rotation and `dispatch-resume` are explicit operator commands; no unattended account switching or automatic duplicate dispatch occurs.
