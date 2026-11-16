# Hoplite standing directives

- When blocked, do not silently stop: explain the problem, what has been tried, and the exact access, data, or decision needed. Record blockers and questions in `docs/hoplite-status.json` for Liaison (Muse) to review and decide; continue independent work without waiting for Henrry on decisions within the approved plan. Ask Henrry only about money, account access, or a new strategic direction outside the plan.
- Complete work in larger sequential packages. After each finished item, update `docs/hoplite-status.json`, then commit and push that item's changes.
- P2's active V2 campaign source of truth is `main` after Henrry's direct order and Liaison's fast-forward-clean merge at `8488d1c` on 2026-11-16. Set the campaign ref to `main`, validate it fail-closed, and record the exact ref and commit SHA for every run. Do not create parallel campaign branches; use a review branch for proposed changes and do not merge without explicit direction.
- The previous two-stage merge plan is superseded. PR #1 (`review/p2-async-evaluation-infra`) is closed as superseded; its required evaluator work was reconciled into the V2 line. Do not follow the former stage-1/stage-2 merge conditions. Training remains independently gated by readiness and Henrry's explicit training order.
- Before launching real or paid work, validate command argument types; every element passed to a subprocess argv list must be a string. Add a regression test for any constructed argv that uses parsed/configured values.
- After a failed run, inspect its logs and artifacts and identify the root exception before changing parameters or dispatching again. Do not retry blindly; allow at most one retry while the cause is unknown, then stop, record the evidence and proposed fix in `docs/hoplite-status.json`, and wait for root-cause evidence or a decision.
- Never fabricate, infer, or synthesize missing market data. Mark gates `passes: true` only when supported by verified evidence.
- Report concrete evidence, verification performed, and unresolved limits.
- Read these directives at the start of every work turn.
