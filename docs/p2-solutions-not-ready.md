# Proposed solutions for P2 readiness gaps

**Status: proposal only.** No liaison-side chain file was changed or run. No repository code, workflow, credential, state ledger, PR, or data was modified by this proposal. No run was dispatched, no PR was merged, and training remains paused.

## 1. Liaison-side chain ledger and `ref=main`

### Current facts

The read-only reference is `docs/p2-chain-reference/` at commit `cf27ab2`. Its `chain_next.py` dispatch payload hardcodes `"ref": "main"` (line 66 in that reference); it chooses the latest structurally complete HF checkpoint, then increments `max_steps` by 50. It polls only the newest `run-colab.yml` run, chains after any completed conclusion if a checkpoint exists, and uses `chain_state.json.chained_from` for dedup. The committed ledger has eight historic dispatch entries and `chained_from: 43580242658`. The script's README says its path/token are liaison-machine local, the 20-minute cron is disabled, and the file is read-only reference here.

### Proposed exact liaison-side reset and ref update

Do not clear `chained_from` while the old script or cron can execute: resetting it to null would make the next poll eligible to dispatch the latest completed run. Keep the cron disabled throughout migration.

1. On the Liaison machine only, make a timestamped, access-controlled backup of the current `chain_state.json`; do not put credentials in that backup or the repo.
2. Retire the old poller from the active schedule (leave the disabled cron disabled). Preserve the eight historical entries as audit history; do not reuse them as an active V2 campaign ledger.
3. In the Liaison-owned working copy only, replace the hardcoded dispatch `ref` with a required `campaign_ref` setting whose value must equal `review/p2-async-evaluation`; fail closed if unset or different. Do not edit `docs/p2-chain-reference/chain_next.py` in this repository.
4. Initialize the *new coordinator's* ledger as a paused campaign, rather than resetting the legacy script's live state:

```json
{
  "schema_version": 2,
  "campaign_id": "p2a-v2-full",
  "status": "paused",
  "approved": false,
  "ref": "review/p2-async-evaluation",
  "legacy_cutoff_run_id": 43580242658,
  "seen_source_run_ids": [],
  "dispatch_intents": [],
  "sessions": [],
  "latest_v2_compatible_checkpoint": null
}
```

The old eight entries remain in the archived legacy ledger; the cutoff ensures they cannot be replayed as new events. Do not set `approved=true` or attach checkpoint-150: it is a legacy-label checkpoint, not V2-compatible.

### Safe verification, without dispatch

- Verify the old cron is still disabled and the old poller is not invoked.
- Run syntax/static checks on the Liaison-owned copy only; inspect the generated dispatch *plan* and assert `ref == review/p2-async-evaluation`, the 50-step cap, and a V2 manifest requirement.
- Exercise with fixture run responses and a mocked HF listing / mocked API client. Assert zero POST calls, zero token reads from the repo, and no Colab allocation. Add an explicit `--dry-run` path that returns before the API POST; do not run the current script as a “test” because it has no safe dry-run mode and completed runs can dispatch.
- Keep cron disabled until the new coordinator passes all fixture cases and a reviewed rehearsal. A dry-run proves the plan, not that a real dispatch is safe.

## 2. Safe V2 data transfer and cross-event campaign state

### Blocker A — no full V2 transfer/resume path

Current `run-colab.yml` downloads the private V2 label artifact only in smoke/ablation jobs. The ordinary full-training job still defaults to the legacy public P1 URLs. The notebook's `dataset_path` uses direct unauthenticated `urlopen`; it is not a private-HF artifact downloader. The V2 train file is about 1.08 GB uncompressed, contains derived labeled feature rows, has SHA-256 `39eb61ce…`, uses label version 2 / adjusted total-return close after 120 exchange sessions / 2% FLAT band, and censors unavailable endpoints. It has 11,013 censored train rows; FLAT and censored rows are excluded from binary supervised training. The raw adjusted-price table must stay out of HF/repo and Colab artifacts.

**Preferred solution:** keep the audited source Actions artifact private and pinned by source run ID for provenance; after Liaison confirms the data-use/retention scope, publish only the V2 labeled train/validation JSONL plus signed/checksummed metadata to a private, access-controlled V2 dataset repository (not the public P1 repo and not the checkpoint repo). Pin an immutable repository revision and per-file SHA-256 in the campaign manifest. Teach the full-training workflow to download that exact revision with the existing HF secret, validate label version, manifest, checksums, FLAT/censor policy, and refuse any legacy file. The notebook must use an authenticated HF client (`hf_hub_download`/equivalent) for the private files without printing the token. For resume sessions, repeat the same immutable revision/hash checks and require the checkpoint training manifest to match. Do not resume checkpoint-150; restart from the base model after approval.

- Pros: one-time controlled data publication, repeatable sessions, avoids retransferring a 1+ GB file through thousands of notebook-kernel chunks.
- Cons: requires Liaison confirmation that the derived V2 labeled rows may be retained in that private repo, a private-repo access setup, and code/tests for auth + immutable revision pinning.

