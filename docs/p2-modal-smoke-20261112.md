# P2 Modal smoke — 12/11/2026 (chunk 5b)

Port `p2a_train.py` sang Modal (`scripts/modal_p2a.py`): smoke 2 bước trên T4,
dữ liệu từ Volume `p2-train-vol` (tarball `p1-dataset.tar.gz`, sha256
`8839f5d8c2ce637ce46e1ff83f5fb635107c73054809b6cb756dee8811b72aec`).

## Kết quả — PASS 3/3

| | Lần A (file cũ) | Lần B (file cũ) | Lần C (file đã sửa) |
|---|---|---|---|
| App | ap-7KL6EKojFy2Y9MTsM9ymoP | ap-ERnnSOdG1ZGaika99pgh3I | ap-rbL55M0vYGoObsJZ8BStAU |
| Thời gian (UTC) | 13:00 → 13:21 | 13:03 → 13:25 | 13:26 → ~13:45 |
| GPU | Tesla T4 (7,5), torch 2.5.1+cu124, CUDA 12.4 | T4 | T4 |
| SHA_MATCH (tarball trong Volume) | True | True | True |
| DATASET_FILE | 3/3 PASS | 3/3 PASS | 3/3 PASS |
| LIGER | ENABLED (`apply_liger_kernel_to_qwen2`) | ENABLED | ENABLED |
| FlashAttention-2 | Không chạy được trên T4: `pre-Ampere GPU (sm_70); FlashAttention-2 requires sm80+` → dùng sdpa | như A | như A |
| GPU mem | alloc 9,30 GiB / reserv 11,05 GiB / free 3,39 GiB / total 14,56 GiB | như A | như A |
| trainable | 12.582.912 / 14.782.616.576 (0,0851%) | như A | như A |
| Step 1 | loss 1,8611, grad NaN, 264,56 s | loss 1,8611, NaN, 191,73 s | loss 1,8611, NaN, 204,53 s |
| Step 2 | loss 2,3405, grad 72,285, cum 537,79 s | loss 2,3405, grad 72,277, cum 382,19 s | loss 2,3405, grad 72,276, cum 410,15 s |
| train_runtime | 539,30 s → **269,65 s/step** | 382,93 s → **191,47 s/step** | 410,82 s → **205,41 s/step** |
| TRAIN_EXIT / WALL | 0 / 752,86 s | 0 / 453,21 s | 0 / 466,07 s |
| ADAPTER_SHA256 | `0f374bbcaa259b3f7cb1be73b3ae617bbecc9ffd7f1a19edfc691240377edc47` | `0f374bbc…` (giống hệt) | `0f374bbc…` (giống hệt) |

Trung bình 3 lần: **222,18 s/step**, ngang Colab chunk-4 (219,73 s/step);
dao động giữa các lần 191–270 s/step (khác host T4 thì khác tốc độ).
Adapter `adapter_model.safetensors` **50.382.896 B**, đã tải về từ Volume và
xác minh sha256 khớp log cả 3 lần.

Chú ý: `progress.jsonl` trong Volume được ghi thêm qua các lần chạy nên khối
PROGRESS_JSONL trong log trộn số các lần trước; số theo từng lần lấy ở dòng
live của trainer kèm timestamp.

## Lỗi đã sửa

`include_source=False` trong `@app.function(...)` làm Modal không đóng gói
`modal_p2a.py` → `ModuleNotFoundError: No module named 'modal_p2a'`.
Đã xóa dòng này (grep = 0, `py_compile` OK).

## Ghi chú Carbon review (20:06 ICT 12/11)

- Carbon nói image `debian_slim` thiếu gcc sẽ crash lúc JIT-compile C
  launcher → **sai**: 3/3 lần chạy `TRAIN_EXIT 0`, không lỗi C compiler/Triton
  nào, kể cả 2 lần chạy bằng file cũ không có gcc. Sửa
  `.apt_install("build-essential")` vẫn giữ như vệ sinh code; file đã sửa
  đã smoke-verify ở lần C.
- Carbon đề xuất đường dẫn tương đối cho `add_local_file` → đã áp.
- Carbon đổi `index_url` thành `https://pytorch.org` → **sai, không áp**:
  pip thật chứng minh `https://pytorch.org` không có torch
  (`No matching distribution found`), còn
  `https://download.pytorch.org/whl/cu124` có `2.5.1+cu124`.
- `p2a_train.py:321` dùng `fp16=True`, không có `bf16` — không cần sửa.

## Tiền

Spend limit $15 trên dashboard vẫn còn. Sau 3 lần smoke: Metered $1,31;
Billed $0,00.

## Chưa làm

- Không chạy full training (5.198 bước), không deploy production.
- Smoke không chạy `p2a_eval.py`; vấn đề eval `generation_invalid 20/20`
  của Colab run 6 vẫn mở.
