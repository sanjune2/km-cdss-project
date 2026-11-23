"""Paired CPU/CUDA explanation benchmark on the Elice instance only."""
from copy import deepcopy
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import statistics
import subprocess
import sys
from time import monotonic, sleep
import urllib.request

ROOT = Path.home() / "codex-bench-20261123"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repeats", type=int, default=1)
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()
if sys.platform != "linux":
    parser.error("This benchmark must run on the target Linux Elice instance")
if args.repeats < 1:
    parser.error("At least one repetition is required")
PAYLOAD = ROOT / "payload"
OUTPUT = ROOT / "results"
OUTPUT.mkdir(exist_ok=True)
os.environ["HF_HOME"] = str(PAYLOAD / "hf-cache")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.path.insert(0, str(PAYLOAD))
from ai import explanations as exp
from ai.evidence_checks import verify_candidate

manifest = json.loads((PAYLOAD / "manifest.json").read_text())
for name, digest in manifest["files"].items():
    assert hashlib.sha256((PAYLOAD / name).read_bytes()).hexdigest() == digest, name
fixture = json.loads((PAYLOAD / "fixtures.json").read_text())
catalog = (
    {"prescription": {int(k): v for k, v in fixture["prescriptions"].items()}},
    {("prescription", int(k), "disease"): set(v) for k, v in fixture["links"].items()},
    {int(k): v for k, v in fixture["compositions"].items()},
)
if (ROOT / "built_runtime_manifest.json").exists():
    runtime = json.loads((ROOT / "built_runtime_manifest.json").read_text())
    prefix = [runtime["server"]]
    runtime_label = runtime["commit"]
else:
    runtime = json.loads((ROOT / "portable_runtime.json").read_text())
    prefix = runtime["command_prefix"]
    runtime_label = "official b12640 CUDA 12.8 with isolated Ubuntu and NVIDIA compatibility libraries"
os.environ["KM_CDSS_LLAMA_EXECUTABLE"] = prefix[-1]
os.environ["KM_CDSS_EXPLANATION_MODEL"] = str(ROOT / "Qwen3.5-4B-Q4_K_M.gguf")
key_file = ROOT / "benchmark-api-key.txt"
if not key_file.exists():
    key_file.write_text(secrets.token_urlsafe(32))
key_file.chmod(0o600)
os.environ["KM_CDSS_LLAMA_SERVER_API_KEY"] = key_file.read_text().strip()

report = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
          "scope": "Elice resident explanation stage; not full service or clinical accuracy evaluation",
          "cpu_cores": os.cpu_count(), "runtime": runtime_label, "runtime_configuration": runtime,
          "model_sha256": "217002fa8008ef4fc6d548353a3aebef055a96e6ff8e0e2c0953ef8254a89c14",
          "input_limit": exp.MAX_INPUT_TOKENS, "output_limit": exp.MAX_OUTPUT_TOKENS,
          "call_timeout_seconds": exp.GENERATION_TIMEOUT_SECONDS,
          "prompt_version": exp.PROMPT_VERSION, "tokenizer_revision": exp.TOKENIZER_REVISION,
          "application_cache_cleared_each_case": True, "server_prompt_cache": True,
          "modes": {}, "rows": []}
if args.resume:
    previous = json.loads((OUTPUT / "benchmark.json").read_text())
    if previous["model_sha256"] != report["model_sha256"] or previous["runtime_configuration"] != runtime:
        parser.error("Cannot resume results from a different model or runtime")
    report = previous
elif (OUTPUT / "benchmark.json").exists():
    parser.error("Existing benchmark results require --resume; preserve the original evidence")
report["sampling"] = {"repetitions": args.repeats, "predefined_candidates": len(fixture["cases"]),
                      "note": "one pass over all predefined candidates; validation policy unchanged"}

