# P4 draft — independent client for the VN Stock AI assistant

**Status:** proposal for Henrry review only. No P4 client code or deployment is included in this change.

## 1. What P4 is

P4 is a user-facing chatbot/AI Agent client for Vietnamese stock-market questions and analysis. It is a separate product surface from **Pocket Personal**: separate UI, configuration, deployment, credentials, and product scope. It consumes P3 as an API; it does not host model weights or call model vendors directly from the browser.

**Initial scope (MVP):** a responsive Vietnamese chat UI; streaming assistant replies; a small set of selectable tasks (general market Q&A and stock/company analysis); visible model/answer status; conversation reset and local-only history; clear caveats that outputs are informational, may be wrong/stale, and are not investment recommendations. Do not submit orders or represent the assistant as a broker/advisor. Avoid collecting account credentials or sensitive personal data.

**Out of scope for MVP:** trading/execution, user accounts and cloud-synced conversations, custom fine-tuning, a separate retrieval/data platform, and Pocket Personal integration. Add these only after a separate approval and security/privacy design.

## 2. Architecture and model transition

```text
Browser P4 client
   └─ HTTPS POST /v1/chat/completions (Bearer client key; SSE stream)
       └─ P3 Cloudflare Worker gateway (auth, rate limit, request logging, failover)
           └─ LiteLLM Proxy/upstreams
               └─ Qwen2.5-14B-Instruct base → final P2 LoRA adapter
```

- Use the existing P3 gateway URL and OpenAI-compatible chat-completions contract. Confirm the production URL and permitted client key at implementation time; do not put a LiteLLM master key or provider credential in browser code.
- While P2 is training, point a temporary LiteLLM model alias (for example `vn-stock-assistant`) at the approved Qwen2.5-14B-Instruct base model. The client always sends the alias, not a provider-specific endpoint.
- After P2 is complete and the final adapter is evaluated/approved, update the server-side LiteLLM model configuration behind that same alias to load the final Qwen2.5-14B base plus its LoRA adapter. Roll back the alias to the base configuration if health or acceptance checks regress. No client rebuild should be needed for a model swap.
- P2 checkpoints are for training recovery, not automatically production releases. Promote only the final evaluated adapter; pin its HF revision/artifact and record the model/base revision used.
- Preserve streaming (`stream: true`) from LiteLLM through the Worker to the browser. The UI must handle partial SSE events, `[DONE]`, upstream errors, timeout, and user cancellation.

## 3. Main user features

1. **Chat:** Vietnamese prompt entry, send/stop, streaming response, retry after a recoverable network error, and clear conversation.
2. **Analysis context:** optional ticker/input fields and a compact context summary included in the prompt. Show the supplied ticker and any date/source context so users can spot stale or mismatched inputs. Never invent missing fundamentals or market data.
3. **Task modes:** explicit, small set of prompt templates (general Q&A versus stock analysis); show which mode is active. The server/gateway remains authoritative for safety/system instructions.
4. **Transparency:** show the selected model alias, response-in-progress/error state, and a concise non-advice/uncertainty notice. If upstream grounding/data is unavailable, say so instead of implying live data.
5. **Privacy:** MVP conversation history stays in browser storage and is removable; do not add server-side persistence or analytics payloads containing prompt text without a separate review. Never log API keys in the browser or expose gateway master credentials.
6. **Responsive accessibility:** keyboard-operable chat, focus management, readable streaming state, and mobile/desktop layouts.

## 4. Technology choices (proposal)

- **TypeScript + React + Vite** for a small static SPA/PWA: familiar web stack, typed API/event handling, fast iteration, and no need for a long-running client server.
- **Cloudflare Pages** (or the already-approved static hosting target) for the isolated P4 client. Keep it in a separate P4 repository/project/account boundary from Pocket Personal; do not reuse Pocket Personal secrets or database.
- **P3 Worker gateway** as the only browser-facing model route. Use a dedicated, least-privilege client key if P3 supports it; otherwise design a safe public-client auth/rate-limit mechanism before launch. A static site cannot keep a shared secret hidden.
- **OpenAI-compatible SSE** rather than provider SDKs so the frontend stays independent of the serving backend and LoRA rollout.
- **No client database in MVP.** Browser-local history avoids introducing a P4 data service and simplifies deletion/privacy. Revisit server sync only with explicit approval.

These are draft choices, not implementation decisions; confirm repository/hosting ownership, production key model, and whether local conversation history is acceptable before coding.

## 5. Delivery steps and verification milestones

| Milestone | Work | Exit evidence |
|---|---|---|
| M0 — decisions | Approve product boundary, target users, gateway URL/auth, hosting/account, data freshness expectations, and local-history policy. | Henrry signs off on this draft or records changes. |
| M1 — API contract | Document request/response/SSE shape, allowed model alias, rate limits, timeout/error behavior, and safe client authentication. | Non-secret test request succeeds through P3; 401/429/5xx behavior is understood. |
| M2 — UI prototype | Build chat shell and task-mode/context controls with mocked streamed responses. | Mobile/desktop review; keyboard flow and stop/reset work. |
| M3 — gateway integration | Connect to P3 through the public Worker route; parse SSE incrementally; implement loading, cancel, retry, and error states. | End-to-end smoke using a non-production test key; verify no master/provider key appears in built assets or browser logs. |
| M4 — safety/privacy | Add disclaimers, stale/missing-data handling, local history controls, and content/logging review. | Review confirms no order execution, no hidden persistence, and explicit uncertainty. |
| M5 — base-model pilot | Use the approved Qwen2.5-14B base behind the stable LiteLLM alias while P2 finishes. | Functional/latency/error acceptance on a small approved test set; fallback route verified. |
| M6 — adapter promotion | Evaluate final P2 adapter offline; pin artifact/revision; switch only the server-side alias, then canary and roll back if needed. | Evaluation approved; health, response quality, latency, and rollback checks pass. |
| M7 — limited release | Deploy isolated P4 static client; observe gateway health/rate limits without storing prompt content. | Release checklist and owner approval; documented rollback and support path. |

**Suggested pilot acceptance checks:** chat completion and stream termination are correct; gateway errors are visible and recoverable; model alias can be switched without changing the client; client bundle contains no privileged key; conversation can be cleared; unsupported/live-data claims are not fabricated. Define numeric latency/quality thresholds with Henrry before M5.

## Review decisions requested

1. Is the MVP a standalone responsive web/PWA client, and which separate repo/account should own it?
2. Which P3 URL and safe client-auth mechanism should P4 use? Do not ship a shared master key in static JavaScript.
3. Is browser-local history acceptable, and should any prompts be sent to analytics/logging?
4. Which data sources/context should the stock-analysis mode display, and what freshness/quality threshold is required?
5. Who approves the final adapter evaluation and production alias switch?
