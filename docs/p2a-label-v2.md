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

For the period before Finhay's exchange-index series starts, the checked-in
`data/p2a-label-v2/market_closures_2014_2016.csv` records sourced exchange
closures (including the 2014 HOSE/HNX reopening-date difference and the full
2015 Apr 28–May 1 closure). `scripts/p2a_build_session_calendar.py` derives
weekday sessions for 2014–2016 from those notices, then appends Finhay's observed
daily index bars from 2017 onward. The builder records the sources and hashes in
its manifest. The historical segment is a notice-derived calendar, not a daily
exchange-published trading-calendar feed; unknown unscheduled closures remain
an audit item.

The generated manifest hashes the input, calendar, price table and output, and
reports class/censor counts. The resulting train and holdout checksums must be
recorded in the notebook/config before any future training. Each checkpoint also
stores its training manifest; the trainer rejects resume when the dataset hash,
label version, prompt, LoRA setup, or training configuration differs. Legacy
checkpoints without a manifest must start from the base model, not be resumed.

## Current gate

The real Finhay snapshot has now been checked against P1. It contains 0
documented adjusted total-return closes, starts stock-price history in 2017
(while P1 starts in 2014), omits one P1 ticker, and has no point-in-time listing
or sector history. The 2014–2016 session calendar is notice-derived rather than
an official daily calendar. Raw-price-only endpoint coverage is diagnostic and
not a valid substitute for total-return labels. The production v2 dataset and
survivorship-bias pass are therefore still blocked; do not train from old labels
or unadjusted closes as if they were v2. See the measured gate and checksums in
`docs/p2a-label-v2-data-gate.md`.

The reproducible v1 audit is saved at `docs/p2a-data-audit-v1.json`. It
checks label counts, date gaps by exchange, ticker/date and prompt overlap,
future dates in prompts, and whether sector/industry fields exist. The train and
holdout SHA-256 values in that report identify exactly which public HF files were
audited. Its token-length counts are from a separate pass using the Qwen2.5-14B
tokenizer and P2a chat template. The current universe file described by the
collector was sourced in November 2026; that is not evidence of historical
point-in-time membership.
