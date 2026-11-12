# P2 Modal resume and eval proof — 2026-11-12

The Modal run resumed `checkpoint-2` with `--max-steps 4`, completed steps 3–4,
and committed its checkpoint and adapter to `p2-train-vol`. Training losses by
step were 1.8611, 2.3405, 1.8855, and 0.7793. The adapter weights SHA-256 is
`ecf030b8dab85670856e2dccaa379ff6ba5bddb0656283c0936f5bdf5626fc9e`.

The pinned `p2a_eval.py` ran against 20 holdout rows (the dataset has 13,641
eligible rows) to keep this smoke proof within the Modal spend limit. Metrics:
direction accuracy 0.45, exact format rate 1.0, Brier 0.4908893182507755, and
4-bin ECE 0.47432722856630655. Downloaded predictions are in
[`artifacts/step6/eval.jsonl`](../artifacts/step6/eval.jsonl) (SHA-256
`6c637df087b85c4a97439755df7a0bbc13ca9f36bc25eb985f054b9ec7e38122`).

The resume fix scopes NumPy RNG safe globals to the explicitly requested
checkpoint load. Final Modal metered cost for the month was $1.72725121.
