# P2 v1-contamination audit

**Scope and method.** Read-only sweep of `review/p2-async-evaluation` at `a3a7462` (the branch HEAD before this audit), compared with `main` at `5301343`. Notebook-embedded Python sources were extracted in memory and SHA-256/byte-compared with the standalone scripts. No dataset/checkpoint was downloaded, no workflow was dispatched, and no code was changed by this audit. Line references below are from the audited branch unless marked `main`.

## Executive result

- Embedded `/content/p2a_train.py`, `p2a_eval.py`, `p2a_validation.py`, and `p2a_numerics.py` are byte-identical to their standalone counterparts.
- The current training executable has a real v2 gate and refuses P1-v1 rows before tokenizer/model loading. Current resume validation also rejects a missing manifest and checks label version/data hash. This prevents the known v1 checkpoint-150 from being resumed through the current trainer.
- There are still **three RISK default paths**: (a) notebook dataset defaults are the legacy P1 URLs/MD5s, so ordinary `run-colab` does not select V2 data; the current trainer will abort rather than train on them; (b) async evaluation defaults to legacy P1 holdout and its label-version guard is skipped when a checkpoint lacks a training manifest; (c) the Modal smoke helper reads a P1 tarball and is not a V2 smoke path. No evidence in this sweep shows a successful current-branch optimizer run that trained on a mixed v1/v2 dataset; the risks are stale/default or fail-open paths that need cleanup before reuse.

## 1. Notebook defaults and embedded script parity — **RISK**

**Byte parity:** The embedded scripts in `notebooks/p2a_train.ipynb` are byte-identical to standalone sources:

| Embedded destination / notebook physical line | Standalone source | Result / embedded SHA-256 |
| --- | --- | --- |
| `/content/p2a_train.py`, line 89 | `scripts/p2a_train.py` | identical; `05d2fce7db5021327e199f63542176ebe58049d23d908fe96e4d3f1c5a59774c` |
| `/content/p2a_eval.py`, line 102 | `scripts/p2a_eval.py` | identical; `ea290b516090a9ca8b8ee91bab08ec3c96122c25721e45674225ac3d21aaaa76` |
| `/content/p2a_validation.py`, line 91 | `scripts/p2a_validation.py` | identical; `1dc014f6e95d560e905039f9293d530a97fcadef627a6d0ef4b5170ae76306d8` |
| `/content/p2a_numerics.py`, line 90 | `scripts/p2a_numerics.py` | identical; `e5af0fe580ebb51221d2e30545829df26050f362209b64f1cd7d491d0f6b111a` |

Notebook cell 1 defaults at `notebooks/p2a_train.ipynb:23-26` are legacy `Jerlob/vn-stock-ai-p1` `p1_train.jsonl.gz` / `p1_holdout.jsonl`, with train/holdout MD5s `f6273e8a12e35fe1027f29ca2127b9c0` / `5f48d9b13d2f2cce0a730067b2f3094c`. `DATASET_URL` defaults empty and `TRAIN_URL` wins (`:22-24,71-76`). Both smoke and full branches use those resolved paths (`:165-182`); smoke caps at 500 rows/2 default steps, full uses configured max steps, but neither branch changes the dataset source. The eval cell uses the same default holdout (`:228-232`).

Standalone `scripts/p2a_train.py` has no train URL; `--train` is required (`:435-440`) and its default MD5 constants are also legacy (`:24-26`). Standalone `scripts/p2a_eval.py` requires `--holdout`, but its default holdout MD5 comes from the same legacy constant (`scripts/p2a_eval.py:6,79-86`).

**Mitigation:** `dataset_label_spec` treats rows lacking `p2a_label_version` as v1 (`scripts/p2a_train.py:174-182`), and `require_v2_training` raises for anything except version 2 (`:223-226`); `main` calls this before loading the tokenizer/model (`:477-485`). Thus the current executable should stop on the default legacy dataset before training. Nevertheless, the default is unsafe/confusing and the v2 dataset is not wired into the normal notebook path.

**Fix proposal:** make training/holdout URLs and hashes required inputs with no legacy defaults; have the full-session path download only an explicitly selected private V2 artifact/revision and verify label version, manifest, SHA-256, label method, flat band and censor policy before any model initialization. Keep P1 URLs only in an explicitly named legacy diagnostic path that cannot train.

## 2. `p2a_eval_async.py` / `p2a_eval.py` holdout and label guard — **RISK**

