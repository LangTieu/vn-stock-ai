# P2 training simplification proposals (preparation only)

**Scope:** proposals only. No workflow dispatch, merge, code/config change, or training is authorized by this document. Full training remains paused pending Henrry's explicit approval.

## 1. Branch and merge workflow

### Options

- **Keep one experiment branch until the v2 run is reviewed (recommended now).** Use `review/p2-async-evaluation` as the sole working branch for this campaign; do not create a new branch for each fix or session. Keep `main` protected and unchanged while the v2 result is being proven. After review, submit one PR with the resulting code/docs; remove stale feature branches only after checking that their unique commits are either merged, intentionally abandoned, or preserved elsewhere.
  - Pros: one known dispatch ref, evaluator hooks stay attached to the experiment, no accidental training from stale code, and the safety review is easy to follow.
  - Cons: the branch lives longer and can accumulate unrelated changes; requires disciplined scope and a final PR review.
- **Promote stable safety/evaluator infrastructure in an earlier, separate PR.** Once the evaluator hook and guards pass their own tests/review, PR only those reusable protections into `main`; keep data/model experiments on the review branch until results are accepted.
  - Pros: future default-branch workflows can inherit reviewed safety behavior; separates reusable infrastructure from experimental model outcomes.
  - Cons: requires careful PR partitioning and conflict management; current `main` does not yet contain the integrated evaluator hook or standalone `p2-eval.yml`.
- **Use per-session branches or merge every package to main.** Not recommended: it multiplies refs and makes it harder to know which code/data gate a run used.

### Recommendation

Use one active feature branch for the P2 campaign, keep `main` protected, and do not delete any of the seven current branches until each is audited for unique commits. Once the evaluator/guard changes are independently reviewed and tested, consider a small infrastructure-only PR to `main`; do not make merge approval depend on whether a tiny exploratory model metric is good. Keep model/data-selection changes separate and merge those only after Liaison/Henrry review. Every dispatched run should record its exact ref and SHA in status/artifacts.

## 2. Training and asynchronous evaluation

### Options

- **Keep training and evaluation on separate Colab assignments (recommended).** Train uses its approved account rotation; evaluator remains TK2 first and TK5 only after a confirmed TK2 `/tun/m/assign` HTTP 503. Evaluator stays detached from the training process, deduplicates/serializes its own work, and writes metrics/artifacts without making evaluation failure fail or stop training.
  - Pros: strongest isolation on a 16-GB T4; prevents evaluation/model loading from competing with training VRAM; an evaluation exception cannot invalidate the training checkpoint or kill its parent job.
  - Cons: additional runtime quota/compute and more account plumbing; logs/results need one place to inspect.
- **Run evaluator sequentially on the training T4.** This can reduce account/runtime coordination but pauses training and reloads a large model/adapter in the same constrained VRAM. It does not satisfy the goal of async evaluation and increases the chance an eval failure interrupts the training session. Not recommended for Qwen2.5-14B QLoRA on a 16-GB T4.
- **One GitHub workflow interface, separate evaluator worker.** Expose train and eval as modes of a single reviewed workflow interface, while keeping the evaluator as a detached child process or separately scheduled job with its own Colab assignment. Keep the existing 50-step slice cadence and 500-step full evaluation cadence.
  - Pros: fewer operator entry points while preserving VRAM/process isolation.
  - Cons: GitHub runner/lock coordination remains; the workflow must ensure child failure is reported but non-fatal to training.

### Recommendation

Simplify the operator surface, not the GPU boundary: one campaign/train workflow and one internal evaluator service path are enough, but retain a separate Colab runtime for evaluation. Make eval failure visible in an artifact/status field and logs, but non-fatal to training; only checkpoint upload/verification, numeric guards, data/label mismatch, and training-process failures should stop training. Keep the evaluator's 14B model out of the training T4's VRAM. Do not add automatic retries for arbitrary evaluator errors; retry allocation only under the explicit, bounded 503 policy.

## 3. Preparation, coordination, chain state, and credentials

### Current liaison chain behavior (read-only audit)

Read `docs/p2-chain-reference/README.md`, `chain_next.py`, and `chain_state.json` at commit `cf27ab2`. The script was not executed and the reference files were not modified.

- `chain_next.py` polls only the newest `run-colab.yml` workflow run. If it is not completed, it prints a message and returns; that is the documented silent-when-running behavior (cron stdout is the only signal).
- It deduplicates only when `chain_state.json.chained_from` equals that run ID. After a successful 201/204 dispatch it updates `chained_from` and appends `dispatched`; it has no persisted pre-dispatch intent/reconciliation key, so a crash between API acceptance and ledger save can permit a duplicate on the next poll.
- It does not gate continuation on the previous run conclusion: any completed latest run can trigger continuation if a complete HF checkpoint exists.
- It selects the newest checkpoint with `optimizer.pt`, `scheduler.pt`, `trainer_state.json`, `rng_state.pth`, `adapter_config.json`, and either adapter weight file. It does not check the v2 training manifest, label version, dataset hash, or whether the checkpoint is compatible with the current label/data contract. Consequently, “complete” currently means structurally resumable, not semantically safe for v2.
- It dispatches the next run with hardcoded `ref: main`, 50 additional steps (`checkpoint step + 50`), `resume_checkpoint` at that newest checkpoint, and an LV1/T4 full session. There is no campaign approval check, max-session/total-step cap, or active-run/conflict check in this chain code.
- The ledger is a local JSON file with one `chained_from` value and a dispatch history. Its path, HF token, and custom GitHub API helper are liaison-machine local. The README says cron is every 20 minutes but currently disabled.
- The ledger records eight past dispatches (several source runs concluded `failure` or `cancelled`), illustrating why a completed status alone is not sufficient authorization to continue.

