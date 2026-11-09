# Phương pháp phân tích BCTC — dạy cho model VN Stock AI

Nguồn: bản "PHẢN BIỆN BÁO CÁO BCTC Q3/2026 — 9 MÃ" (kiểm chứng độc lập qua API
Finhay Securities, 09/11/2026). Bản phản biện bắt được 3 lỗi thật của báo cáo
gốc — 3 lỗi đó chính là 3 luật dưới đây. Model phải phân tích theo các luật
này, không được mắc lại các lỗi đó.

## Luật 1 — Lợi nhuận so cùng kỳ là con số đầu tiên, không được giấu số xấu

- Luôn nêu **% thay đổi LNST so với cùng kỳ** ngay ở đầu phân tích.
- Lãi giảm mạnh (vd HCM −32,5%) là **lý do số một** để đánh giá thấp — quan
  trọng hơn ROE hơi thấp hay "phụ thuộc FVTPL".
- Không được viết mười chữ "rủi ro biến động" thay cho một con số −32,5%.
  Người đọc chấm điểm theo con số, không theo tính từ.

## Luật 2 — ROE phải là trailing 4 quý, KHÔNG BAO GIỜ niên hóa lợi nhuận 1 quý

- ROE = LNST 4 quý gần nhất / vốn chủ sở hữu bình quân (trailing).
- **CẤM** tính ROE = LNST 1 quý × 4 / vốn một kỳ. Cách đó thổi ROE gấp
  rưỡi trong chính quý bất thường nhất (vd VHM: ROE "33,49%" bịa ra từ quý
  lãi tăng 5,19x; ROE trailing thật chỉ 18,4%).
- Nếu nguồn đưa ROE theo quý, ghi rõ "ROE quý — không so được với ROE năm",
  không dùng nó để xếp hạng.
- Bắt được lỗi này ở mã này thì phải bắt ở mọi mã — không được để con số
  đẹp chạy qua chỉ vì nó đẹp.

## Luật 3 — In dòng tiền khối ngoại vào cạnh dòng lợi nhuận

- Mọi kết luận về "độ hấp dẫn" phải có **khối ngoại cả năm + 20 phiên gần
  nhất** đặt cạnh lợi nhuận.
- Lãi đẹp mà ngoại xả cả năm (vd VHM lãi +419% nhưng ngoại xả −3.959 tỷ)
  thì không được xếp hạng 1 — người trong cuộc biết điều gì đó mà báo cáo
  không hỏi.
- Hai khung cùng dương (vd PVT +280,5 tỷ cả năm, +27,7 tỷ 20 phiên) là
  tín hiệu mạnh. Đảo chiều (vd CTG cả năm −410,5 tỷ nhưng 20 phiên +193,6
  tỷ) là tín hiệu mạnh hơn — ghi rõ "đảo chiều thật".
- Kinh doanh tốt mà bị rút tiền lớn (vd HDB bị rút −3.170 tỷ) thì phải hỏi
  "ai hiểu gì đó mà mình không thấy?" — không được bỏ qua.

## Luật 4 — Xếp hạng phải có giá, không xếp hạng trên giấy

- Mọi mã được xếp hạng phải kèm **vị trí giá so với đỉnh/đáy** (vd HDB −4,3%
  từ đỉnh = mua giữa dốc, không phải đáy sâu) + RSI/hỗ trợ.
- Giá rẻ trên giấy (PE thấp, PB thấp) + ngoại xả mạnh = đặt câu hỏi về
  luận điểm "rẻ", không được chấp nhận mù.
- Tự mâu thuẫn trong 1 trang là lỗi: ghi rủi ro "tài sản tăng 70% từ phải
  thu" rồi vẫn xếp hạng 1 thì hạng đó vô giá trị.

## Luật 5 — Mọi kết luận phải có THỜI ĐIỂM (khi nào)

- Kết luận "có thể xem xét" mà không nói **khi nào** thì vô nghĩa. Phải có
  tín hiệu/điều kiện cụ thể (vd "chờ ngoại ngừng xả", "chờ giữ hỗ trợ").
- Không có tín hiệu, không có điều kiện thì nói rõ là chưa có điểm vào.

## Luật 6 — Cầu chì vĩ mô quyết định cỡ vị thế

- Luôn nêu bối cảnh vĩ mô (vd CPI VN 5,08% vượt mục tiêu, Fed 4%) vì nó
  quyết định cỡ vị thế, không phải chỉ quyết định mua hay không.
- Bối cảnh vĩ mô xấu thì vị thế nhỏ lại dù mã tốt.

## Luật 7 — Xếp hạng bằng điểm + bằng chứng đầy đủ

- Mỗi hạng phải có **điểm số + bằng chứng** (LNST %YoY, PE, PB, khối ngoại
  2 khung, RSI/đáy). Không xếp hạng bằng tính từ.
- Ví dụ thang điểm (từ bản phản biện): CTG 7 (LNST +28%, PE 5,8, PB 1,23,
  đáy sâu −11,5%, ngoại đảo chiều), PVT 7 (LNST +40,2%, PE 6,9, PB 1,08,
  RSI 33 quá bán, ngoại dương 2 khung), VHM 3, MBB 2, ACB 2, VCB 1, HDB 0,
  HCM −1, STB −3.
- Điểm âm được phép — mã tệ thì điểm âm, không ép về 0.

## Ghi nhớ

- Báo cáo BCTC tốt = **kết quả xét nghiệm tốt**. Nhưng kết quả xét nghiệm
  không phải đơn thuốc — phân tích phải trả lời được "xuống tiền khi nào,
  bao nhiêu", không chỉ "mã nào tốt".
- Đây là phân tích dữ liệu, KHÔNG phải khuyến nghị mua bán.
