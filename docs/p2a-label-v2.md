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
- V2 model input is restricted to ticker/as-of context, OHLCV bars and technical
  indicators. Sector, industry, universe/listing-membership, flow, fundamental,
  macro, source and signal-text features are removed because reliable historical
  point-in-time inputs are unavailable. Liaison approved this scope decision;
  it closes the feature-level survivorship gate but does not claim P1 is a
  complete historical market universe. See
  `docs/p2a-feature-scope-audit.json`.
- Train and eval use the same deterministic prompt transform. It omits verbose
  coverage date arrays; for v2 it also retains only OHLCV and indicator inputs.
  Both transform versions are fingerprinted in the training manifest.
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

Liaison-authorized Finfo `adClose` v2 labels were generated from exact 120th observed exchange-session endpoints. Train has 72,929 labeled and 11,013 censored of 83,942 rows; holdout has 13,570 labeled and 254 censored of 13,824 bulk rows. Censored rows have missing exact start/end adjusted prices; no later quote or synthetic value was substituted. Class/censor counts and input/output hashes are in `docs/p2a-finfo-adclose-coverage.json`.

The v2 split audit reports zero forward-target overlap into holdout, zero ticker/as-of duplicates, zero duplicate prompts, and zero future prompt dates. The model input transform retains only ticker/as-of, OHLCV and technical indicators; sector/universe and other non-approved features are excluded. This passes the feature-level survivorship gate by Liaison decision, while the P1-observed sample is not claimed to cover every historical market listing. The audit is in `docs/p2a-data-audit-v2.json`; data-only baselines are in `docs/p2a-validation-baseline-v2.json`.

Do not train on v1. The approved next step is a bounded Colab gradient smoke using only the v2 balanced slice (TK2 first; TK5 only after an assign HTTP 503; maximum 50 steps, default two). Full training remains paused for Henrry. Do not publish raw Finfo adjusted prices to HF or the repository.

The reproducible v1 audit is saved at `docs/p2a-data-audit-v1.json`. It
checks label counts, date gaps by exchange, ticker/date and prompt overlap,
future dates in prompts, and whether sector/industry fields exist. The train and
holdout SHA-256 values in that report identify exactly which public HF files were
audited. Its token-length counts are from a separate pass using the Qwen2.5-14B
tokenizer and P2a chat template. The current universe file described by the
collector was sourced in November 2026; that is not evidence of historical
point-in-time membership.
