# P2a V2 controlled LoRA/hyperparameter ablation

Status: controlled experiment workflow prepared; no trial has run yet. Full training remains paused until Liaison selects the ablation result and Henrry separately approves a full run.

## Fixed inputs and controls

- Only the private, successful Finfo-derived label-v2 artifact from Actions run `43691791091` is accepted. The train split is reduced to the same 64-row sample (32 UP/32 DOWN), seed 42, and the validation input is the same independent 64-row holdout sample (32 UP/32 DOWN), seed 4242 for every trial.
- Every trial uses 12 optimizer steps by default (explicit workflow input, hard maximum 50), identical batch size, gradient accumulation (32), target modules, seed, feature transform, and train/validation checksums.
- One factor changes per comparison: baseline LoRA rank 8/alpha 32/dropout .1/LR 1e-4; LR-only 5e-5; rank-only 4 with alpha held at 32. TK2 is tried first; TK5 is used only after a confirmed `/tun/m/assign` HTTP 503. The Colab runtime is sequential, and the workflow refuses overlap with another training run.
- No HF/repository checkpoint upload occurs; labels and Finfo price series are not uploaded by the ablation workflow. The output artifact contains only config, checksums, aggregate finite-gradient counts, and held-out metrics.

## Selection and interpretation

Trials are ranked by the same held-out V2 slice using direction accuracy, then macro-F1, then lower Brier score. The selected configuration is exploratory only because the validation set is small and a dozen steps are not converged training. Record all trials and the selected setting in `manifest.json`; do not start full training until Liaison selects a candidate and Henrry separately authorizes full training.