`script/p2a_eval_async.py:19-20` sets the checkpoint repo correctly but sets `HOLDOUT_URL` to legacy P1 `p1_holdout.jsonl`. The generated remote job imports the P1 holdout MD5 and downloads that holdout (`:132-146`). `p2a_eval.py:11-18` rejects differing train/holdout label versions, but explicitly returns without checking if `train_manifest is None` (`:12-13`). The evaluator obtains the manifest from `<adapter>/p2a_training_manifest.json` and passes `None` if it is absent (`:90-93`). Meanwhile `checkpoint_complete` / `latest_complete_step` require optimizer, scheduler, trainer state, RNG, adapter config, and adapter weights, but do **not** require `p2a_training_manifest.json` (`p2a_eval_async.py:87-107`).

**Effect:** a valid V2 checkpoint with its manifest should fail evaluation against the legacy V1 holdout (safe failure, no comparable metrics); a legacy checkpoint that passes the structural file check and lacks a manifest can skip the version guard and be evaluated against V1. That is an evaluation contamination risk, not proof of a successful mixed-label training run.

**Fix proposal:** make checkpoint discovery require a V2 training manifest and verify `label_version == 2`, train SHA, method, horizon and flat/censor metadata. Replace the async evaluator's P1 holdout default with the pinned, approved V2 internal validation artifact/revision and verify its label version/hash before evaluation. Keep the compromised external holdout out of routine checkpoint comparisons; full-holdout mode must require a separately approved, matching V2 artifact. Fail closed if the manifest is missing; remove the current `None` bypass for checkpoint evaluations.

## 3. `.github/workflows/run-colab.yml` jobs — **RISK**

The ordinary `run-colab` job does not download a V2 artifact or set `TRAIN_URL`, `HOLDOUT_URL`, `TRAIN_MD5`, or `HOLDOUT_MD5` (`.github/workflows/run-colab.yml:178-220`). Its notebook input defaults to a P0 notebook (`:13-16`); if an operator selects `notebooks/p2a_train.ipynb`, its P1 defaults apply. Current `require_v2_training` should reject those rows before model loading, but this generic full-mode job is not a configured V2 training path.

By contrast, the dedicated `p2a-v2-smoke` job downloads the private `p2a-vndirect-adclose-audit` artifact by source run ID (`:291-304`), requires exactly one `p1_train_v2.jsonl`, rejects raw adjusted-price files and checks the artifact manifest's `label_version == 2` (`:305-325`), and builds a balanced V2 slice. `p2a-v2-ablation` separately downloads the private artifact (`:398-413`), requires a V2 train file/manifest (`:414-433`), and builds internal train/validation slices.

**Effect:** the bounded smoke/ablation jobs are explicitly V2; the ordinary P2 full-session path remains legacy-default/unwired. Its trainer guard is a mitigation, not a V2 data path.

**Fix proposal:** add a dedicated full-V2 training job/input that fetches the authorized private V2 artifact by run ID or immutable dataset revision, validates its manifest/checksums, supplies the V2 train and matching holdout/validation sources, and uses the current v2-gated trainer. Prevent `run-colab` from accepting `notebooks/p2a_train.ipynb` in `mode=full` unless the V2 source gate is satisfied. Add a preflight test asserting the selected input label version/hash and the exact environment forwarded into the notebook.

## 4. Checkpoint resume validation (including checkpoint-150) — **CLEAN for current trainer resume**

The current training script rejects label version 1 (`scripts/p2a_train.py:223-226`), writes a training manifest with `label_version`, exact `train_sha256`, input transform, label method, flat band, LoRA/training config and code hashes (`:237-265`), and when `--resume` is used calls `validate_resume_manifest` (`:513-519`). That validator refuses a missing manifest and compares `label_version`, `train_sha256`, `input_transform_version`, `flat_band_pct`, method-related training fields, and the remaining config/code fingerprints (`:268-280`). Therefore checkpoint-150 cannot be resumed into this V2 trainer if its manifest is missing/V1 or its hash differs; the status record independently records checkpoint-150's legacy provenance and lack of verified V2 manifest (`docs/hoplite-status.json:151-210`).

The separate async evaluator's structural checkpoint scan does not provide that resume guarantee; see item 2. Do not infer “current training resume clean” means “all checkpoint consumers are V2-safe.”

**Fix proposal:** no additional resume-code fix identified in this sweep. Preserve the fail-closed manifest check and add an integration regression test that a legacy checkpoint (missing manifest or label_version 1) is rejected before any optimizer/model resume. Keep checkpoint-150 out of the V2 campaign.

## 5. `data/` and documentation claims — **CLEAN**

