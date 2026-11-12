# DESIGN-grounding — Nối You.com Search vào chat VN Stock AI (P3 gateway)

## 1. Đường chat hiện tại (đọc từ code thật)

```
Client (Space demo / caller OpenAI-compatible)
  |  POST /v1/chat/completions  + Authorization: Bearer $GATEWAY_API_KEY
  v
Cloudflare Worker gateway (workers/index.js — live)
  |  body.model = 'vn-stock'  (ép, bỏ model client gửi)
  |  failover từng host trong LITELLM_URLS, timeout 8s/host, 5xx -> host tiếp
  |  Authorization: Bearer $LITELLM_MASTER_KEY
  v
LiteLLM (port 4000 trên máy này)
  |  model alias "vn-stock" -> router_settings.fallbacks (danh sách vn-stock-*)
  v
Upstream LLM (Respan Ember / Cerebras / DeepSeek / GLM / Gonka / Itera / WorkersAI ...)
```

Bằng chứng từ code thật:

- `workers/index.js:61` — auth gateway: `auth !== 'Bearer ' + env.GATEWAY_API_KEY` → 401.
- `workers/index.js:82` — `body.model = 'vn-stock'` (ép model).
- `workers/index.js:14-34` — `tryUpstream`: POST `{base}/v1/chat/completions` với
  `Authorization: Bearer <masterKey>`, `AbortSignal.timeout(8000)`; 5xx → null (failover),
  4xx vẫn trả (lỗi của request, không phải host chết).
- `workers/index.js:94-98` — thử lần lượt từng host trong `upstreamUrls(env)` (`LITELLM_URLS`
  hoặc `LITELLM_URL` đơn, `workers/index.js:6-9`).
- `workers/index.js:53-56` — `GET /health` → `{ok:true, upstreams:<số host>}` (verify live
  12/11: `curl https://vn-stock-ai-gateway.vn-stock-ai.workers.dev/health` trả HTTP 200).
- Rate limit: 30 req/phút/IP (`workers/index.js:40-48`), 429 khi vượt.
- `p0/system_prompt.txt` — system prompt P0 hiện tại: chỉ khối VERIFIED_DATA là nguồn sự thật
  (dòng 3), luật ABSTAIN khi thiếu dữ liệu lõi (dòng 12), 7 luật BCTC (dòng 4-11),
  OUTPUT 1 JSON object, sections tiếng Việt, kết luận đứng đầu (dòng 13-15).
- LiteLLM `config.yaml` (trên máy, đọc cấu trúc không in key): `model_name: vn-stock` +
  `router_settings.fallbacks` gồm vn-stock-cerebras, vn-stock-deepseek, vn-stock-glm,
  vn-stock, vn-stock-workersai, vn-stock-gonka-*, vn-stock-itera-qwen,
  vn-stock-respan-ember (Ember `openai/meta/muse-ember:free`), vn-stock-respan-carbon.
- `scripts/p3_deploy.py` — mẫu deploy: PUT multipart lên
  `/accounts/<id>/workers/scripts/<name>` với bindings `secret_text`
  (LITELLM_URLS, GATEWAY_API_KEY, LITELLM_MASTER_KEY). Chỉ đọc để học pattern, KHÔNG chạy.

Chỗ model nhận dữ liệu hôm nay: system prompt + khối VERIFIED_DATA do client nhét vào
messages (gateway chỉ pass-through body, không thêm/chỉnh gì ngoài `body.model`).
Không có dữ liệu lõi → model ABSTAIN theo luật. Đây là chỗ grounding sẽ chèn khối mới vào.

## 2. Thiết kế grounding (quyết định bằng chứng)

### 2.1 Endpoint You.com — đối chiếu docs chính thức (12/11)

Nguồn: `https://you.com/docs/guides/search` (fetch thật 12/11, file tạm của tool).

- Web Search API: `POST https://ydc-index.io/v1/search` (cũng hỗ trợ `GET`; POST có
  `extraction` + `knowledge`, GET không).
- Auth: header `X-API-Key: <key>` cho mọi API trừ Inference Router
  (Inference Router dùng `Authorization: Bearer` — KHÔNG dùng ở đây).
- Gửi JSON body: `{query, count (default 10, max 100), freshness, ...}`; mảng là JSON array.
- Response: `results.web[]` gồm url/title/description + metadata (published date, thumbnail,
  favicon); `results.knowledge` khi `knowledge:"core"` (POST only).
- Giá: $5/1000 calls (tới 100 results/call). Key gifted $100 hiện có đủ cho Search.

Lưu ý: brief ghi `api.you.com/v1/search` — docs hiện tại ghi host `ydc-index.io` cho
Search/Contents còn `api.you.com` cho Inference Router/Answer/Research/Finance Research.
Gửi Research path tới `ydc-index.io` trả 403. Cả hai host đều thử được ở bước verify (§5);
nháp code mặc định `ydc-index.io` theo docs mới nhất, có biến `YOUCOM_SEARCH_URL` để đổi
nếu test live chứng minh ngược lại.

### 2.2 Chỗ gọi You.com — gateway Workers là chỗ đúng

Quyết định: **gateway gọi You.com Search TRƯỚC khi proxy tới LiteLLM, nhét kết quả vào
prompt dưới dạng khối dữ liệu có nguồn + thời gian.** Lý do theo bằng chứng:

1. Gateway đã là điểm duy nhất mọi request chat đi qua (auth + ép model + failover);
   chèn ở đây = thân thiện client, không sửa Space/collector, gateway vẫn pass-through
   streaming như hôm nay.
