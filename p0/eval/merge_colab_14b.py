#!/usr/bin/env python3
"""Merge the 55 Colab T4 raw records into the P0 14B eval.

Reads raw14b_A_extracted.json + raw14b_B_extracted.json (the RAW14B lines
from both colab_result.json artifacts), verifies every record against
p0/eval/colab_inputs_14b.json and the A/B assignment, writes the 55
raw_14b_<TICKER>_run<N>.json files (never overwriting the 5 Space files),
appends them to manifest_14b.json, and regenerates results_14b.json over
ALL 60 runs using the same summarize logic as p0/eval/run_eval_14b.py.
"""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "p0" / "eval"
MODEL_LABEL = "Qwen/Qwen2.5-14B-Instruct (Colab T4)"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_eval = _load("run_eval_mod_merge", EVAL / "run_eval.py")
parse_json = run_eval.parse_json
outcome = run_eval.outcome
read_json = run_eval.read_json


def main():
    inputs = json.loads((EVAL / "colab_inputs_14b.json").read_text())
    manifest = json.loads((EVAL / "manifest_14b.json").read_text())
    done = {(x["ticker"], x["repeat"]) for x in manifest["outputs"]}
    assert len(done) == 5, f"expected 5 done Space runs, got {len(done)}"

    recs = []
    for f in ("raw14b_A_extracted.json", "raw14b_B_extracted.json"):
        recs.extend(json.loads((ROOT / f).read_text()))
    assert len(recs) == 55, f"expected 55 Colab records, got {len(recs)}"

    # Verify each record against the assignment + inputs, then write the file.
    expected = {(t, n) for t, runs in
                (("A", inputs["assignment"]["A"]["runs"]),
                 ("B", inputs["assignment"]["B"]["runs"]))
                for t, n in runs}
    assert len(expected) == 55
    seen = set()
    for r in recs:
        key = (r["ticker"], r["repeat"])
        assert key in expected, f"unexpected record {key}"
        assert key not in seen, f"duplicate record {key}"
        assert key not in done, f"would overwrite a Space run {key}"
        assert "rubric" in r and not r.get("error"), f"record {key} has no rubric / has error"
        assert r["model"] == MODEL_LABEL and r["model_group"] == "space-14b"
        assert r["input_hash"] == inputs["tickers"][r["ticker"]]["input_hash"]
        assert r["params"] == inputs["params"]
        seen.add(key)
        path = EVAL / f"raw_14b_{r['ticker']}_run{r['repeat']}.json"
        assert not path.exists(), f"refusing to overwrite {path.name}"
        path.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n")

    # Append to the manifest in the canonical ticker order (VHM run3 first,
    # then the 18 tickers in manifest order, 3 repeats each).
    order = manifest["tickers"]
    appended = sorted(seen, key=lambda k: (order.index(k[0]), k[1]))
    for t, n in appended:
        manifest["outputs"].append({
            "ticker": t, "repeat": n,
            "file": f"raw_14b_{t}_run{n}.json",
            "model": MODEL_LABEL, "error": None,
        })
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    (EVAL / "manifest_14b.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["outputs"]) == 60
    print(f"wrote 55 raw files; manifest now has {len(manifest['outputs'])} outputs")

    # Summarize over ALL 60 runs — same logic as run_eval_14b.py.
    rank = read_json("inputs/bot-data/stock_rank.json")[:20]
    ref = []
    for item in rank:
        t = item["code"]
        records = []
        for n in range(1, 4):
            p = EVAL / f"raw_14b_{t}_run{n}.json"
            if p.exists():
                records.append(json.loads(p.read_text()))
        valid = [r for r in records if "rubric" in r]
        stock_out = records[0]["stock_outcome_20"] if records else None
        idx_out = records[0]["vnindex_outcome_20"] if records else None
        ref.append({
            "ticker": t, "repeat_count": len(records),
            "model_runs": sorted(set(r.get("actual_model") for r in valid)),
            "mean_rubric": round(sum(r["rubric"]["score"] for r in valid) / len(valid), 2) if valid else None,
            "stock_direction_20": stock_out["direction"] if stock_out else None,
            "stock_return_20_pct": stock_out["return_pct"] if stock_out else None,
            "vnindex_direction_20": idx_out["direction"] if idx_out else None,
            "predicted_directions": [r["rubric"]["direction_output"] for r in valid],
            "outputs": [r["rubric"]["direction_output"] for r in valid],
        })
    index_rows = read_json("inputs/bot-data/vnindex_vnstock.json")
    index = outcome(index_rows, "2026-04-07")
    actual_up = index["direction"] == "UP" if index else None
    preds = [r for r in ref for d in r["predicted_directions"] if d in ["UP", "DOWN", "FLAT"]]
    index_hit = sum((d == "UP") == actual_up for d in preds) / len(preds) if preds and actual_up is not None else None
    stock_preds = [(d, r["stock_direction_20"]) for r in ref for d in r["predicted_directions"] if d in ["UP", "DOWN", "FLAT"]]
    stock_hit = sum(d == a for d, a in stock_preds) / len(stock_preds) if stock_preds else None
    valid_records = [json.loads((EVAL / x["file"]).read_text())
                     for x in manifest["outputs"] if not x.get("error")]
    report = {
        "eval_type": "space-14b", "model": manifest["model"],
        "cutoff": manifest["cutoff"], "horizon_sessions": manifest["horizon_sessions"],
        "index_outcome": index, "index_direction_hit_rate": index_hit,
        "index_direction_predictions_n": len(preds),
        "stock_direction_hit_rate": stock_hit,
        "stock_direction_predictions_n": len(stock_preds),
        "direction_coverage": {
            "directional_n": len(preds),
            "unknown_n": len(valid_records) - len(preds),
            "total_n": len(valid_records),
            "directional_fraction": len(preds) / len(valid_records) if valid_records else None,
        },
        "recommendation_counts": {
            name: sum(parse_json(r.get("content")).get("recommendation") == name for r in valid_records)
            for name in ["BUY", "WAIT", "REDUCE", "ABSTAIN"]
        },
        "rubric_mean": round(sum(r["rubric"]["score"] for r in valid_records) / len(valid_records), 2) if valid_records else None,
        "rubric_max": 10,
        "rubric_method": "Automated heuristic checks; not human adjudication or comparison to absent bot-analysis prose",
        "symbols_evaluated": [r["ticker"] for r in ref if r["repeat_count"]],
        "symbols_with_model_output": [r["ticker"] for r in ref if r["model_runs"]],
        "per_ticker": ref,
        "outputs_recorded": len(manifest["outputs"]),
        "quota_stopped": False,
        "platforms": {"space": 5, "colab_t4": 55},
        "model_runs": sorted(set(r.get("actual_model") for r in valid_records)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (EVAL / "results_14b.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("SUMMARY-14B-MERGED", json.dumps({
        "count_outputs": report["outputs_recorded"],
        "symbols": report["symbols_with_model_output"],
        "index_direction_hit_rate": index_hit,
        "index_predictions_n": len(preds),
        "stock_direction_hit_rate": stock_hit,
        "stock_predictions_n": len(stock_preds),
        "rubric_mean": report["rubric_mean"],
        "recommendation_counts": report["recommendation_counts"],
        "direction_coverage": report["direction_coverage"],
        "platforms": report["platforms"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
