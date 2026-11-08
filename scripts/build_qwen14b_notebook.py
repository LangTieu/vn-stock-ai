#!/usr/bin/env python3
"""Sinh notebook P0.0 v4: test Qwen2.5-14B (4-bit) bang du lieu that VCB.
Henrry 17:17 08/11: nang model len nua thu (TK1). 14B la co lon nhat vua
T4 free 4-bit (~8-9GB VRAM); 32B (~18GB) khong vua T4 16GB.
Base 4-bit NF4 + double quant, compute float16 — vua T4 free (8-9GB VRAM).
Du lieu + prompt giong v2 (1.5B); chi doi model + quantization.
Ghi ra: notebooks/p0_qwen14b_vcb_real.ipynb
"""
import json
import os

BASE = os.path.expanduser("~/workspace/vn-stock-ai-model")
DATA = json.load(open(os.path.join(BASE, "datasets", "vcb_test.json")))


def md(source):
    return {"cell_type": "markdown", "metadata": {},
            "source": source.splitlines(True)}


def code(source):
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": source.splitlines(True)}


PROMPT_BUILDER = '''# Du lieu that VCB (ngay 2026-11-06) — dua vao prompt lam context (item 12)
import json
VCB_DATA = json.loads("""__VCB_JSON__""")

import json
d = VCB_DATA
ind = d["indicators"]
lines = []
lines.append("DU LIEU PHAN TICH MA VCB (ngay %s, HOSE):" % d["as_of"])
lines.append("- Gia dong cua: %s VND (%s%% so voi phien truoc), MA20: %s VND, RSI(14): %s, gia %s MA20."
             % (f"{ind['last_close']:,.0f}", ind["change_pct_1d"],
                f"{ind['ma20']:,.0f}", ind["rsi14"],
                "tren" if ind["above_ma20"] else "duoi"))
lines.append("- Khoi ngoai 5 phien gan nhat (ty VND, am = ban rong): " +
             ", ".join("%s: %s" % (f["date"], f["net_value_ty"]) for f in d["foreign_last5"]) + ".")
lines.append("- Tu doanh 5 phien gan nhat (ty VND): " +
             ", ".join("%s: %s" % (f["date"], f["net_value_ty"]) for f in d["proprietary_last5"]) + ".")
lines.append("- Tin tuc:")
for n in d["news"]:
    lines.append("  + " + n)
lines.append("- Nguon: OHLCV VNDirect, khoi ngoai/tu doanh nmquan.vn, tin tong hop.")
DATA_TEXT = "\\n".join(lines)
print(DATA_TEXT)
print("---")
print("So phien OHLCV kem theo:", len(d["ohlcv_last20"]))
'''.replace("__VCB_JSON__", json.dumps(DATA, ensure_ascii=False))

GENERATE = '''import time
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch

bnb = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.float16,
)
tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-14B-Instruct")
model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen2.5-14B-Instruct", quantization_config=bnb, device_map="auto")
print("model loaded on:", model.device)
print("VRAM used (GB):", torch.cuda.memory_allocated() / 1e9)

SYSTEM = ("Ban la tro ly phan tich chung khoan Viet Nam. Tra loi bang tieng Viet. "
          "Ket luan truoc, roi moi giai thich. Chi dung so lieu duoc cung cap, "
          "khong bia them so. Trinh bay ngan gon co bang neu can. "
          "Cuoi bai them 1 cau mien tru trach nhiem duy nhat.")
USER = DATA_TEXT + "\\n\\nPhan tich ma VCB: xu huong, dong tien khoi ngoai/tu doanh, vung ho tro/khang cu, va danh gia ngan han."
messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": USER},
]
text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tok([text], return_tensors="pt").to(model.device)
t0 = time.time()
out = model.generate(**inputs, max_new_tokens=512)
reply = tok.decode(out[0][len(inputs.input_ids[0]):], skip_special_tokens=True)
print("=== REPLY (%.1fs) ===" % (time.time() - t0))
print(reply)
'''

nb = {
    "cells": [
        md("# P0.0 v4 — Test Qwen2.5-14B (4-bit) bang du lieu THAT ma VCB\n\n"
           "Henrry 17:17 08/11: nang model len nua thu (TK1). Base 4-bit NF4 + "
           "double quant, compute float16 — vua T4 free (8-9GB VRAM).\n"
           "Du lieu that ngay 2026-11-06, nhung thang vao prompt lam context. "
           "So sanh chat luong voi ban 1.5B (v2): doc so ty co dung khong, co ket "
           "luan truoc khong, co nhac tang von + trich lap Q3 khong."),
        code("!nvidia-smi --query-gpu=name,memory.total --format=csv\n"
             "import torch\n"
             "print('torch:', torch.__version__)\n"
             "print('cuda available:', torch.cuda.is_available())\n"
             "print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"),
        code("!pip install -q transformers accelerate bitsandbytes"),
        code("from google.colab import drive\ndrive.mount('/content/drive')\n"
             "import os\n"
             "print(os.path.exists('/content/drive/MyDrive/vn-stock-ai'))\n"
             "print(os.path.exists('/content/drive/Shared with me/vn-stock-ai'))"),
        code("from transformers import AutoTokenizer\n"
             "tok0 = AutoTokenizer.from_pretrained('Qwen/Qwen2.5-14B-Instruct')\n"
             "print('tokenizer ok:', tok0.__class__.__name__)"),
        code(PROMPT_BUILDER),
        code(GENERATE),
        md("## Ket qua mong doi (de doi chieu voi v2 1.5B)\n\n"
           "- Model phai doc dung: gia 53.600 duoi MA20 55.855, RSI(14) 37,3, "
           "khoi ngoai BAN RONG 5 phien lien tiep (~-587 ty), tu doanh nho le.\n"
           "- Vung ho tro 53.000-53.500, cau chuyen tang von (phat hanh rieng le 543,1 tr cp).\n"
           "- 7B ky vong: doc so ty DUNG don vi (khong thanh %), ket luan truoc, "
           "nhac duoc tang von + trich lap Q3, khong cut cau giua chung.\n"
           "- Ghi lai: VRAM dung bao nhieu GB, thoi gian sinh bao lau, so voi 44,7s cua 1.5B."),
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "accelerator": "GPU",
    },
    "nbformat": 4,
    "nbformat_minor": 0,
}

out = os.path.join(BASE, "notebooks", "p0_qwen14b_vcb_real.ipynb")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print("wrote", out, os.path.getsize(out), "bytes")
