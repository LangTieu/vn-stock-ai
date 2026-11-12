# Grounding You.com — Plan deploy 12/11 ~12:0x ICT

## Review (nháp lane, ~/workspace/youcom-ground/)
- Diff nháp vs live (2426e0ea, file deploy 10/11): đúng như thiết kế — thêm
  fetchGrounding/lastUserText/trimSnippet/injectGrounding, /health thêm
  `grounding:`, gọi grounding trước proxy. Auth/rate-limit/failover/ép
  model/8s timeout giữ nguyên. VERIFY.md trung thực (ABSTAIN đúng luật,
  KẾT LUẬN liệt kê 3 tin có nguồn).
- 2 sửa của Plan trước khi deploy:
  1. Nháp XÓA 4 khối comment tiếng Việt của file live (upstreamUrls,
     tryUpstream, comment timeout 8s, comment failover) → merge = file live
     + phần grounding, giữ nguyên comment. Merged md5 051304fa (sau fix UA).
  2. Script provision DRAFT có 3 lỗi đường dẫn VM (KEY_FILE /data/home/...,
     WORKERS_DIR ../workers, /tmp/gateway_api_key) + deploy nháp nguyên văn
     → Plan viết lại provision_youcom_secret.py theo mẫu p3_deploy.py đã
     chứng minh 10/11 (key ~/.youcom_key, sha 88997518… verify trước khi
     dùng; /tmp key restore từ ~/.gateway_api_key rồi shred sau chạy).

## Deploy
- PUT workers/scripts/vn-stock-ai-gateway: "deploy OK, script id:
  vn-stock-ai-gateway". Secrets trên worker: GATEWAY_API_KEY,
  LITELLM_MASTER_KEY, LITELLM_URLS, YOUCOM_API_KEY (đủ 4).
- LITELLM_URLS giữ nguyên 6 host như live (upstreams:6).
- /health live: 200 {"ok":true,"upstreams":6,"grounding":true}.
- File live workers/index.js backup: index.js.bak-20261112 (2426e0ea).
  Rollback = PUT lại file .bak bằng cùng script provision.

## Test chat thật qua gateway (VCB, P0 system prompt, không nhét grounding tay)
- HTTP 200, model meta/muse-ember:free, ABSTAIN đúng luật — nhưng
  prompt_tokens 970 (không có khối grounding; lane verify có grounding là
  1489), câu trả lời KHÔNG nhắc tin nào. Grounding KHÔNG vào prompt.
- Chẩn đoán (bằng chứng, không đoán): You.com Search trả 403
  {"message":"Forbidden"} cho đúng key này, đúng query VNINDEX/VCB, từ IB1
  (2 UA khác nhau, GET + POST) — trong khi 10:15 + 10:49 cùng key/query trả
  200/5 kết quả. api.you.com/v1/search trả 401 Invalid API key (đúng như
  DESIGN: host đó chỉ cho Inference Router). Từ VM thì timeout (đường
  egress VM tới ydc-index.io treo — khác triệu chứng, cùng kết luận:
  search hiện không dùng được).
- Code gateway ĐÚNG: fail-open hoạt động (search chết → chat chạy bình
  thường như cũ). Fix UA (thêm User-Agent browser + log lý do grounding
  fail) đã deploy kèm nhưng không đổi kết quả — nguyên nhân là 403 từ
  You.com, không phải UA/timeout.
- KHÔNG rollback: code mới khi search chết hành xử y hệt code cũ + có
  /health grounding:true; rollback chỉ gỡ tính năng, không sửa được 403.

## Còn lại (ngoài tay Plan)
- You.com 403 cần kiểm tra phía tài khoản/key admin@aistockvn.com:
  dashboard You.com (key "vn-stock-ai" còn sống? credit $100 còn?
  có rule/quota mới?) hoặc support You.com. Khi API trả 200 lại, gateway
  tự grounding ngay, không cần deploy thêm (secret + code đã live).
- Repo commit (LangTieu/vn-stock-ai): lane AI-model chat (Plan không commit
  repo này, như fix 10/11).
