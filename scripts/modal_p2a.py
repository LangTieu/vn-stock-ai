#!/usr/bin/env python3
"""Port Modal cho p2a_train.py: smoke 2 step tren T4.

Tai su dung logic train tu p2a_train.py (cung ham loss, LabelTrainer,
TrainingArguments). Khong viet lai trainer.
"""

import json
import os
import time
from pathlib import Path

import modal

APP_NAME = "p2a-train"
VOLUME_NAME = "p2-train-vol"
VOLUME_MOUNT = "/vol"

app = modal.App(APP_NAME)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("build-essential")
    .pip_install(
        "torch==2.5.1",
        index_url="https://download.pytorch.org/whl/cu124",
    )
    .pip_install(
        "transformers==4.51.3",
        "peft==0.15.2",
        "bitsandbytes==0.48.2",
        "accelerate==1.6.0",
        "liger-kernel==0.6.0",
        "datasets==3.5.0",
        "huggingface_hub==0.30.2",
        "jinja2==3.1.6",
    )
    .add_local_file(Path(__file__).parent / "p2a_train.py", "/workspace/p2a_train.py")
    .add_local_file(Path(__file__).parent / "p2a_eval.py", "/workspace/p2a_eval.py")
)

volume = modal.Volume.from_name(VOLUME_NAME)


