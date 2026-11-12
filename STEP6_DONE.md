# Step 6 — P2 resume and eval proof

- Resume command requested `--resume /vol/p2a-resume-proof-20261112/checkpoint-2`
  with `--max-steps 4`; Modal reported `TRAIN_EXIT 0` and completed step 4.
- Loss by step: 1 `1.8611`, 2 `2.3405`, 3 `1.8855`, 4 `0.7793`.
- Final `adapter_model.safetensors` SHA-256:
  `ecf030b8dab85670856e2dccaa379ff6ba5bddb0656283c0936f5bdf5626fc9e`.
- Eval used the pinned `scripts/p2a_eval.py` (SHA-256
  `fe111ca017e89889204f482bc91082b2c72004a3de6776fe857735f744f3c335`) on 20
  holdout records. There are 13,641 eligible holdout records in total.
- `direction_accuracy`: `0.45`
- `exact_format_rate`: `1.0`
- `brier`: `0.4908893182507755`
- `ece_4_bins`: `0.47432722856630655`
- Downloaded [`eval.jsonl`](artifacts/step6/eval.jsonl), 20 lines, 3,261 bytes;
  SHA-256 `6c637df087b85c4a97439755df7a0bbc13ca9f36bc25eb985f054b9ec7e38122`.
- Final Modal billing summary: metered cost `$1.68725121`, billed cost `$0E-8`.
