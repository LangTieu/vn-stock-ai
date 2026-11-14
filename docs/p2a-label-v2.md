# P2a label v2: 120 exchange sessions

## Contract

- The prediction cutoff is the row's `as_of` close. The target is the close on the
  120th later session in that security's exchange calendar.
- Return is computed from `adjusted_total_return_close`, a point-in-time series
  whose provider must document split and cash-dividend adjustments. If that
  series cannot be verified, do not publish a v2 dataset.
- `UP` means return > +2%; `DOWN` means return < -2%; otherwise the target is
  `FLAT`. This is a deadband to avoid assigning a direction to near-zero moves.
  The P2a binary direction task excludes FLAT from its UP/DOWN objective and
  reports FLAT coverage separately.
- If 120 future exchange sessions or an adjusted close at either endpoint are
  unavailable, mark the row censored and exclude it from supervised training and
  directional scoring. Never substitute a later quote or silently discard a
  ticker. Keep censor counts by exchange and ticker.
- Historical sector and exchange membership must be point-in-time. Current
  ticker lists are not an acceptable survivorship-bias correction.

## Rebuild inputs

`scripts/p2a_relabel.py` writes a new file and never overwrites its source. It
requires:

1. `calendar.csv`: `exchange,date`, one row per actual exchange session.
2. `adjusted_prices.csv`: `ticker,exchange,date,adjusted_total_return_close`,
   including the snapshot and exact 120th future session. Blank price means no
   valid quote and censors that row.
3. The original P1 JSONL dataset.

The generated manifest hashes the input, calendar, price table and output, and
reports class/censor counts. The resulting train and holdout checksums must be
recorded in the notebook/config before any future training. Each checkpoint also
stores its training manifest; the trainer rejects resume when the dataset hash,
label version, prompt, LoRA setup, or training configuration differs. Legacy
checkpoints without a manifest must start from the base model, not be resumed.

## Current gate

The old P1 JSONLs are available, but the repository contains neither the dataset
builder nor source OHLCV, corporate-action adjustment factors, exchange-session
calendar, historical universe membership, or point-in-time sector mappings. The
old source fields identify files under `data/train_2014_2026_*.json`, which are
not in this checkout. Therefore the relabel utility is tested on synthetic data,
but a production v2 dataset and a survivorship-bias pass have not been produced.
Do not mark this gate passed or train from the old labels pending those inputs.

The reproducible v1 audit is saved at `docs/p2a-data-audit-v1.json`. It
checks label counts, date gaps by exchange, ticker/date and prompt overlap,
future dates in prompts, and whether sector/industry fields exist. The train and
holdout SHA-256 values in that report identify exactly which public HF files were
audited. Its token-length counts are from a separate pass using the Qwen2.5-14B
tokenizer and P2a chat template. The current universe file described by the
collector was sourced in November 2026; that is not evidence of historical
point-in-time membership.
