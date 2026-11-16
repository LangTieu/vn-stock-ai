# P2 operator and event coordinator

**Safety state:** implemented as a fail-closed planner and dry-run event workflow. It has not dispatched training. Full training remains paused until Henrry's separate explicit approval. The sample manifest is `docs/p2-campaign.json`; its approval is `pending`, training-workflow-ready is false, and its pilot caps are one 50-step session / 50 cumulative steps.

## One operator interface

Use one CLI or the `P2 train/evaluate operator and campaign planner` workflow for both operations:

```sh
python3 scripts/p2_operator.py train --dry-run
python3 scripts/p2_operator.py evaluate --checkpoint-step latest --dry-run
```

Evaluation plans target `p2-eval.yml` and preserve a separate Colab T4 runtime, profile order `eval_tk2`, then `eval_tk5` only for a confirmed `/tun/m/assign` HTTP 503. Evaluation can be dispatched through the same CLI with the explicit `--dispatch` flag. Training plans target `run-colab.yml`, use a named training profile, and fail closed unless the campaign is approved, within caps, and the v2 full-training workflow is certified ready. `--dispatch` is explicit for the CLI; the GitHub operator workflow requires `dry_run=false` for evaluation. For training, `P2_TRAIN_APPROVAL_REF` must match the manifest approval reference and the v2 full-training workflow must be certified ready. The sample manifest is pending and deliberately marks that workflow not ready, so training cannot dispatch. The run-colab profile interface points to Liaison-installed `~/.config/vncolab/train_tkN/token.json` files and requires matching `P2_TRAIN_TK4_EMAIL`/`P2_TRAIN_TK5_EMAIL`/`P2_TRAIN_TK1_EMAIL` identity vars; the evaluator uses corresponding `eval_tkN` profile folders. The evaluator and trainer stay isolated; evaluator output/failure is recorded separately and does not change the training process result.

## Named credential profile interface

Liaison installs profiles outside the repository at `~/.config/vncolab/<profile>/token.json`, mode 0600, and expected account identities as environment variables. Names/order:

- Training: `train_tk4`, `train_tk5`, `train_tk1`; advance only after confirmed `/tun/m/assign` HTTP 503, never on arbitrary errors.
- Evaluation: `eval_tk2`, `eval_tk5`; the evaluator already falls back only after confirmed TK2 assignment HTTP 503.

`run-colab.yml` accepts a profile name for LV1 execution and verifies file permissions and identity before Colab assignment. `scripts/p2_profile_check.py` never prints or returns token contents. Liaison must provision the profile files and exact expected-email vars; this repository contains no credential material.

## Event coordinator and dry-run

`scripts/p2_campaign.py` validates the manifest and evaluates a completed-run event without network calls or side effects. It requires:

- v2 data version and pinned train SHA, label method, and FLAT band;
- for resume, complete optimizer/scheduler/trainer/RNG/adapter files **and** a matching v2 training manifest;
- explicit campaign approval, approved ref, valid conclusion, idempotency checks, and session/total-step caps;
- fail-closed manual review for failures/cancellations, except a clearly identified assignment 503 may produce a plan for the next named profile (still no dispatch).

The `workflow_run` campaign event always writes a plan artifact and never dispatches. Manual dry-run uses `dry_run=true`; manual evaluation may explicitly dispatch the existing isolated evaluator with `dry_run=false`. Manual training remains blocked by the approval/workflow-readiness gates. The local fixture rehearsal is:

```sh
python3 scripts/p2_campaign.py event \
  --manifest docs/p2-campaign.json \
  --event tests/fixtures/p2-campaign/run-colab-success.json
```

Current manifest returns `approval_or_preflight_required`, with `dispatch=false`. Other fixtures test running, failed, duplicate, ref-mismatch, checkpoint mismatch, and capped sessions. The workflow's `workflow_run` trigger is staged on the feature branch; GitHub only activates it after that workflow is reviewed and merged to the default branch. No merge was done here. Its event path is intentionally plan-only: the current source run does not carry a durable campaign-state artifact or v2 checkpoint inventory, and the sample manifest remains unapproved. Automatic continuation is therefore not enabled yet.

## Cron retirement

Do not run or modify the liaison-machine chain reference. Its 20-minute poll remains disabled but available as a rollback. Retire it only after the workflow event path has produced correct plan artifacts for a full rehearsal set, including success, running, failure/cancel, duplicate delivery, 503 profile fallback, incomplete checkpoint, v1/mismatched-v2 manifest, missing approval, and cap reached. Confirm alerts and idempotency before any dispatch-capable version is enabled.
