#!/usr/bin/env python3
"""CLI fallback wrapper using the same isolated NVIDIA/Ubuntu compatibility libraries."""
import json
import os
from pathlib import Path
import sys

root = Path(os.getenv("KM_CDSS_RUNTIME_ROOT", str(Path.home() / "codex-bench-20261123")))
configuration = json.loads((root / "portable_runtime.json").read_text())
command = list(configuration["command_prefix"])
completion = Path(command[-1]).with_name("llama-completion")
if not completion.is_file():
    raise SystemExit("The pinned completion executable is missing")
command[-1] = str(completion)
command += ["--n-gpu-layers", "999", "--threads", "2", "--threads-batch", "2"] + sys.argv[1:]
os.chdir(completion.parent)
os.execv(command[0], command)
