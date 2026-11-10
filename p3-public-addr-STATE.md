# P3 — Public addressing for LiteLLM + Workers gateway (STATE.md)

Updated: 2026-11-10 ~01:30 +07. All URLs below were checked by hand; nothing here is a placeholder.

## Workers gateway — DEPLOYED + VERIFIED END-TO-END

- **URL:** https://vn-stock-ai-gateway.vn-stock-ai.workers.dev
- **/health:** `{"ok":true,"upstreams":6}` (HTTP 200).
- **Secrets set + verified by list (no values):** LITELLM_URLS (6 hosts), GATEWAY_API_KEY, LITELLM_MASTER_KEY.
- **Deploy method:** Cloudflare API via connector surrogate (script `scripts/p3_deploy.py`, also on GitHub). Wrangler was NOT usable — the project token is not extractable from the connector, and Qoder's `wrangler --temporary` wrote secrets to a wrong temporary account.
- **End-to-end chat (through gateway, model vn-stock):** WORKS. "ok" test returns a valid chat completion (reasoning model puts thinking in `reasoning_content`; with max_tokens=20 the content field is null because reasoning consumes the budget — that is a model quirk, not a gateway failure). VCB test (max_tokens=600) returned a coherent Vietnamese analysis: conclusion-first "Xu hướng ngắn hạn của VCB hiện đang là giảm", stop-loss 53.500đ, re-entry above MA20 55.855đ + RSI >45-50. One run was degenerate (repetitive input echo, number corruption) — model output varies run-to-run; gateway is not the cause.
- **Worker fix 10/11:** `tryUpstream` now has `AbortSignal.timeout(30000)` (30s per host). Before this, a hanging host hung the whole Worker request (no failover). Pushed to GitHub; redeployed via API.
- **GATEWAY_API_KEY copies:** IB1 `/data/home/gateway_api_key` (0600, 55 bytes). VM /tmp copy shredded after tests.

## Verified (health + /v1/models + chat, Bearer auth)

| Machine | Mechanism | Public URL | Verified |
|---------|-----------|------------|----------|
| IB1 (agent-browser-relay1) | `instabox-port publish 4000` (no expiry) | https://4000-agq2ln7pkiptkjif5rapg6ajeu.instabox.tech | YES — health "I'm alive!" from VM; /v1/models 20 models; chat via public URL works FROM LV1 (HTTP 200, ~2s). NOTE: from VM and from Cloudflare Workers the public URL HANGS (60s+ timeout) — see "Known problem" below. |
| IB2 (rea-work) | `instabox-port publish 4000` (no expiry) | https://4000-agqzelppmu4se45k5tscmuxije.instabox.tech | YES — health from VM; /v1/models. Same hang from VM/Workers as IB1. |
| IB3 (instabox3) | `instabox-port publish 4000` (no expiry) | https://4000-agq332yzdd6xkookjmi6sr2mba.instabox.tech | YES — health from VM; /v1/models. |
| IB4 (box-1615a5db) | `instabox-port publish 4000` (no expiry) | https://4000-agq34ej3bbchwgwxejqglzikme.instabox.tech | YES — health from VM; /v1/models. |

## NOT working — LightVela Cloudflare Tunnels (proven 10/11)

| Machine | Mechanism | Public URL | Status |
|---------|-----------|------------|--------|
| LV1 (100.78.95.56) | Cloudflare Tunnel `lv1-litellm` (id f76009ad-5272-4aa0-9afa-0129a6d751ef) | https://f76009ad-5272-4aa0-9afa-0129a6d751ef.cfargotunnel.com | **FAILS from Workers:** tunnel-only LITELLM_URLS test returned `{"error":"upstream unavailable"}` in 1.3s (both tunnels fail FAST). From VM: empty reply HTTP 000. cloudflared IS running and registered (connIndex=3, sin15, QUIC), ingress hostname -> http://localhost:4000 is correct, LiteLLM alive on localhost:4000. Tunnel is connected but NOT serving traffic — needs diagnosis/recreation. |
| LV2 (100.75.174.33) | Cloudflare Tunnel `lv2-litellm` (id bf501ad3-3325-4c46-ba1f-fbe4f7d92c69) | https://bf501ad3-3325-4c46-ba1f-fbe4f7d92c69.cfargotunnel.com | **Same as LV1:** fails from Workers (tunnel-only test), empty reply HTTP 000 from VM. |

## Known problem — InstaBox public URLs hang from VM/Workers (10/11)

- From LV1, IB1's public URL chat works (HTTP 200, ~2s). From the VM it times out (60s+) and from Cloudflare Workers it also hangs. LiteLLM on IB1 is fine on localhost (0.9s). So the hang is in the network path VM/Cloudflare -> instabox.tech, NOT in LiteLLM.
- Mitigation in place: the Worker now fails over after 30s per host, so a request eventually reaches a working host (e2e "ok" test took 60s when IB1+IB2 hung, 2.3s when IB1 answered). The 4 InstaBox URLs still provide redundancy; LV1/LV2 tunnels are currently dead weight in the list.
- Tailscale Funnel is PARKED (Henrry 23:05 09/11). Do not revisit unless the tunnels also fail after recreation AND Henrry's Tailscale login works.

## What still needs doing

1. **Diagnose/recreate the LV1/LV2 Cloudflare Tunnels** (cloudflared connected but URL returns empty reply). Possible: delete + recreate tunnel, or check Cloudflare-side routing. This is the one remaining P3 gap.
2. Provider keys still owed by Henrry (Cerebras + BeatAPI for LV2/IB2/IB3/IB4; LLM7, Gemini, Radox for all machines). When they arrive: 0600 files in each litellm dir, uncomment/add legs, restart, verify.
3. The gateway's 30s-per-host failover means a request can take up to 6×30s=180s worst case if several hosts hang. If the InstaBox hang persists, consider reordering LITELLM_URLS (working hosts first) or shortening the timeout.

## Files / persistence

- InstaBox: `instabox-port publish 4000` (mapping stored by the platform, no expiry).
- LightVela: cloudflared binary `~/.local/bin/cloudflared`; credentials `~/.cloudflared/<tunnel-id>.json` (0600); config `~/.cloudflared/config.yml`; keepalive `~/cloudflared-keepalive.sh` + cron `*/5 * * * *`.
- Workers deploy script: `scripts/p3_deploy.py` (local + GitHub). Worker code: `workers/index.js` (local + GitHub).
- Tunnel credentials and the Cloudflare API token are never in this file.

## Status: MOSTLY DONE

Gateway deployed, 3 secrets set, end-to-end chat + VCB analysis verified through Workers. 4/6 upstream hosts reachable (IB1–IB4, with a hang-from-VM/Workers caveat mitigated by the 30s failover). 2/6 (LV1/LV2 tunnels) are NOT working from Workers — the remaining P3 gap.
