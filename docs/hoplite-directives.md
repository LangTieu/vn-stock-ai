# Hoplite standing directives

- When blocked, do not silently stop: explain the problem, what has been tried, and the exact access, data, or decision needed. Record blockers and questions in `docs/hoplite-status.json` for Liaison (Muse) to review and decide; continue independent work without waiting for Henrry on decisions within the approved plan. Ask Henrry only about money, account access, or a new strategic direction outside the plan.
- Complete work in larger sequential packages. After each finished item, update `docs/hoplite-status.json`, then commit and push that item's changes.
- Before launching real or paid work, validate command argument types; every element passed to a subprocess argv list must be a string. Add a regression test for any constructed argv that uses parsed/configured values.
- After a failed run, inspect its logs and artifacts and identify the root exception before changing parameters or dispatching again. Do not retry blindly; allow at most one retry while the cause is unknown, then stop, record the evidence and proposed fix in `docs/hoplite-status.json`, and wait for root-cause evidence or a decision.
- Never fabricate, infer, or synthesize missing market data. Mark gates `passes: true` only when supported by verified evidence.
- Report concrete evidence, verification performed, and unresolved limits.
- Read these directives at the start of every work turn.
