"""Launch the isolated, authenticated GPU explanation service on Elice."""
import argparse
import json
import os
from pathlib import Path
import socket

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, default=Path.home() / "codex-bench-20261123")
parser.add_argument("--port", type=int, default=18091)
parser.add_argument("--api-key-file", type=Path)
args = parser.parse_args()
if not 1 <= args.port <= 65535:
    parser.error("Invalid port")
root = args.root.resolve()
configuration = json.loads((root / "portable_runtime.json").read_text())
if "cuda_compat" not in configuration:
    parser.error("The verified CUDA compatibility configuration is missing")
key_file = (args.api_key_file or root / "benchmark-api-key.txt").resolve()
if not key_file.is_file() or not key_file.read_text().strip():
    parser.error("A nonempty private API key file is required")
key_file.chmod(0o600)
with socket.socket() as check:
    try:
        check.bind(("127.0.0.1", args.port))
    except OSError:
        parser.error("The requested local port is already occupied")
prefix = configuration["command_prefix"]
command = prefix + ["--model", str(root / "Qwen3.5-4B-Q4_K_M.gguf"),
    "--host", "127.0.0.1", "--port", str(args.port), "--ctx-size", "4096",
    "--parallel", "1", "--threads", "2", "--threads-batch", "2",
    "--n-gpu-layers", "999", "--cache-ram", "128", "--no-webui", "--no-slots",
    "--api-key-file", str(key_file)]
os.chdir(Path(prefix[-1]).parent)
os.execv(prefix[0], command)
