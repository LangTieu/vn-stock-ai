# P0 — skill-as-prompt cho nghiên cứu chứng khoán Việt Nam

Chỉ đóng gói prompt và đánh giá thử; không huấn luyện, không triển khai. `system_prompt.txt` chứa wrapper/luật BCTC/JSON output; `tool_spec.json` định nghĩa đầu vào snapshot; `snapshot.py` tính chỉ báo bằng `inputs/indicators.py` và chỉ đưa số liệu đã kiểm chứng vào `VERIFIED_DATA`; `vcb_snapshot.json` là ví dụ tại 2026-11-06. Giá OHLCV trong snapshot tính bằng nghìn VND/cổ phiếu. Thiếu dữ liệu phải giữ nguyên chuỗi `không có số liệu`; không thay số liệu 5 phiên cho 20 phiên hoặc YTD.

## Chạy

Từ thư mục gốc: `python3 p0/snapshot.py --ticker VCB --as-of 2026-11-06 --output p0/vcb_snapshot.json`. Có thể kiểm tra snapshot và prompt bằng Python; `python3 p0/eval/run_eval.py` gọi proxy LiteLLM cục bộ có xác thực bằng khóa trong môi trường tiến trình, không ghi khóa ra đĩa. Chỉ chạy lại eval khi muốn tạo các response mới; cache trong `p0/eval/cache/` dùng cho việc phục hồi từng lần gọi. Không cần kết nối mạng để đọc kết quả đã lưu. Không dùng thư viện `vnstock`; dữ liệu OHLCV đã được cung cấp trong `inputs/bot-data/`.

## Eval thực tế

- Nguồn chọn mẫu: 20 mã đứng đầu `inputs/bot-data/stock_rank.json` theo đúng thứ tự file thực tế, không dùng điểm ví dụ trong brief. Mỗi mã có 3 lần gọi độc lập: 60 JSON raw trong `p0/eval/raw_*_run*.json`, manifest và `results.json`; 0 lỗi. Proxy gọi nhóm `vn-stock` (ưu tiên Tuoke theo cấu hình); tên **model thực sự trả về** trong cả 60 response là `gpt-6-sol`, không phải Qwen hay khẳng định backend Tuoke thực tế. Tham số gửi: temperature 0.1, top_p 0.75, top_k 40, reasoning_effort none.
- Rubric tự động (10 kiểm tra cấu trúc/chứng cứ) trung bình **10/10** sau khi sửa regex nhận dạng định nghĩa dấu dòng tiền; đây là heuristic, không phải đánh giá thủ công độ đúng tài chính. Tất cả 60 trả recommendation `ABSTAIN`; 53/60 để direction `UNKNOWN`, 7/60 là `DOWN`. Coverage dự báo có hướng **7/60 = 11,67%**.
- Giá thực tế lấy phiên gốc **2026-04-07** và phiên thứ 20 tiếp theo **2026-05-08**; VN-Index 1.677,54 → 1.915,37 (**+14,177307%**, UP). Trong **7** dự báo có hướng, hit-rate chiều mã **2/7 = 28,57%** và chiều index **0/7 = 0%**. Không được trình bày 2/7 thành 2/60 hoặc coi UNKNOWN là dự báo sai/đúng. Số liệu chi tiết ở `p0/eval/results.json`.

| Mã | Lần | Rubric TB /10 | Lợi suất 20 phiên % | Chiều thực | Chiều đầu ra ba lần |
|---|---:|---:|---:|---|---|
| HDB | 3 | 10 | +8,959 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| VHM | 3 | 10 | +42,622 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| CTG | 3 | 10 | +7,412 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| ACB | 3 | 10 | -1,501 | DOWN | UNKNOWN, DOWN, UNKNOWN |
| STB | 3 | 10 | +19,125 | UP | UNKNOWN, DOWN, UNKNOWN |
| MBB | 3 | 10 | +2,146 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| HCM | 3 | 10 | +15,256 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| VCB | 3 | 10 | +4,659 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| MWG | 3 | 10 | +8,471 | UP | DOWN, DOWN, DOWN |
| FRT | 3 | 10 | -3,006 | DOWN | UNKNOWN, DOWN, UNKNOWN |
| PVT | 3 | 10 | +5,737 | UP | UNKNOWN, UNKNOWN, DOWN |
| HPG | 3 | 10 | +3,886 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| HVN | 3 | 10 | +3,972 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| VCI | 3 | 10 | -4,596 | DOWN | UNKNOWN, UNKNOWN, UNKNOWN |
| TCB | 3 | 10 | +17,930 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| KDH | 3 | 10 | -2,992 | DOWN | UNKNOWN, UNKNOWN, UNKNOWN |
| NVL | 3 | 10 | +16,593 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| BID | 3 | 10 | +7,627 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| VPB | 3 | 10 | +7,287 | UP | UNKNOWN, UNKNOWN, UNKNOWN |
| VJC | 3 | 10 | +7,769 | UP | UNKNOWN, UNKNOWN, UNKNOWN |

**Giới hạn:** Bộ xếp hạng dùng để **chọn** mã được tạo từ đầu vào sẵn có muộn hơn ngày cutoff; do đó tập mẫu có thể có thiên lệch nhìn trước, kết quả trên chỉ là đánh giá P0 có kiểm soát dữ liệu prompt, **không phải backtest ngoài mẫu** hay độ chính xác triển khai. Thiếu văn bản phân tích riêng lẻ của bot gốc: không thể chấm rubric đối chiếu prose bot. Tại cutoff thiếu BCTC, ngoại 20 phiên/YTD và Fed nên ABSTAIN đúng hợp đồng; các hit-rate dựa trên 7 dự báo điều kiện rất thưa. Space công khai chạy Qwen2.5-14B-Instruct NF4 4-bit đã được kiểm tra bằng một probe riêng, nhưng phiên bản triển khai dùng system prompt cũ, `do_sample=False`, không nhận prompt mới/tham số sampling bắt buộc nên **không tính** vào 60 kết quả. Có lần gọi LiteLLM bị treo; sau khi dừng và đặt timeout 90 giây, runner phục hồi từ checkpoint; cuối cùng không còn lỗi trong manifest.

Đây là phân tích dữ liệu thử nghiệm, không phải khuyến nghị đầu tư.