def save():
    (OUTPUT / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

def cuda_device():
    lib = ctypes.CDLL("libcuda.so.1")
    code = lib.cuInit(0)
    if code:
        return {"initialization_code": code}
    count = ctypes.c_int()
    lib.cuDeviceGetCount(ctypes.byref(count))
    name = ctypes.create_string_buffer(256)
    lib.cuDeviceGetName(name, 256, 0)
    memory = ctypes.c_size_t()
    result = lib.cuDeviceTotalMem_v2(ctypes.byref(memory), 0)
    return {"devices": count.value, "name": name.value.decode(),
            "memory_query_code": result, "allocated_memory_mib": memory.value / 1024**2}

report["cuda_device"] = cuda_device()
report["gpu_listing"] = subprocess.check_output(["nvidia-smi", "-L"], text=True)
save()
exp.explanation_tokenizer()

for mode in ("cpu", "gpu"):
    if all(any(row["mode"] == mode and row["repeat"] == repeat + 1 and row["candidate_id"] == case["candidate"]["id"]
               for row in report["rows"]) for repeat in range(args.repeats) for case in fixture["cases"]):
        continue
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    os.environ["KM_CDSS_LLAMA_SERVER_URL"] = f"http://127.0.0.1:{port}"
    command = prefix + ["--model", os.environ["KM_CDSS_EXPLANATION_MODEL"], "--host", "127.0.0.1",
        "--port", str(port), "--ctx-size", "4096", "--parallel", "1", "--threads", "2", "--threads-batch", "2",
        "--batch-size", "512", "--ubatch-size", "512", "--no-webui", "--no-slots", "--cache-ram", "0",
        "--api-key-file", str(key_file), "-lv", "4", "--n-gpu-layers", "0" if mode == "cpu" else "999"]
    if mode == "cpu":
        command += ["--device", "none"]
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = "/usr/local/cuda-12.8/lib64:" + environment.get("LD_LIBRARY_PATH", "")
    log_path = OUTPUT / (mode + "-server.log")
    with log_path.open("w") as log:
        started = monotonic()
        process = subprocess.Popen(command, cwd=Path(prefix[-1]).parent, stdout=log, stderr=log, env=environment, start_new_session=True)
        try:
            while monotonic() - started < 360:
                if process.poll() is not None:
                    raise RuntimeError(mode + " server exited; inspect its isolated log")
                try:
                    with urllib.request.urlopen(os.environ["KM_CDSS_LLAMA_SERVER_URL"] + "/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except Exception:
                    sleep(0.2)
            else:
                raise TimeoutError(mode + " server did not become ready")
            metadata = {"model_ready_seconds": round(monotonic() - started, 3), "port": port}
            text = log_path.read_text(errors="replace")
            offload = re.findall(r"offloaded (\d+)/(\d+) layers", text)
            metadata["offloaded_layers"] = offload[-1] if offload else None
            metadata["gpu_buffers"] = [line for line in text.splitlines() if "CUDA" in line and "buffer size" in line]
            if mode == "gpu" and (not offload or int(offload[-1][0]) == 0):
                raise RuntimeError("CUDA offload was not verified")
            report["modes"][mode] = metadata
            save()
            print(json.dumps({"mode": mode, **metadata}), flush=True)
            stop_mode = False
            for repeat in range(args.repeats):
                for case in fixture["cases"]:
                    candidate = deepcopy(case["candidate"])
                    if any(row["mode"] == mode and row["repeat"] == repeat + 1 and row["candidate_id"] == candidate["id"] for row in report["rows"]):
                        continue
                    checks = verify_candidate(fixture["search"], candidate, fixture["runtime"], catalog)
                    assert checks == case["verified_checks"]
                    with exp._cache_lock:
                        exp._completion_cache.clear()
                    t0 = monotonic()
                    result, trace = exp.explain(candidate, case["terms"], lambda: False, checks=checks)
                    row = {"mode": mode, "repeat": repeat + 1, "candidate_id": candidate["id"],
                           "seconds": round(monotonic() - t0, 3), "status": result["status"],
                           "generation": trace.get("generationMetrics"), "review": trace.get("reviewMetrics"),
                           "checks": trace["checks"], "failure_type": trace.get("failureType"),
                           "failure_reason": trace.get("failureReason")}
                    report["rows"].append(row)
                    save()
                    (OUTPUT / f'{mode}-{repeat + 1}-{candidate["id"]}.json').write_text(
                        json.dumps({"result": result, "trace": trace}, ensure_ascii=False, indent=2) + "\n")
                    print(json.dumps({k: row[k] for k in ("mode", "repeat", "candidate_id", "seconds", "status", "failure_type")}), flush=True)
                    if trace.get("failureType") in ("TimeoutError", "ReadTimeout"):
                        stop_mode = True
                        break
                if stop_mode:
                    break
            if report["rows"][-1]["status"] == "READY":
                t0 = monotonic()
                warmed, trace = exp.explain(candidate, case["terms"], lambda: False, checks=checks)
                report["modes"][mode]["warm_application_cache"] = {
                    "seconds": round(monotonic() - t0, 6), "status": warmed["status"],
                    "generation_cache_hit": trace.get("generationMetrics", {}).get("cacheHit", False),
                    "review_cache_hit": trace.get("reviewMetrics", {}).get("cacheHit", False)}
                save()
        except Exception as error:
            report["modes"].setdefault(mode, {})["error_type"] = type(error).__name__
            report["modes"][mode]["error"] = str(error)
            save()
            print(json.dumps({"mode": mode, "error_type": type(error).__name__, "error": str(error)}), flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

paired = []
for cpu in (r for r in report["rows"] if r["mode"] == "cpu" and r["status"] == "READY"):
    gpu = next((g for g in report["rows"] if g["mode"] == "gpu" and g["status"] == "READY"
                and (g["repeat"], g["candidate_id"]) == (cpu["repeat"], cpu["candidate_id"])), None)
    if gpu:
        paired.append((cpu["seconds"], gpu["seconds"]))
if paired:
    cpu_median = statistics.median(c for c, g in paired)
    gpu_median = statistics.median(g for c, g in paired)
    report["comparison"] = {"paired_successes": len(paired), "cpu_median_seconds": cpu_median,
        "gpu_median_seconds": gpu_median, "median_latency_speedup": cpu_median / gpu_median,
        "median_latency_reduction_percent": 100 * (1 - gpu_median / cpu_median)}
report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
save()
print("BENCHMARK_COMPLETE " + json.dumps(report.get("comparison", {})), flush=True)
