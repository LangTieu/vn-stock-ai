"""VN Stock AI — Space demo (ZeroGPU).

Ban demo dung model Qwen2.5-14B-Instruct 4-bit (Chot 19:20 08/11: dung o 14B,
tran tren T4 free; 32B khong chay duoc) + skill phan tich CK VN lam prompt.
Muc dich: chung minh duong host ZeroGPU chay duoc. Khi co adapter LoRA
(buoc P2) se nap them adapter vao day.

ZeroGPU: GPU chi duoc cap trong luc ham @spaces.GPU chay (free 5 phut/ngay).
Model cache o CPU (global), moi lan bam nut thi chuyen len GPU, sinh xong
chuyen ve CPU de giai phong GPU.
"""

import spaces
import torch
import gradio as gr
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_ID = "Qwen/Qwen2.5-14B-Instruct"

SYSTEM_PROMPT = (
    "Ban la chuyen gia phan tich chung khoan Viet Nam. Tra loi bang tieng Viet, "
    "ket luan truoc, roi moi giai thich. CHI dung so lieu duoc cung cap trong "
    "phan du lieu, khong bia them so lieu hay tin tuc. Neu du lieu thieu thi noi "
    "ro la thieu. "
    "Phan tich BCTC theo 7 luat: (1) Neu % thay doi LNST so cung ky ngay dau; "
    "lai giam manh la ly do so mot de danh gia thap, khong duoc giau so xau. "
    "(2) ROE phai la trailing 4 quy; CAM nien hoa LNST 1 quy x4 (thoi ROE). "
    "(3) In dong tien khoi ngoai (ca nam + 20 phien) vao canh loi nhuan; lai "
    "dep ma ngoai xa ca nam thi khong duoc xep hang cao. 'Ban rong' nghia la "
    "KHOI NGOAI BAN (so am, tin xau), 'mua rong' nghia la KHOI NGOAI MUA (so "
    "duong, tin tot) — KHONG DUOC dao chieu huong dong tien. (4) Moi xep hang phai "
    "kem vi tri gia so voi dinh/day + RSI/ho tro; gia re + ngoai xa manh thi "
    "dat cau hoi ve luan diem 're'. (5) Moi ket luan phai co THOI DIEM (tin "
    "hieu/dieu kien cu the); khong co thi noi ro chua co diem vao. (6) Neu boi "
    "canh vi mo (CPI, Fed) vi no quyet dinh co vi the. (7) Xep hang bang diem "
    "so + bang chung day du (LNST %YoY, PE, PB, khoi ngoai 2 khung, RSI/day). "
    "Cuoi bai chi ghi 1 dong mien tru trach nhiem: day khong phai "
    "khuyen nghi dau tu."
)

DEFAULT_TICKER = "VCB"
DEFAULT_DATA = """Ma: VCB (Vietcombank), ngay 06/11/2026.
Gia dong: 53.600d, -1,11% trong ngay. MA20: 55.855 (gia dang DUOI MA20).
RSI(14): 37,3. Ho tro: 53.000-53.500.
Khoi ngoai ban rong 5 phien lien tiep: -110,8; -89,0; -13,5; -219,1; -155,1 ty
(tong -587,5 ty). Tu doanh nho/le: -0,7; +2,2; +5,5; +20,6; +7,9 ty.
Tin: (1) VCB dang thu vung ho tro 53.000-53.500 sau khi giam manh; 02/11 giam
~4,8% voi ~14 trieu co phieu. (2) NHNN chap thuan phat hanh rieng le toi da
543,1 trieu co phieu (6,5%), von dieu le len ~89.000 ty, Mizuho du kien tham gia.
(3) 9 thang 2026 LNTT ~40.440 ty (+22,1%), Q3 LNTT 11.218 ty di ngang do trich
lap 6.184 ty (khoang 5.000 ty cho 1 trai phieu doanh nghiep nganh nang luong),
no xau 0,71%, bao phu no xau 243,2%."""

_model = None
_tokenizer = None


def _load_model_cpu():
    global _model, _tokenizer
    if _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, quantization_config=bnb
        )
    return _model, _tokenizer


@spaces.GPU
def analyze(ticker: str, data: str) -> str:
    model, tokenizer = _load_model_cpu()
    model = model.to("cuda")
    try:
        user_text = (
            f"Phan tich co phieu {ticker} dua tren du lieu sau:\n\n{data}\n\n"
            "Hay dua ra nhan dinh: xu huong, diem manh/yeu, rui ro chinh."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer([text], return_tensors="pt").to("cuda")
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=512, do_sample=False, pad_token_id=tokenizer.eos_token_id
            )
        gen = out[0][len(inputs.input_ids[0]):]
        return tokenizer.decode(gen, skip_special_tokens=True).strip()
    finally:
        model.to("cpu")
        torch.cuda.empty_cache()


with gr.Blocks(title="VN Stock AI — Demo") as demo:
    gr.Markdown(
        "# VN Stock AI — Demo\n"
        "Ban demo chay model Qwen2.5-14B (4-bit) **chua fine-tune**, chi de thu ha tang "
        "ZeroGPU. Ket qua chua dung de dau tu."
    )
    ticker = gr.Textbox(label="Ma co phieu", value=DEFAULT_TICKER)
    data = gr.Textbox(label="Du lieu (gia, khoi ngoai, tu doanh, tin)", lines=12, value=DEFAULT_DATA)
    btn = gr.Button("Phan tich", variant="primary")
    out = gr.Textbox(label="Nhan dinh", lines=14)
    btn.click(analyze, inputs=[ticker, data], outputs=out)

if __name__ == "__main__":
    demo.launch()
