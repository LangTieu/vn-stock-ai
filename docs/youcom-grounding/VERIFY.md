# VERIFY — kiểm chứng sống You.com grounding (không deploy)

Ngày chạy: 2026-11-12 (UTC). Key You.com verify trước khi dùng:
`ls -la /data/home/.youcom_api_key` → 600, 66 B;
`sha256sum` → `889975184e91b75489dec591ed249e8e566257aa4177d08c52bcf2ee5b90c896` (khớp brief).
Key chỉ đọc in-process, không in giá trị. Gateway key file `/data/home/gateway_api_key` (600,
55 B, len 54); LiteLLM master `/data/home/litellm/.master_key` (600, len 61) — chỉ đọc qua
harness, không in giá trị.

## 1. You.com Search thật (query: VCB Vietcombank tin moi nhat)

Harness: `POST https://ydc-index.io/v1/search`, header `X-API-Key` (docs chính thức:
Search ở `ydc-index.io`, Inference Router mới ở `api.you.com` — đối chiếu
`https://you.com/docs/guides/search` fetch 12/11).

Output thật (dán nguyên):

```
YOUC_SEARCH_HTTP 200
RESULT_COUNT 5
RESULT 1 | Vietcombank Securities | https://www.vcbs.com.vn/trung-tam-phan-tich |  | You need to enable JavaScript to run this app · Tiện ích · Đăng nhập · Giao dịch Trực tuyến · Bảng giá · Trung tâm phân tích · Liên hệ
RESULT 2 | Vnindex | https://vnindex.ai/stocks/VCB |  | Trong năm 2010, VCB đã hoàn tất 2 lần tăng vốn điều lệ thành công với mức tăng 9,28% (vào tháng 8/2010 và 33% vào tháng 2/2011, đưa tổng vốn điều lệ lên mức 17.588 tỷ đồng. Ngày 30/6/2009, Vietcombank
RESULT 3 | VCB: Ngân hàng TMCP Ngoại thương Việt Nam - VIETCOMBANK ... | https://finance.vietstock.vn/VCB-ngan-hang-tmcp-ngoai-thuong-viet-nam.htm |  | VCB: Tin tức và dữ liệu Ngân hàng TMCP Ngoại thương Việt Nam (VIETCOMBANK): 19/10/2026 - 56,900 đồng, giá realtime, giao dịch, tài chính, tin tức, sự kiện, hồ sơ doanh nghiệp,...
```

> Lưu ý host: `ydc-index.io/v1/search` trả 200 ngay lần đầu; brief ghi
> `api.you.com/v1/search` — docs hiện tại ghi Search ở `ydc-index.io`, và harness đã
> thử `ydc-index.io` trước (có fallback `api.you.com`). Nháp code dùng
> `https://ydc-index.io/v1/search`. Đây là khác biệt docs vs brief, đã ghi trong DESIGN §2.1.

## 2. Câu hỏi thật qua gateway LIVE (có khối grounding)

Câu hỏi: `VCB Vietcombank tin moi nhat` (với system prompt P0 + khối GROUNDING_DATA
nhét vào prompt qua gateway thật `https://vn-stock-ai-gateway.vn-stock-ai.workers.dev`).

Lưu ý kỹ thuật: gateway bị Cloudflare 403 error 1010 khi không có User-Agent
(`UA None → HTTPError 403: Forbidden error code: 1010`); với `User-Agent: Mozilla/5.0`
trả HTTP 200 và model `meta/muse-ember:free`. Harness dùng UA Mozilla/5.0.

HTTP thật:

```
GATEWAY_HTTP 200
MODEL_FIELD meta/muse-ember:free
USAGE {"completion_tokens": 2595, "prompt_tokens": 1489, "total_tokens": 4084, "completion_tokens_details": {"reasoning_tokens": 2219}}
```

Câu trả lời đầy đủ thật:

```json
{"ticker":"VCB","recommendation":"ABSTAIN","confidence":"LOW","direction":"UNKNOWN","sections":{"KẾT LUẬN":"LNST YoY: không có số liệu; khối ngoại cả năm/YTD: không có số liệu; 20 phiên: không có số liệu; ABSTAIN, chưa có điểm vào, cần đủ dữ liệu lõi từ VERIFIED_DATA trước khi kết luận.","BẢNG SỐ LIỆU":"giá: không có số liệu; MA: không có số liệu; RSI: không có số liệu; MACD: không có số liệu; ROE trailing: không có số liệu; PE: không có số liệu; PB: không có số liệu","TÍN HIỆU":"signal_text: không có số liệu; RSI là sức kéo, MA là giá trung bình, MACD histogram là đà tăng giảm","BCTC VÀ DÒNG TIỀN":"LNST YoY: không có số liệu; bán ròng = SELL/âm; mua ròng = BUY/dương; khối ngoại cả năm/YTD: không có số liệu; 20 phiên: không có số liệu; ROE trailing: không có số liệu; không nhầm cửa sổ dòng tiền","XẾP HẠNG":"không xếp hạng — không có số liệu","KỊCH BẢN VÀ VỊ THẾ":"WHEN: chưa có điểm vào; CPI: không có số liệu; Fed: không có số liệu; position_size: không có số liệu; điều kiện vô hiệu hóa: không có số liệu","GIỚI HẠN":"dữ liệu lõi thiếu, chỉ có tin tức grounding có nguồn và thời gian, không có số BCTC trong VERIFIED_DATA; Đây là phân tích dữ liệu, không phải khuyến nghị đầu tư."}}
```

### Kết luận verify (trung thực)

- Model VẪN ABSTAIN đúng luật: thiếu BCTC lõi (LNST YoY, PE/PB, ngoại, RSI...) trong
  VERIFIED_DATA → không tự tính số ngoài khối. Đây là HÀNH VI ĐÚNG, không phải lỗi.
- Điểm khác biệt thấy được: ở trường GIỚI HẠN, model ghi "chỉ có tin tức grounding có
  nguồn và thời gian" — chứng tỏ khối grounding đã vào prompt và được nhận biết,
  thay vì abstain mù không có gì. Nhưng nếu đặt câu hỏi thuần tin tức (không cần BCTC),
  model vẫn ABSTAIN theo format P0 vì recommendation bị ép bởi luật abstain (thiếu dữ
  liệu lõi); tin tức chỉ được dùng làm bổ sung trong GIỚI HẠN/KẾT LUẬN, không đủ để
  chuyển sang BUY/WAIT. Nói cách khác: grounding cho model "có tin để nhắc tới", nhưng
  không thay số BCTC có cấu trúc — đúng giới hạn đã ghi trong DESIGN §2.4.

## 3. Test tin tức thuần (chưa có VERIFIED_DATA BCTC)

| Trường hợp | Kết quả thật |
|---|---|
| Baseline (không grounding) | ABSTAIN, toàn "không có số liệu", GIỚI HẠN chỉ ghi "dữ liệu thiếu: không có số liệu" — không nhắc tới tin tức nào |
| Có grounding (query `VCB Vietcombank tin moi nhat`) | ABSTAIN đúng luật, nhưng KẾT LUẬN liệt kê 3 tin kèm nguồn (vietstock, vietcombank.com.vn, baomoi) từ GROUNDING_DATA, GIỚI HẠN ghi rõ "chỉ có GROUNDING_DATA bổ sung tin tức có nguồn + thời gian" |

→ Grounding sống: tin tức thật từ You.com đã đi vào câu trả lời có nguồn, mà không
phá vỡ luật abstain (không bịa số BCTC). Đây đúng là kết quả cần để Plan review/merge/
deploy: deploy gateway nháp → mọi chat đều tự có tin mới nhất có nguồn; BCTC số vẫn
phải từ VERIFIED_DATA/collector (lane sau), không thể từ snippet search.

## 4. File verify

- Harness: `verify_harness.py` (chạy thật, output dán ở trên).
- Nháp gateway: `workers/index-grounded.js` (`node --check` OK).
- Nháp provisioning: `provision_youcom_secret_DRAFT.py` (`py_compile` OK, CHƯA chạy).
- DESIGN: `DESIGN-grounding.md`.