@app.function(
    image=image,
    gpu="T4",
    volumes={VOLUME_MOUNT: volume},
    timeout=5400,
    memory=32000,
    env={"HF_HOME": "/vol/hf-cache", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
)
def smoke_train(
    output_dir: str = "/vol/p2a-checkpoints-smoke",
    resume: str = "",
    max_steps: int = 2,
):
    import hashlib
    import subprocess
    import sys

    import torch

    print("GPU_NAME", torch.cuda.get_device_name(0), flush=True)
    print("GPU_CAPABILITY", torch.cuda.get_device_capability(0), flush=True)
    print("TORCH", torch.__version__, "CUDA", torch.version.cuda, flush=True)

    vol = Path(VOLUME_MOUNT)
    tar_path = vol / "p1-dataset.tar.gz"
    print("VOLUME_LS", sorted(p.name for p in vol.iterdir()), flush=True)
    print("TAR_SIZE", tar_path.stat().st_size, flush=True)

    digest = hashlib.sha256()
    with open(tar_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    sha = digest.hexdigest()
    print("VOLUME_TAR_SHA256", sha, flush=True)
    expected = "8839f5d8c2ce637ce46e1ff83f5fb635107c73054809b6cb756dee8811b72aec"
    print("SHA_MATCH", sha == expected, flush=True)
    if sha != expected:
        raise ValueError(f"sha256 trong Volume mismatch: {sha} != {expected}")

    dataset_dir = vol / "dataset"
    dataset_dir.mkdir(exist_ok=True)
    train_file = dataset_dir / "p1-dataset" / "p1" / "train.jsonl"
    if not train_file.exists():
        print("EXTRACT_START", flush=True)
        res = subprocess.run(
            ["tar", "xzf", str(tar_path), "-C", str(dataset_dir)],
            capture_output=True, text=True,
        )
        print("EXTRACT_EXIT", res.returncode, flush=True)
        if res.stderr:
            print("EXTRACT_STDERR_TAIL", res.stderr[-2000:], flush=True)
        if res.returncode != 0:
            raise RuntimeError("tar xzf failed")
    else:
        print("EXTRACT_SKIPPED already present", flush=True)

    for rel, want_md5 in [
        ("p1-dataset/p1/train.jsonl", "f6273e8a12e35fe1027f29ca2127b9c0"),
        ("p1-dataset/p1/holdout.jsonl", "5f48d9b13d2f2cce0a730067b2f3094c"),
        ("p1-dataset/p1/smoke.jsonl", "eeb4faeb32a23d97f474813bac659797"),
    ]:
        f = dataset_dir / rel
        d = hashlib.md5()
        with open(f, "rb") as fh:
            for ch in iter(lambda: fh.read(1024 * 1024), b""):
                d.update(ch)
        actual = d.hexdigest()
        print(f"DATASET_FILE {f} size={f.stat().st_size} md5={actual} "
              f"{'PASS' if actual == want_md5 else 'FAIL'} expected={want_md5}", flush=True)

    output_dir = Path(output_dir)
    cmd = [
        sys.executable, "/workspace/p2a_train.py",
        "--train", str(train_file),
        "--output-dir", str(output_dir),
        "--limit", "500",
        "--max-steps", str(max_steps),
        "--save-steps", "1",
    ]
    if resume:
        cmd.extend(["--resume", resume])
    print("RUN_CMD", " ".join(cmd), flush=True)
    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=False)
    elapsed = time.monotonic() - start
    print("TRAIN_EXIT", proc.returncode, "WALL_SECONDS", elapsed, flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"train exit {proc.returncode}")

    prog = output_dir / "progress.jsonl"
    if prog.exists():
        print("PROGRESS_JSONL", flush=True)
        print(prog.read_text()[-8000:], flush=True)
    for d in sorted(output_dir.glob("checkpoint-*")):
        print(f"CHECKPOINT_DIR {d.name}", flush=True)
        for f in sorted(d.iterdir()):
            print(f"  CKPT {f.name} {f.stat().st_size if f.is_file() else '<dir>'}", flush=True)
    adapter_dir = output_dir / "adapter"
    if adapter_dir.exists():
        for f in sorted(adapter_dir.glob("*")):
            if f.is_file():
                print(f"ADAPTER_FILE {f.name} {f.stat().st_size}", flush=True)
                if f.name == "adapter_model.safetensors":
                    d = hashlib.sha256()
                    with open(f, "rb") as fh:
                        for ch in iter(lambda: fh.read(1024 * 1024), b""):
                            d.update(ch)
                    print(f"ADAPTER_SHA256 {d.hexdigest()}", flush=True)
    volume.commit()
    print("VOLUME_COMMITTED", flush=True)
    return {"sha": sha, "wall_seconds": elapsed}


@app.function(
    image=image,
    gpu="T4",
    volumes={VOLUME_MOUNT: volume},
    timeout=5400,
    memory=32000,
    env={"HF_HOME": "/vol/hf-cache", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
)
def eval_adapter(output_dir: str = "/vol/p2a-checkpoints-smoke", limit: int = 20):
    import hashlib
    import subprocess
    import sys

    output_dir = Path(output_dir)
    holdout = Path(VOLUME_MOUNT) / "dataset/p1-dataset/p1/holdout.jsonl"
    eval_output = output_dir / "eval.jsonl"
    cmd = [
        sys.executable, "/workspace/p2a_eval.py",
        "--holdout", str(holdout),
        "--adapter", str(output_dir / "adapter"),
        "--output", str(eval_output),
        "--limit", str(limit),
    ]
    print("RUN_EVAL_CMD", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, capture_output=False)
    print("EVAL_EXIT", proc.returncode, flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"eval exit {proc.returncode}")

    metrics = Path(str(eval_output) + ".metrics.json")
    print("EVAL_METRICS", metrics.read_text(), flush=True)
    digest = hashlib.sha256(eval_output.read_bytes()).hexdigest()
    print("EVAL_JSONL", eval_output, "BYTES", eval_output.stat().st_size,
          "SHA256", digest, flush=True)
    volume.commit()
    print("VOLUME_COMMITTED", flush=True)
    return {"eval_jsonl": str(eval_output), "sha256": digest}


@app.local_entrypoint()
def main(output_dir: str = "/vol/p2a-checkpoints-smoke", resume: str = "", max_steps: int = 2):
    result = smoke_train.remote(output_dir=output_dir, resume=resume, max_steps=max_steps)
    print("RESULT", json.dumps(result), flush=True)
