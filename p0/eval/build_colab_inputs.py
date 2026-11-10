#!/usr/bin/env python3
"""Build the Colab eval inputs for the remaining 55 runs of the P0 14B eval.

Rebuilds the 20-ticker ref list EXACTLY like p0/eval/run_eval_14b.py
(same cutoff 2026-04-07, same PARAMS, same model_group "space-14b",
same sha() definition), then writes p0/eval/colab_inputs_14b.json with
the 19 tickers still missing (VHM + 18) + the A/B runtime assignment.

Sanity checks (must both pass before writing):
  1. VCB prompt reproduced: sha({prompt, model_group "vn-stock",
     params incl. reasoning_effort}) == c4400d29... (recorded in
     p0/eval/raw_VCB_run1.json / inputs/README.md).
  2. The 5 done Space runs: recomputed 14B input_hash matches the stored
     input_hash in each raw_14b_*.json (HDB x3, VHM x1/x2).
"""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "p0" / "eval"
CUTOFF = "2026-04-07"
HORIZON = 20
PARAMS = {"temperature": 0.1, "top_p": 0.75, "top_k": 40, "max_tokens": 1200}
PARAMS_VNSTOCK = dict(PARAMS, reasoning_effort="none")
VCB_HASH_RECORDED = "c4400d2964cf17edb5b3cb42a985d54ea1c84fb1445c20dce73e40316ce8e71d"

# Runtime A (TK1/IB1): VHM run3 + 9 tickers x 3 = 28 runs.
RUN_A = ["VHM", "CTG", "ACB", "STB", "MBB", "HCM", "VCB", "MWG", "FRT", "PVT"]
# Runtime B (TK2/IB2): 9 tickers x 3 = 27 runs.
RUN_B = ["HPG", "HVN", "VCI", "TCB", "KDH", "NVL", "BID", "VPB", "VJC"]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


snapshot = _load("p0_snapshot_colab", ROOT / "p0" / "snapshot.py")
run_eval = _load("run_eval_mod_colab", EVAL / "run_eval.py")
outcome = run_eval.outcome
read_json = run_eval.read_json
sha = run_eval.sha


def main():
    rank = read_json("inputs/bot-data/stock_rank.json")[:20]
    stocks = read_json("inputs/bot-data/stocks_vnstock.json")
    idx = read_json("inputs/bot-data/vnindex_vnstock.json")
    ref = []
    for item in rank:
        t = item["code"]
        future = outcome(stocks[t], CUTOFF)
        snap = snapshot.build(t, CUTOFF)
        if future is None:
            continue
        prompt = snapshot.prompt(snap)
        ihash = sha({"prompt": prompt, "model_group": "space-14b", "params": PARAMS})
        ref.append({
            "ticker": t, "snapshot": snap,
            "prompt": prompt,
            "prompt_user": prompt[1]["content"],
            "input_hash": ihash,
            "stock_outcome": future,
            "index_outcome": outcome(idx, CUTOFF),
        })
    tickers = [x["ticker"] for x in ref]
    manifest = json.loads((EVAL / "manifest_14b.json").read_text())
    assert tickers == manifest["tickers"], f"ticker order mismatch: {tickers} vs {manifest['tickers']}"
    print("tickers OK (20):", ", ".join(tickers))

    # Sanity check 1: VCB prompt reproduction (vn-stock hash def).
    vcb = next(x for x in ref if x["ticker"] == "VCB")
    vcb_vn_hash = sha({"prompt": vcb["prompt"], "model_group": "vn-stock",
                       "params": PARAMS_VNSTOCK})
    assert vcb_vn_hash == VCB_HASH_RECORDED, f"VCB vn-stock hash mismatch: {vcb_vn_hash}"
    print("VCB prompt-hash check PASS:", vcb_vn_hash[:12], "...")

    # Sanity check 2: the 5 done Space runs' input_hashes reproduce exactly.
    for f in sorted((EVAL).glob("raw_14b_*.json")):
        raw = json.loads(f.read_text())
        item = next(x for x in ref if x["ticker"] == raw["ticker"])
        assert item["input_hash"] == raw["input_hash"], \
            f"{f.name}: recomputed {item['input_hash']} != stored {raw['input_hash']}"
        print(f"  {f.name}: input_hash MATCH {raw['input_hash'][:12]}...")
    print("Space input_hash check PASS (5/5 done runs)")

    # Remaining: VHM run3 + 18 tickers x 3 = 55 runs.
    by_ticker = {x["ticker"]: x for x in ref}
    assert set(RUN_A) | set(RUN_B) == set(tickers) - {"HDB"}, "assignment must cover all except HDB"
    assert not (set(RUN_A) & set(RUN_B)), "A/B overlap"
    system = (ROOT / "p0" / "system_prompt.txt").read_text()
    assert by_ticker["VHM"]["prompt"][0]["content"] == system

    def entry(t):
        x = by_ticker[t]
        return {"ticker": t, "snapshot": x["snapshot"],
                "prompt_user": x["prompt_user"],
                "input_hash": x["input_hash"],
                "stock_outcome": x["stock_outcome"],
                "index_outcome": x["index_outcome"]}

    runs_a = [("VHM", 3)] + [(t, n) for t in RUN_A[1:] for n in (1, 2, 3)]
    runs_b = [(t, n) for t in RUN_B for n in (1, 2, 3)]
    assert len(runs_a) == 28 and len(runs_b) == 27, (len(runs_a), len(runs_b))
    payload = {
        "cutoff": CUTOFF, "horizon_sessions": HORIZON,
        "model": "Qwen/Qwen2.5-14B-Instruct (Colab T4)",
        "model_group": "space-14b", "params": PARAMS,
        "system_prompt": system,
        "tickers": {t: entry(t) for t in RUN_A + RUN_B},
        "assignment": {
            "A": {"runner": "colab-driver", "runs": [list(r) for r in runs_a]},
            "B": {"runner": "colab-driver-tk2", "runs": [list(r) for r in runs_b]},
        },
    }
    out = EVAL / "colab_inputs_14b.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"runtime A: {len(runs_a)} runs, runtime B: {len(runs_b)} runs, total 55")


if __name__ == "__main__":
    main()