**Fallback if private V2 dataset storage is not approved:** every training Actions run downloads the already-authorized private source artifact by explicit source-run ID, validates it, and transfers the selected V2 file into the Colab runtime using an authenticated streaming/chunk protocol with end-to-end SHA-256 and a size/time limit. Rehearse transport using a non-training fixture/known-size synthetic file first; do not use raw adjusted-price artifacts. This is less attractive due transfer time, runner/runtime failure coupling, and temporary artifact retention.

**Repo vs Liaison:** repo work can add a full-run source selector, authenticated downloader, manifest/hash/label checks, checkpoint compatibility guard, and transport tests. Liaison must authorize the private data destination/retention, provision read/write HF access and expected account identity variables, and confirm no raw price table is included. Henrry must separately approve training.

### Blocker B — campaign state/checkpoint inventory is not persisted across events

The current sample `docs/p2-campaign.json` is a seed manifest, not durable mutable state. `workflow_run` receives the source run event but the training workflow does not attach a coordinator ledger/checkpoint inventory artifact; the event planner cannot recover it. Its staged workflow is also not active until available from the default branch. Therefore do not claim exactly-once auto-chaining or remove cron yet.

**Preferred solution:** serialize event handling with a campaign-specific GitHub Actions `concurrency` group; store an append-only state/decision artifact per coordinator run containing campaign ID, source run ID, ref/SHA, conclusion, pinned V2 dataset revision/hash, selected checkpoint name/step and verified file/manifest hashes, cumulative sessions/steps, approval reference, decision, and dispatch intent/result. On each event, fetch the latest completed coordinator-state artifact using Actions `actions:read`, validate its schema/hash, and deduplicate by `(campaign_id, source_run_id)`. Persist a dispatch intent before any future dispatch; after API acceptance, reconcile the resulting Actions run by an explicit source-run/campaign marker before marking the intent complete. Missing, expired, corrupt, or ambiguous state must block and require manual review. Artifact retention must exceed the campaign lifetime; if not, use a Liaison-provisioned durable state store with atomic conditional updates instead.

- Pros: no mutable `chain_state.json` reset per session; auditable lineage and replay protection.
- Cons: cross-run artifact lookup, retention, permissions, races, and dispatch reconciliation need tests. An Actions artifact is not a transactional database; state expiry must fail closed, not reset to an empty ledger.

**Repo vs Liaison:** repo can implement schema migration, artifact input/output, concurrency, deterministic idempotency, recovery states, and fixture tests. Liaison must decide/provision artifact retention or the durable state store and any required Actions write permission. Event workflow activation requires review/merge into the default branch under Henrry's Stage 1 approval; until then, only local/fixture dry-run is live.

## 3. PR #1 readiness and merge order

PR #1 is open and GitHub reports it mergeable, but “mergeable” only means no known branch conflict; it does not establish review approval, green checks, or V2 compatibility. Before Stage 1 is merge-ready:

1. Require focused CI checks green on the current PR head and an independent code review; retain auto-merge off. Verify no secrets or private data are committed.
2. Review the exact file scope. The evaluator implementation/hook may change trainer/notebook code only for instrumentation and detached scheduling; it must not silently change training labels, hyperparameters, data URLs, or add a training dispatch.
3. **Fix/check V2 evaluation compatibility:** `scripts/p2a_eval_async.py` currently downloads legacy `p1_holdout.jsonl` from the public P1 repo. `p2a_eval.py` rejects train/holdout label-version mismatches. A V2 adapter/checkpoint therefore cannot be correctly evaluated by that legacy holdout. Add a V2, label-compatible validation source pinned by manifest/hash (use the internal 2024 validation for routine checkpoint comparisons; the external holdout is compromised and must not be treated as pristine). Keep full-holdout evaluation disabled until its label version and approval are explicitly aligned.
4. Verify the safety contract with tests: checkpoint cadence (slice each 50, full only at approved milestone), TK2 then TK5 only on confirmed assignment 503, serialized/deduplicated eval, and eval failure visible in logs/artifact but not changing training's exit/success state. Ensure checkpoint incompleteness or v2-manifest mismatch blocks evaluation.
5. Record the reviewed PR head SHA and verification evidence in status. Stage 1 merge still needs Henrry's separate explicit approval; no merge is authorized by this readiness checklist.

**Recommended order:** (a) prepare/fix PR #1 and get checks/review green; (b) when Henrry separately approves Stage 1, merge only evaluator infrastructure; (c) separately complete V2 data transfer/resume and coordinator readiness; (d) obtain Henrry's distinct full-training approval; (e) train on the feature ref and evaluate each checkpoint; (f) only after full training completes and per-checkpoint evaluation proves the model, open/merge Stage 2 PR(s) for remaining P2 work under Henrry's decision. Keep `main` the clean proven line until then.

No work in this turn changes PR #1 or any workflow/code. The steps above are proposals for Liaison/Henrry review.
