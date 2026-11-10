#!/usr/bin/env python3
"""Build the two self-contained Colab notebooks for the remaining 55 runs
of the P0 14B eval (runtime A = TK1/IB1, runtime B = TK2/IB2).

Reads p0/eval/colab_inputs_14b.json (built by build_colab_inputs.py) and
embeds, per notebook: the system prompt, the assigned tickers'
prompt_user/snapshot/input_hash/outcomes, and parse_json + score copied
verbatim from p0/eval/run_eval.py. No drive.mount, no external files.

Each generation cell runs one ticker (3 runs; VHM run3 alone), builds raw
records mirroring p0/eval/run_eval_14b.py exactly (model label differs:
"Qwen/Qwen2.5-14B-Instruct (Colab T4)"), and prints each record as one
line "RAW14B:" + json.dumps(raw) so it is recoverable from the driver
output (vncolab stores per-cell output text in colab_result.json).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "p0" / "eval"
INPUTS = json.loads((EVAL / "colab_inputs_14b.json").read_text())

# parse_json + score copied VERBATIM from p0/eval/run_eval.py (pure Python).
RUN_EVAL_SRC = (EVAL / "run_eval.py").read_text()
m = re.search(r"(def parse_json\(text\):.*?)\ndef main\(\):", RUN_EVAL_SRC, re.S)
assert m, "could not extract parse_json/score from run_eval.py"
SCORE_SRC = m.group(1).rstrip() + "\n"

RUN_A_TICKERS = ["VHM", "CTG", "ACB", "STB", "MBB", "HCM", "VCB", "MWG", "FRT", "PVT"]
RUN_B_TICKERS = ["HPG", "HVN", "VCI", "TCB", "KDH", "NVL", "BID", "VPB", "VJC"]
MODEL_ID = "Qwen/Qwen2.5-14B-Instruct"
MODEL_LABEL = "Qwen/Qwen2.5-14B-Instruct (Colab T4)"


def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(True)}


def code(source):
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": source.splitlines(True)}


CHECK_CELL = """!nvidia-smi --query-gpu=name,memory.total --format=csv
import torch
print('torch:', torch.__version__)
print('cuda available:', torch.cuda.is_available())
print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')
"""

PIP_CELL = "!pip install -q transformers accelerate bitsandbytes\n"

LOAD_CELL = f"""import time
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch

bnb = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.float16,
)
tok = AutoTokenizer.from_pretrained("{MODEL_ID}")
model = AutoModelForCausalLM.from_pretrained(
    "{MODEL_ID}", quantization_config=bnb, device_map="auto")
print("model loaded on:", model.device)
print("VRAM used (GB):", torch.cuda.memory_allocated() / 1e9)
"""

RUN_ONE_SRC = '''
def run_one(ticker, repeat):
    entry = DATA[ticker]
    snap = entry["snapshot"]
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": entry["prompt_user"]}]
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok([text], return_tensors="pt").to(model.device)
        out = model.generate(**inputs, max_new_tokens=PARAMS["max_tokens"],
                              temperature=PARAMS["temperature"], top_p=PARAMS["top_p"],
                              top_k=PARAMS["top_k"], do_sample=True)
        content = tok.decode(out[0][len(inputs.input_ids[0]):], skip_special_tokens=True)
        raw = {"ticker": ticker, "repeat": repeat, "model": MODEL_LABEL,
               "model_group": "space-14b", "actual_model": MODEL_LABEL,
               "timestamp_started_utc": started,
               "timestamp_completed_utc": datetime.now(timezone.utc).isoformat(),
               "elapsed_seconds": round(time.time() - t0, 3),
               "params": PARAMS, "input_hash": entry["input_hash"],
               "cache_hit": False, "content": content,
               "tool_calls": None, "finish_reason": "stop", "usage": None}
        raw["rubric"] = score(raw, snap)
        raw["stock_outcome_20"] = entry["stock_outcome"]
        raw["vnindex_outcome_20"] = entry["index_outcome"]
    except Exception as exc:
        raw = {"ticker": ticker, "repeat": repeat, "model": MODEL_LABEL,
               "model_group": "space-14b", "actual_model": None,
               "timestamp_started_utc": started,
               "timestamp_completed_utc": datetime.now(timezone.utc).isoformat(),
               "elapsed_seconds": round(time.time() - t0, 3),
               "params": PARAMS, "input_hash": entry["input_hash"],
               "error_type": type(exc).__name__, "error": str(exc)[:500]}
    RESULTS.append(raw)
    print("RAW14B:" + json.dumps(raw, ensure_ascii=False), flush=True)
    print("%s run%d: rubric=%s seconds=%s error=%s" % (
        ticker, repeat, raw.get("rubric", {}).get("score"),
        raw["elapsed_seconds"], raw.get("error")), flush=True)
    return raw
'''

SUMMARY_CELL = """ok = [r for r in RESULTS if "rubric" in r]
print("RESULTS: %d runs, %d with rubric" % (len(RESULTS), len(ok)))
for r in RESULTS:
    print(r["ticker"], "run" + str(r["repeat"]),
          "rubric=" + str(r.get("rubric", {}).get("score")),
          "seconds=" + str(r["elapsed_seconds"]),
          "error=" + str(r.get("error")))
