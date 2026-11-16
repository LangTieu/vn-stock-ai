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

### Options

- **Replace `chain_next.py` + mutable `chain_state` + watch cron with one durable campaign record and event-driven Actions orchestration (recommended target).** The current repo does not contain `chain_next.py` or `chain_state`; these controls appear external to the tracked checkout. If the external coordinator can be simplified, store a small campaign manifest (approved ref/SHA, dataset/version/hash, target step budget, latest verified checkpoint, run IDs, approval state) as a run artifact or workflow output. A bounded `workflow_run`/reusable-workflow continuation can start the next session only after the prior session completes and its checkpoint is verified. Keep a required approval gate before the first training session and an explicit max-session/step cap.
  - Pros: one source of truth, fewer stale-state resets, event-driven rather than polling cron, recoverable/auditable continuation.
  - Cons: cross-run state/artifact handling and workflow permissions need review; GitHub event delivery is not a substitute for a checkpoint-integrity check.
- **Keep manual chain, cron, and token rotation.** Simple to understand in an incident, but repeated resets, missed watches, and copy/paste errors remain likely.
- **Fully automatic retry/rotation.** Not recommended without limits: arbitrary failures must not trigger repeated spend or silent account changes.

### Recommendation

Move toward one manifest-driven, event-based coordinator and remove cron polling only after the coordinator is proven in a non-training rehearsal. In the short term, reduce operator steps with one guarded command that (a) inspects the last run, (b) verifies a complete v2-compatible checkpoint/manifest, (c) checks no other train/eval job is active, and (d) prints the exact proposed ref/checkpoint/account before requiring approval. Do not let it dispatch until Henrry approves the campaign. For a confirmed Colab assignment 503, keep the explicit ordered fallback; prefer separately named, pre-verified credential profiles over overwriting a single token by hand, but keep credentials outside the repo/logs and never rotate on an unrelated error. A 401/expired token should request authorized credential refresh, not be treated as capacity 503.

## Decision requested from Liaison/Henrry

1. Approve the single-feature-branch policy now, with a later infrastructure-only PR after review?
2. Keep separate train/eval runtimes while simplifying them behind one operator entry point?
3. Approve a future event-driven campaign coordinator and named credential profiles, subject to a dry-run/rehearsal and an explicit training approval gate?

Until those decisions and a separate training approval are recorded, do not merge or dispatch training.
