#!/usr/bin/env python3
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
source = Path(args.source)
output = Path(args.output)
settings = json.loads(source.read_text())
providers = settings["providers"]

for name in ("Sol", "Astra", "Luna"):
    old_model = f"vn-stock-fosta-{name.lower()}"
    new_model = f"vn-stock-fosta2-{name.lower()}"
    display_name = f"FOSTA2 {name} (Router)"
    provider_id, provider = next(
        (pid, provider)
        for pid, provider in providers.items()
        if any(model.get("model") == old_model for model in provider.get("models", []))
    )
    alias_id = provider_id + "-fosta2"
    if alias_id in providers:
        continue
    alias = deepcopy(provider)
    model = next(model for model in alias["models"] if model.get("model") == old_model)
    alias["displayName"] = display_name
    alias["model"] = new_model
    model["model"] = new_model
    model["displayName"] = display_name
    alias["models"] = [model]
    providers[alias_id] = alias

with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
    handle.write(json.dumps(settings, indent=2) + "\n")
