#!/usr/bin/env python3
"""Chain P2 training through the night: when the latest run-colab run finishes,
dispatch the next 50-step session resuming from the newest COMPLETE HF checkpoint.
Silent when the run is still going or a follow-up was already dispatched.
Uses the proven github_api.py helper (LangTieu PAT) + HfApi. No gh CLI needed."""
import importlib.util, json, os, re, sys

GOAL = os.path.expanduser("~/workspace/goals/vietnam-stock-ai-model-qwen2-5/hidden_files/p2-full-training")
STATE = os.path.join(GOAL, "chain_state.json")
REPO = "LangTieu/vn-stock-ai"
CKPT_REPO = "Jerlob/vn-stock-ai-p2a-checkpoints"
REQUIRED = {"optimizer.pt", "scheduler.pt", "trainer_state.json", "rng_state.pth", "adapter_config.json"}
ADAPTER = {"adapter_model.safetensors", "adapter_model.bin"}

def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"chained_from": None, "dispatched": []}

def save_state(s):
    json.dump(s, open(STATE, "w"), indent=2)

def gh():
    spec = importlib.util.spec_from_file_location("gh", os.path.expanduser("~/workspace/custom-connectors/custom.github/bin/github_api.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

def body(p):
    return p.get("body", p)

def latest_complete_checkpoint():
    from huggingface_hub import HfApi
    tok = open(os.path.expanduser("~/.hf_token")).read().strip()
    api = HfApi(token=tok)
    files = api.list_repo_files(CKPT_REPO)
    contents = {}
    for f in files:
        m = re.fullmatch(r"checkpoints/(checkpoint-(\d+))/(.+)", f)
        if m:
            contents.setdefault((int(m.group(2)), m.group(1)), set()).add(m.group(3))
    complete = sorted((step, name) for (step, name), paths in contents.items()
                      if REQUIRED <= paths and paths & ADAPTER)
    return complete[-1] if complete else (None, None)

def main():
    g = gh()
    # latest run on the run-colab workflow
    s, p = g.call("GET", f"/repos/{REPO}/actions/workflows/run-colab.yml/runs?per_page=1")
    runs = body(p).get("workflow_runs", [])
    if not runs:
        print("no runs found"); return
    run = runs[0]
    rid, status, conclusion = run["id"], run["status"], run.get("conclusion")
    print(f"latest run {rid}: status={status} conclusion={conclusion}")
    if status != "completed":
        print("still running/queued; nothing to do"); return
    st = load_state()
    if st.get("chained_from") == rid:
        print(f"already chained from run {rid}; nothing to do"); return
    # run finished: find latest complete checkpoint and dispatch next 50 steps
    step, name = latest_complete_checkpoint()
    if step is None:
        print("NO complete checkpoint on HF; cannot resume. Manual check needed."); return
    next_max = step + 50
    payload = {"ref": "main", "inputs": {
        "notebook": "notebooks/p2a_train.ipynb", "mode": "full", "executor": "lv1",
        "gpu": "T4", "timeout": "28800", "max_steps": str(next_max),
        "save_steps": "25", "resume_checkpoint": name,
        "download_remote": "/content/p2a-checkpoints/full",
        "download_local": "p2a-output-full.zip", "runner": "colab-driver"}}
    s2, p2 = g.call("POST", f"/repos/{REPO}/actions/workflows/run-colab.yml/dispatches", body=payload)
    print(f"dispatch status={s2} resume={name} max_steps={next_max} (run {rid} {conclusion})")
    if s2 in (201, 204):
        st["chained_from"] = rid
        st.setdefault("dispatched", []).append({"from_run": rid, "conclusion": conclusion,
            "resume": name, "max_steps": next_max, "dispatch_status": s2})
        save_state(st)
        print("CHAINED OK")
    else:
        print("DISPATCH FAILED:", json.dumps(body(p2))[:300])

if __name__ == "__main__":
    main()
