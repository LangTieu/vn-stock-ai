# Current external P2 chain controls (read-only reference)

These files are the liaison-side chain controls that currently drive P2
training sessions from outside the repo. Committed here so Hoplite can read
them while designing the event-driven campaign coordinator (approved
simplification #3).

- `chain_next.py` — polls the latest run-colab run; when finished, dispatches
  the next 50-step session resuming from the newest complete HF checkpoint.
  Dispatches with ref=main today; runs on a 20-minute cron (currently
  disabled while training is paused).
- `chain_state.json` — local chain ledger (last chained run + dispatch
  history).

Do NOT execute from the repo: paths and credentials referenced are
liaison-machine local (~/.hf_token, ~/workspace/...). Do NOT edit here to
change chain behavior; the coordinator redesign replaces these controls.