### Recommended coordinator design

Replace the poll-and-immediately-dispatch behavior only after a safe dry-run rehearsal. The coordinator should be event-driven from a completed training workflow, but initially emit a continuation plan/artifact rather than launching training. Later, after Henrry's separate approval, it may dispatch exactly one bounded next session if every gate below passes.

1. **Manifest-backed campaign ledger:** one versioned manifest stores campaign ID, approved source ref/SHA, label version and train SHA-256, model/config fingerprint, explicit Henrry approval record/reference, maximum session count, maximum cumulative optimizer steps, session size, latest accepted run ID, latest semantically compatible complete checkpoint, and idempotency keys for both observed and dispatched workflow runs. Do not store credentials in it.
2. **Preflight gates:** require approved campaign state; the completed source run must be on the approved ref/SHA and have an allowlisted conclusion (`success` by default; permit failed/cancelled continuation only under an explicit recovery action and documented checkpoint review); no competing active training run; checkpoint must contain the full structural set above *and* a matching P2a training manifest with label version 2, dataset hash, label method/horizon, FLAT/censor policy, and training config; enforce both per-session and cumulative caps.
3. **Exactly-once intent/reconciliation:** persist a continuation intent keyed by campaign + source run before sending dispatch. On a timeout/uncertain API result, reconcile against Actions runs for the same branch/ref and source marker before retrying. Record the resulting run ID and state before accepting another event. This is at-least-once event delivery made idempotent, not a claim of transactional exactly-once behavior across GitHub API and state storage.
4. **Operator-visible states:** every event writes a structured decision (`ignored_running`, `already_seen`, `blocked_reason`, `plan_ready`, `dispatch_accepted`, `dispatch_reconciled`, or `session_complete`) to a workflow artifact and campaign ledger. Missing credentials, invalid checkpoint, failure conclusion, cap reached, or approval missing must be explicit non-dispatch outcomes, not silent success.
5. **First-session approval:** use a repository/environment protection with a named human reviewer for the first training dispatch; then persist the approval reference into the campaign manifest. A boolean supplied by a caller or a repository file alone must not stand in for the human approval. Keep the campaign paused if the environment protection is not configured.
6. **Dry-run first:** `plan --dry-run` validates the manifest/schema, last run, candidate checkpoint, branch/SHA, profile names, caps, and approval state, then prints a redacted planned action without writing tokens, invoking dispatch, touching external cron/state, or allocating Colab. Test no-run, already-seen, invalid/missing v2 manifest, incompatible hash, failed/cancelled run, active run, missing approval, cap reached, and eligible-next-session cases. Only after a Liaison-reviewed dry-run artifact demonstrates all gates should an approved implementation replace cron polling.

### Named credential profile interface (design only)

The coordinator may refer to profile *names*, but credentials remain entirely in Liaison-managed environment/secrets or external permission-controlled files and are never committed, emitted in logs, or copied into campaign artifacts. Proposed names:

- Training order: `train_tk4`, `train_tk5`, `train_tk1` (the profile resolver maps names to Liaison-installed credentials; rotation policy must be explicitly approved and must not be triggered by arbitrary errors).
- Evaluation order: `eval_tk2`, then `eval_tk5` only on a confirmed `/tun/m/assign` HTTP 503.

The interface resolves a profile name to an already-installed credential and expected account identity, verifies identity before use, and fails closed if missing/mismatched. It must never accept a raw token value as a CLI argument or serialize token contents. Training and evaluation remain separate Colab assignments/runtimes: evaluation failure is recorded and visible but must not terminate or invalidate training. `401`/expired credentials are operator-action conditions, not capacity fallback signals.

### Rollout recommendation and trade-offs

- **Now:** preserve the current chain helper only as a disabled read-only reference; do not run it from the repo. Implement a manifest/schema validator and dry-run planner, and rehearse against fixture inputs only.
- **After a successful reviewed dry-run:** deploy an event-triggered coordinator in a non-training mode that only produces plans/status artifacts. Compare those decisions with the liaison's disabled 20-minute cron output; do not remove the cron before the event path is proven and its alerts/ledger are visible.
- **Only after Henrry's separate training approval:** enable the protected dispatch action with bounded session/total-step caps and named profile resolution. Remove cron polling only after a documented parity/recovery rehearsal and a rollback path.

Pros: no 20-minute polling, explicit provenance/idempotency, fewer manual state resets, clear errors, and an audit trail. Cons: state persistence and event redelivery are distributed-systems concerns; GitHub Actions/API permissions and environment protection require careful setup; the new coordinator adds code that itself needs rehearsal. Keep the existing disabled cron until dry-run/event rehearsal and alerting are proven; never auto-rotate credentials or retry arbitrary failures.

## Decision requested from Liaison/Henrry

1. Approve the single-feature-branch policy now, with a later infrastructure-only PR after review?
2. Keep separate train/eval runtimes while simplifying them behind one operator entry point?
3. Approve a future event-driven campaign coordinator and named credential profiles, subject to a dry-run/rehearsal and an explicit training approval gate?

Until those decisions and a separate training approval are recorded, do not merge or dispatch training.
