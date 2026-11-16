# P2a workstream 5 review: augmentation, retrieval, and architecture

Checked 2026-11-15 against the Liaison-approved V2 input scope and real P1 prompts.

## Data and feature evidence

The feature-scope audit scanned 97,766 bulk P1 prompts and found no sector/universe keys or text. V2 now keeps only ticker/as-of context, observed OHLCV, and technical indicators; flows, fundamentals, macro, signal text, and source metadata are excluded by a fingerprinted transform. See `docs/p2a-feature-scope-audit.json` and `docs/p2a-data-audit-v2.json`.

## Decision

- **Augmentation:** no synthetic market bars or labels are added. Current V2 labels are derived from real Finfo adjusted-price endpoints. No measured experiment shows synthetic augmentation improves the task, while invented examples would violate the no-fabricated-data requirement and risk misrepresenting corporate actions.
- **Retrieval:** no retrieval component is added. The target is computed from the real adjusted-price series, while the input uses the observed historical OHLCV/indicator snapshot. Extra retrieved corporate, sector, event, or macro data lacks verified point-in-time coverage and could introduce temporal leakage.
- **Architecture:** keep the existing Qwen2.5-14B QLoRA path unchanged. The 2-step v2 smoke establishes only that a bounded forward/backward/update path can run with finite observed gradient norms; it is not comparative evidence that a different architecture is better. The controlled LoRA/configuration ablation is a separate approved workstream and is running before any full training decision.

**Disposition:** workstream 5 is evaluated and complete as a no-change decision. No architecture or data-generation code was changed for this review. Revisit only if a controlled ablation on the same V2 split provides positive evidence.