if ok:
    print("mean_rubric:", round(sum(r["rubric"]["score"] for r in ok) / len(ok), 2))
"""


def build_notebook(name, tickers, assignment_runs):
    data = {t: INPUTS["tickers"][t] for t in tickers}
    inputs_cell = (
        "import json, re, time\n"
        "from datetime import datetime, timezone\n\n"
        f"SYSTEM_PROMPT = json.loads({json.dumps(INPUTS['system_prompt'], ensure_ascii=False)!r})\n"
        f"DATA = json.loads({json.dumps(data, ensure_ascii=False)!r})\n"
        f"PARAMS = {json.dumps(INPUTS['params'])}\n"
        f"MODEL_LABEL = {json.dumps(MODEL_LABEL)}\n"
        "RESULTS = []\n\n"
        + SCORE_SRC
        + RUN_ONE_SRC
    )
    cells = [
        md(f"# P0 14B eval — Colab T4 runtime {name}\n\n"
           "Remaining runs of the P0 14B eval (60 runs total; 5 done on the HF "
           "Space, ZeroGPU quota exhausted). Model Qwen2.5-14B-Instruct 4-bit "
           "NF4 double-quant float16, temperature 0.1, top_p 0.75, top_k 40, "
           "max_new_tokens 1200 — identical measurement to the Space runs. "
           "Cutoff 2026-04-07, horizon 20 sessions.\n\n"
           f"Tickers: {', '.join(tickers)} — {len(assignment_runs)} runs."),
        code(CHECK_CELL),
        code(PIP_CELL),
        code(LOAD_CELL),
        code(inputs_cell),
    ]
    for ticker, repeats in assignment_runs:
        cells.append(code("\n".join(f'run_one("{ticker}", {n})' for n in repeats) + "\n"))
    cells.append(code(SUMMARY_CELL))
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "accelerator": "GPU",
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def main():
    runs_a = [("VHM", [3])] + [(t, [1, 2, 3]) for t in RUN_A_TICKERS[1:]]
    runs_b = [(t, [1, 2, 3]) for t in RUN_B_TICKERS]
    assert sum(len(r) for _, r in runs_a) == 28
    assert sum(len(r) for _, r in runs_b) == 27
    for name, tickers, runs in (("A", RUN_A_TICKERS, runs_a), ("B", RUN_B_TICKERS, runs_b)):
        nb = build_notebook(name, tickers, runs)
        out = ROOT / "notebooks" / f"p0_eval14b_colab_{name.lower()}.ipynb"
        out.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n")
        # Validate: parses as nbformat, and the inputs cell executes standalone
        # (syntax check only — no model needed).
        import nbformat
        nbformat.read(str(out), as_version=4)
        for cell in nb["cells"]:
            if cell["cell_type"] == "code":
                # IPython shell escapes (!cmd) are valid in Jupyter, not in
                # plain compile() — drop those lines for the syntax check.
                src = "\n".join(l for l in "".join(cell["source"]).splitlines()
                                 if not l.startswith("!"))
                compile(src, "<cell>", "exec")
        print(f"wrote {out} ({out.stat().st_size} bytes, {len(nb['cells'])} cells)")


if __name__ == "__main__":
    main()
