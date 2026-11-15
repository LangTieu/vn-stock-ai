# P2a V2 controlled LoRA/hyperparameter ablation

Status: controlled experiment workflow prepared; no trial has run yet. Full training remains paused until Liaison selects the ablation result and Henrry separately approves a full run.

## Fixed inputs and controls

- Only the private, successful Finfo-derived label-v2 artifact from Actions run `43691791091` is accepted. The train split is reduced to the same 64-row sample (32 UP/32 DOWN), seed 42, and the validation input is the same independent 64-row validation sample (32 UP/32 DOWN), deterministically held from 2024 rows within the P1 train split. Every selected training row has a target endpoint strictly before the validation period; the external 2025–2026 holdout is never used to tune configs.
- Every trial uses 12 optimizer steps by default (explicit workflow input, hard maximum 50), identical batch size, gradient accumulation (32), target modules, seed, feature transform, and train/validation checksums.
- One factor changes per comparison: baseline LoRA rank 8/alpha 32/dropout .1/LR 1e-4; LR-only 5e-5; rank-only 4 with alpha held at 32. TK2 is tried first; TK5 is used only after a confirmed `/tun/m/assign` HTTP 503. The Colab runtime is sequential, and the workflow refuses overlap with another training run.
- No HF/repository checkpoint upload occurs; labels and Finfo price series are not uploaded by the ablation workflow. The output artifact contains only config, checksums, aggregate finite-gradient counts, and held-out metrics.

## Selection and interpretation

Trials are ranked by the same internal time-separated V2 validation slice using direction accuracy, then macro-F1, then lower Brier score. The selected configuration is exploratory only because the validation set is small and a dozen steps are not converged training. Record all trials and the selected setting in `manifest.json`; do not start full training until Liaison selects a candidate and Henrry separately authorizes full training.

## Leakage-safe internal validation evidence

The actual v2 train artifact was split by time for the ablation: validation uses 2024 `as_of` rows; training candidates are restricted to rows whose target endpoint precedes the earliest validation `as_of` (2024-01-02). The fixed slices contain 128 train rows (64 UP/64 DOWN) and 64 validation rows (32 UP/32 DOWN), both with fixed hashes recorded by the workflow. For this real-data split, the latest train `as_of` is 2023-07-07, its latest target endpoint is 2023-12-26, and the earliest validation `as_of` is 2024-01-02. The external 2025–2026 holdout is not used for config selection.