`data/` contains only `data/p2a-label-v2/market_closures_2014_2016.csv` (12,147 bytes), a calendar support file; no P1/V1 labeled JSONL rows are stored in the repository. `docs/p2a-data-audit-v2.json:4-17` labels `p1_train_v2.jsonl`, reports the V2 hash `39eb61ce…`, and shows the UP/DOWN/FLAT/None counts; `docs/p2a-finfo-adclose-coverage.json:41-60` records separately named `_v2.jsonl` outputs and exact V2 counts. Its `p1_input_sha256` at `:5-8` is explicitly provenance for source P1 files, not a claim that those inputs are V2 labels. The V1 baseline report identifies itself as `legacy P1 v1; diagnostic only; no model evaluated` (`docs/p2a-validation-baseline-v1-rerun.json:2-7`). The progress table explicitly labels its historical baseline and V2 artifacts (`docs/p2a-progress-24.md:11-15`). No v1 source rows are mislabeled as v2 in these inspected records.

## 6. Hugging Face `Jerlob/vn-stock-ai-p1` refs in P2 train/eval paths — **RISK**

The live P2 notebook defaults both train and holdout to the `...vn-stock-ai-p1...` dataset (`notebooks/p2a_train.ipynb:23-24`). The async evaluator independently defaults its holdout to the same P1 repo (`scripts/p2a_eval_async.py:20`). The old MD5s in the notebook and trainer (`notebooks/p2a_train.ipynb:25-26`; `scripts/p2a_train.py:24-26`) identify legacy P1 files. These references are legitimate legacy/source provenance for audits, but they are not safe defaults for the V2 train/eval path. Dedicated V2 smoke/ablation jobs use private V2 artifacts, not those public URL defaults.

**Fix proposal:** use explicitly named `P1_LEGACY_*` constants only in audit/legacy diagnostic tooling; make the P2a notebook reject unresolved P1 URLs for non-dry-run; require an explicit V2 source run/revision and SHA for training/eval. Async evaluation must consume the matching V2 validation artifact, not P1 holdout.

## 7. `scripts/modal_p2a.py` dataset path — **RISK**

The Modal image packages the current `scripts/p2a_train.py` (`scripts/modal_p2a.py:38-39`), but the smoke function reads a volume archive named `p1-dataset.tar.gz`, extracts `p1-dataset/p1/train.jsonl`, and checks legacy P1 train/holdout/smoke MD5s (`:64-109`). It then invokes the current trainer on that P1 train file with a 500-row/two-step smoke (`:111-125`). Current `require_v2_training` should reject these legacy rows before model initialization; the Modal helper itself has no V2 label selector/manifest and is therefore stale/incompatible, not a valid V2 smoke path.

**Fix proposal:** either retire/rename it as a deliberately V1-only diagnostic and make the V2 gate failure explicit before any GPU assignment, or replace its volume input with a pinned V2 dataset/manifest and verify V2 label semantics/hash. Do not infer V2 from the P2a script name or checkpoint directory.

## 8. P3 gateway / LiteLLM configs — **CLEAN (secondary surface)**

A targeted scan of `litellm_config.yaml`, `litellm_vnstock.yaml`, and `scripts/setup_litellm.sh` found no `Jerlob/vn-stock-ai-p1`, `p1_train`, `p1_holdout`, P2a checkpoint, or label-version references (configs are provider/model aliases). No P2 dataset path or V1 checkpoint is wired through these gateway configs. Generic P2a metric discussion elsewhere is documentation, not a gateway data/weights input.

**Fix proposal:** none for the requested gateway/config scope. Re-audit only if a P2a adapter/checkpoint alias or data-backed gateway endpoint is added.

## Cross-branch comparison and final disposition

Audit ref: `review/p2-async-evaluation` at `a3a7462`; comparison base: `main` at `5301343`. `main` also has P1 notebook defaults and its older trainer has no V2 label-version gate (`main:notebooks/p2a_train.ipynb:19`, `main:scripts/p2a_train.py:15-18,112-127`), so it is a legacy V1 line and must not be used as the V2 training ref. Current feature code adds the V2 guard/manifest, but retains legacy URL defaults and async evaluator fallback. V2 outputs are private Actions artifacts (source run `43691791091`), not repository files.

**Overall:** no evidence from tracked data/docs or current trainer code that V1 rows are successfully mixed into a V2 training run; the current training guard blocks that. However, default training/eval URLs, the async manifest-optional V1 evaluator path, and the Modal P1 smoke helper remain **RISK** surfaces. Treat the P2 V2 path as not contamination-proof until the proposed V2 defaults, async manifest/version/source checks, full-V2 workflow wiring, and Modal retirement/replacement are addressed. This audit is static source/document inspection only; it does not verify the contents of the private HF/Actions artifacts or remote Modal volume.