2. Relation tới helper `scripts/p3_deploy.py`: pattern secret Workers đã có sẵn
   (`secret_text` bindings); chỉ thêm binding `YOUCOM_API_KEY` là xong, không cần service
   mới, không cần thêm host, không cần thêm infra.
3. Service phụ (Python/Workers riêng) sẽ thêm 1 hop latency + 1 điểm chết + phải tự
   maintain; Python local không chịu được burst từ Internet (gateway đã làm việc này).
4. Alternative "client tự gọi You.com rồi nhét vào prompt" — loại bỏ: key sẽ lộ ở client,
   mỗi client phải tự implement, không kiểm soát được format khối grounding.

Trừ: nếu sau này cần Contents/Research cho bài sâu/BCTC dài → mới cân nhắc service phụ
(noi You.com Contents/Research) vì payload lớn, gating theo query. Hiện tại Search là đủ
(tin tức + trích dẫn ngắn). Ghi rõ trong code: chỉ Search ở lane này.

### 2.3 Hình thức khối grounding (được chèn vào prompt)

Gateway sẽ, với mỗi POST /v1/chat/completions:

1. Lấy query từ message user cuối cùng (nếu có), gọi You.com Search (count mặc định 5,
   tối đa chặn 10; timeout 5s; header X-API-Key từ secret YOUCOM_API_KEY).
2. Nếu You.com lỗi/timeout → bỏ qua grounding, proxy bình thường như hôm nay
   (fail-open: không chặn chat vì search chết).
3. Nếu có kết quả → tạo khối text và nhét vào message có role system ĐẦU TIÊN
   (hoặc chèn đầu messages nếu không có), SAU system prompt P0 hiện có, dạng:

```
<GROUNDING_DATA>
nguon: You.com Web Search API
thoi_diem: 2026-11-12T03:xx:xxZ (ISO, lúc search)
query: <query đã search>
- [1] <title> | <url> | <published?> | <description/snippet ngắn>
- [2] ...
</GROUNDING_DATA>
```

Chỉ sao chép nguyên văn tiêu đề/url/date/snippet từ You.com; không diễn giải lại.

4. Trả lời vẫn tuân luật abstain: nếu khối grounding + VERIFIED_DATA đều không có
   dữ liệu lõi → ABSTAIN như cũ; kết quả search cũng chỉ là dữ liệu, model KHÔNG tự
   tính số ngoài khối (giữ nguyên WRAPPER của system prompt P0).

### 2.4 Giới hạn đã biết

- Search snippet ≠ BCTC số liệu chính thức (LNST YoY, ROE trailing, PE/PB vẫn phải từ
  VERIFIED_DATA/collector). Grounding giúp "có tin mới để trả lời" thay vì abstain mù,
  nhưng không thay thế số BCTC có cấu trúc. Ghi rõ vào prompt grounding:
  "khối này bổ sung tin tức; số BCTC vẫn chỉ lấy từ VERIFIED_DATA".
- Gateway Workers có giới hạn CPU/wall-time: Search timeout 5s + cắt count → tránh làm
  tăng latency quá; nếu You.com chậm, fail-open về chat cũ.
- Rate limit 30 req/phút/IP giữ nguyên (grounding nằm trong cùng request nên không tăng
  số request vào gateway).

### 2.5 Rủi ro / alternative đã loại

| Phương án | Kết luận |
|---|---|
| Gateway gọi Search trước proxy | CHOSEN (đơn giản nhất, đúng điểm chèn) |
| Python service phụ gọi Search | Loại: thêm hop, thêm điểm chết, không cần |
| Client tự gọi You.com | Loại: lộ key, format không kiểm soát được |
| Research/Contents API | Loại ở lane này: chỉ khi cần bài sâu; Search đủ cho tin tức realtime |

## 3. File nháp code (bài này)

- `workers/index-grounded.js` — bản nháp gateway có grounding (KHÔNG sửa `workers/index.js` live).
  Giữ nguyên 100% hành vi hiện tại (auth, rate limit, failover, /health) + thêm bước
  grounding trước proxy. Kiểm tra cú pháp: `node --check workers/index-grounded.js`.
- `provision_youcom_secret_DRAFT.py` — nháp đặt secret Workers YOUCOM_API_KEY qua Cloudflare
  API theo pattern `scripts/p3_deploy.py`. CHỈ LÀ BẢN NHÁP, KHÔNG chạy (Plan deploy sau).

## 4. Verify

Xem `VERIFY.md`: 1 query thật You.com Search + 1 câu hỏi thật qua gateway với khối
grounding nhét vào prompt, kèm HTTP status + câu trả lời đầy đủ + nguồn grounding.

## 5. Việc giao Plan (lane này không deploy/commit/merge)

1. **Plan review**: đọc `DESIGN-grounding.md`, `workers/index-grounded.js`,
   `provision_youcom_secret_DRAFT.py`, `VERIFY.md`; đối chiếu diff với `workers/index.js`
   live; xác nhận luật abstain còn nguyên; quyết định có chấp nhận nháp không.
2. **Plan merge**: merge `workers/index-grounded.js` → `workers/index.js` (hoặc chọn
   phương án tốt hơn), giữ tên secret `YOUCOM_API_KEY`, giữ LITELLM_URLS hiện có trong
   `scripts/p3_deploy.py`.
3. **Plan deploy**: chạy bản thật (không phải DRAFT) của provision script để đặt secret
   YOUCOM_API_KEY qua Cloudflare API, deploy worker mới, test `/health` (phải thấy
   `grounding:true`) + 1 chat thật có tin mới; nếu lỗi thì rollback `workers/index.js`
   cũ. Key đọc từ `/data/home/.youcom_api_key` in-process, không in giá trị.
