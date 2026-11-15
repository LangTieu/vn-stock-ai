# P2a label v2: 120 exchange sessions

## Contract

- The prediction cutoff is the row's `as_of` close. The target is the close on the
  120th later session in that security's exchange calendar.
- Return is computed from `adjusted_total_return_close`, a point-in-time series
  whose provider must document split and cash-dividend adjustments. If that
  series cannot be verified, do not publish a v2 dataset.
- `UP` means return > +2%; `DOWN` means return < -2%; otherwise the target is
  `FLAT`. This is a deadband to avoid assigning a direction to near-zero moves.
- The P2a binary direction task excludes FLAT from its UP/DOWN objective and
  reports FLAT coverage separately. The ±2% band is the implementation's
  default candidate and must be part of each dataset's explicit label manifest.
- If 120 future exchange sessions or an adjusted close at either endpoint are
  unavailable, mark the row censored and exclude it from supervised training and
  directional scoring. Never substitute a later quote or silently discard a
  ticker. Keep censor counts by exchange and ticker.
- Historical sector and exchange membership must be point-in-time. Current
  ticker lists are not an acceptable survivorship-bias correction.
- To prevent thousands of redundant flow-coverage dates from causing silent
  training-row loss, train and eval use the same deterministic prompt transform:
  omit only nested `coverage.dates` arrays while retaining their count, bounds and
  status. The transform version is stored in every training manifest.
  On the audited P1 files, this shortened 1,439/83,147 eligible train prompts
  (1.73%, 3,732,820 characters total) and 621/13,641 holdout prompts (4.55%,
  1,858,958 characters). Exact Qwen2.5-14B tokenization with the training template
  then measured zero eligible examples over 4,096 tokens; maximums were 1,669
  train and 1,676 holdout tokens. The old untransformed audit found 515 and 261
  overlength rows respectively. These measurements are saved in
  `docs/p2a-data-audit-v1.json`.

## Rebuild inputs

`scripts/p2a_relabel.py` writes a new file and never overwrites its source. It
requires:

1. `calendar.csv`: `exchange,date`, one row per actual exchange session.
2. `adjusted_prices.csv`: `ticker,exchange,date,adjusted_total_return_close`,
   including the snapshot and exact 120th future session. Blank price means no
   valid quote and censors that row.
3. The original P1 JSONL dataset.

`scripts/p2a_build_session_calendar.py` includes a date only when an observed
exchange-index row or a positive-close stock-price row exists for it. The
liaison-provided source files are now mirrored under
`raw-2014-2026/` in the P1 HF dataset. Their observed rows supply 3,204 session
dates per exchange from 2014-01-02 through 2026-11-06; no dates are generated
from weekdays. The audit compares those dates to Finhay's observed index bars
over 2017-01-03–2026-11-06; HOSE has two additional observed price dates that
Finhay's index file lacks. Source hashes and counts are recorded in
`docs/p2a-drive-source-audit.json`.

The generated manifest hashes the input, calendar, price table and output, and
reports class/censor counts. The resulting train and holdout checksums must be
recorded in the notebook/config before any future training. Each checkpoint also
stores its training manifest; the trainer rejects resume when the dataset hash,
label version, prompt, LoRA setup, or training configuration differs. Legacy
checkpoints without a manifest must start from the base model, not be resumed.

## Current gate

The real Drive OHLCV files restore observed sessions for the former 13,062
train rows from 2014–2016; they do **not** contain adjusted prices. Exact raw
120-session start/end quotes exist for 83,832/83,942 train rows and
13,816/13,824 holdout rows. These are diagnostics only; 110 train and 8
holdout rows lack an exact endpoint quote. There are still 0
`adjusted_total_return_close` values and no verified corporate-action total
return series. Historical event coverage/terms and point-in-time universe also
remain incomplete. The production v2 labels and survivorship-bias pass are
therefore still blocked; do not train from v1 labels or raw closes as if they
were v2. See `docs/p2a-label-v2-data-gate.md`.

The reproducible v1 audit is saved at `docs/p2a-data-audit-v1.json`. It
checks label counts, date gaps by exchange, ticker/date and prompt overlap,
future dates in prompts, and whether sector/industry fields exist. The train and
holdout SHA-256 values in that report identify exactly which public HF files were
audited. Its token-length counts are from a separate pass using the Qwen2.5-14B
tokenizer and P2a chat template. The current universe file described by the
collector was sourced in November 2026; that is not evidence of historical
point-in-time membership.
