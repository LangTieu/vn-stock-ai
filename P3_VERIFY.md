# P3 Gateway — Verify + file (09/11/2026)

Gateway gom 2 phan: LiteLLM Proxy (router/fallback, chay Python, host
rieng) + Workers frontend (mat tien, `workers/index.js`). Client goi
Workers `/v1/chat/completions` voi model `vn-stock`; LiteLLM fallback
theo chuoi khi 1 provider loi.

## Ai lam
- LiteLLM config (`litellm_config.yaml`): ban nhap do **Cerebras
  gpt-oss-120b** viet; em sua lai (indentation `api_key`, dinh dang
  `fallbacks`, them fallback cho alias `vn-stock`). YAML da kiem tra
  load duoc, 6 model, 5 rule fallback, tat ca key dung env var.
- Workers frontend (`workers/index.js`): do **LLM7 gpt-oss:20b**
  (turbo/free) viet. Da kiem tra cu phap JS (`node --check` OK).
  80 dong: auth, rate limit 30 req/phut/IP, force model `vn-stock`,
  forward len LiteLLM, ho tro stream, log khong ghi body/key.
- Perch KHONG lam duoc P3 lan nay (hong tren ca 5 may do share session
  — xem memory 09/11). Se giao Perch review lai khi dang nhap lai.

## Verify provider (live 09/11)
- **Cerebras:** song. 2 model: `gpt-oss-120b`, `qwen-3.8-27b`.
  Trial $5 den 25/11 (guard $0,20).
- **LLM7:** song. 68 model. **DeepSeek la pro (tra phi), KHONG free.**
  Model `openai/DeepSeek-V4-Flash-0731` trong plan cu KHONG ton tai —
  id that la `deepseek-v4-flash:0731` (pro). Leg LLM7 trong config
  dung `gpt-oss:20b` (turbo/free). Cac model turbo/free con lai:
  `codestral-latest`, `mistral-Nemo-Instruct-2407`,
  `nemotron-3-nano:30b`. Han muc free: 100k token/ngay.
- **Radox:** api_base `https://radoxai.com/v1` song (GET /v1/models
  tra 401 = can key, khong phai 404/sap). Model id la placeholder
  (`radox-default`) — server tu route. Can key that de goi that.
- **Gemini:** `gemini/gemini-3.5-flash-lite` (~20 cau/ngay theo plan).
  Chua goi that lan nay (can key Gemini).
- **Workers AI:** `@cf/openai/gpt-oss-120b`, 10k Neurons/ngay (theo plan).
  Chua goi that lan nay.

## File
- `litellm_config.yaml` — config LiteLLM Proxy (6 alias, fallback chain).
- `workers/index.js` — Workers frontend.
- `workers/wrangler.toml` — ten worker + ghi chu secret.
- `scripts/freechat.py` — helper goi chat completion qua
  Cerebras/LLM7 (dung khi Perch hong).

## Con thieu (can Chot/tay anh)
- May host LiteLLM Proxy (chua quyet) — can host moi chay + test
  end-to-end (acceptance: hedge ~6s, stream-first-token ~3s).
- Key that Radox + Gemini de test that leg (key nam trong connector,
  chua goi that).
- Deploy Workers (Plan lam, khong deploy o day).
