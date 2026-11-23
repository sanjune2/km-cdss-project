"""Prepare an isolated CUDA runtime for the verified Elice A100 MIG / driver 535 host.

No system packages, drivers, application files or public ports are modified.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import tarfile
import urllib.request

MODEL_SHA = "217002fa8008ef4fc6d548353a3aebef055a96e6ff8e0e2c0953ef8254a89c14"
RUNTIME_SHA = "8c8fe406139995bac125757f28ac09661c25f5bb7b5a69f9aa3e5f659f779287"
UBUNTU_PACKAGES = {
    "libc6": ("2.39-0ubuntu8.12", "d821b41fc59cb4978ecd53bc83e5c964ac15d305c8d2ac4c8a35aebe55010fb9"),
    "libgcc-s1": ("14.2.0-4ubuntu2~24.04.1", "aa7fadbe33b78bcf99885318040601c550c208929565b179891d9a3cc2aa68cd"),
    "libgomp1": ("14.2.0-4ubuntu2~24.04.1", "e8a95ec58125b4933597f30ff56c2ae10edf90f287262e366d4b6edea3019144"),
    "libstdc++6": ("14.2.0-4ubuntu2~24.04.1", "a51f8de7829211db961a31f02158058ad1a95f92ac6d0a5dff6350e2821c54c0"),
}
CUDA_COMPAT_VERSION = "570.211.01-0ubuntu1"
CUDA_COMPAT_SHA = "4363d39d2fcec488e03d5aaac13ba7e775e60ccfb2b4bc22bf9a407510681493"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, target, digest):
    if target.exists():
        if sha(target) != digest:
            raise RuntimeError("Existing file SHA-256 mismatch: " + target.name)
        return
    partial = target.with_suffix(target.suffix + ".download")
    urllib.request.urlretrieve(url, partial)
    if sha(partial) != digest:
        raise RuntimeError("Downloaded file SHA-256 mismatch: " + target.name)
    partial.rename(target)


def package_index(url):
    data = gzip.decompress(urllib.request.urlopen(url, timeout=60).read()).decode()
    for block in data.split("\n\n"):
        yield dict(line.split(": ", 1) for line in block.splitlines()
                   if ": " in line and not line.startswith(" "))


def extract_runtime(archive, destination):
    destination.mkdir(exist_ok=True)
    boundary = destination.resolve()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(boundary):
                raise RuntimeError("Unsafe archive member")
            if member.issym() or member.islnk():
                link = ((target.parent if member.issym() else destination) / member.linkname).resolve()
                if not link.is_relative_to(boundary):
                    raise RuntimeError("Unsafe archive link")
        tar.extractall(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / "codex-bench-20261123")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("Run this on the target Elice Linux instance, not a local Windows PC")
    devices = subprocess.check_output(["nvidia-smi", "-L"], text=True)
    driver = subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True).strip()
    if "A100" not in devices or "MIG 1g.10gb" not in devices or not driver.startswith("535."):
        parser.error("This configuration was verified only for A100 MIG 1g.10gb with driver 535")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    model = root / "Qwen3.5-4B-Q4_K_M.gguf"
    if args.verify_only:
        if not model.is_file() or sha(model) != MODEL_SHA:
            raise RuntimeError("Pinned model verification failed")
        archive = root / "llama-b12640-bin-ubuntu-cuda-12.8-x64.tar.gz"
        if not archive.is_file() or sha(archive) != RUNTIME_SHA:
            raise RuntimeError("Pinned runtime archive verification failed")
        manifest = json.loads((root / "portable_runtime.json").read_text())
        if manifest.get("cuda_compat", {}).get("sha256") != CUDA_COMPAT_SHA:
            raise RuntimeError("CUDA compatibility configuration mismatch")
    else:
        download("https://huggingface.co/ggml-org/Qwen3.5-4B-GGUF/resolve/main/" + model.name, model, MODEL_SHA)
        archive = root / "llama-b12640-bin-ubuntu-cuda-12.8-x64.tar.gz"
        download("https://github.com/ggml-org/llama.cpp/releases/download/b12640/" + archive.name, archive, RUNTIME_SHA)
        extract_runtime(archive, root / "runtime")
        ubuntu = "https://archive.ubuntu.com/ubuntu/"
        selected = {p["Package"]: p for p in package_index(ubuntu + "dists/noble-updates/main/binary-amd64/Packages.gz")
                    if p.get("Package") in UBUNTU_PACKAGES
                    and p.get("Version") == UBUNTU_PACKAGES[p["Package"]][0]}
        if selected.keys() != UBUNTU_PACKAGES.keys():
            raise RuntimeError("Pinned Ubuntu packages are no longer in the index; review instead of silently upgrading")
        library_root = root / "compat-libs"
        library_root.mkdir(exist_ok=True)
        packages = []
        for name, row in selected.items():
            digest = UBUNTU_PACKAGES[name][1]
            if row["SHA256"] != digest:
                raise RuntimeError("Ubuntu package metadata mismatch")
            package = root / Path(row["Filename"]).name
            download(ubuntu + row["Filename"], package, digest)
            subprocess.run(["dpkg-deb", "-x", str(package), str(library_root)], check=True)
            packages.append({"package": name, "version": row["Version"], "sha256": digest})
        nvidia = "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/"
        selected_cuda = next(p for p in package_index(nvidia + "Packages.gz")
                             if p.get("Package") == "cuda-compat-12-8" and p.get("Version") == CUDA_COMPAT_VERSION)
        if selected_cuda["SHA256"] != CUDA_COMPAT_SHA:
            raise RuntimeError("NVIDIA package metadata mismatch")
        package = root / Path(selected_cuda["Filename"]).name
        download(nvidia + selected_cuda["Filename"].lstrip("./"), package, CUDA_COMPAT_SHA)
        cuda_root = root / "cuda-compat"
        cuda_root.mkdir(exist_ok=True)
        subprocess.run(["dpkg-deb", "-x", str(package), str(cuda_root)], check=True)
        cuda_path = cuda_root / "usr/local/cuda-12.8/compat"
        server = root / "runtime/llama-b12640/llama-server"
        loader = next(library_root.rglob("ld-linux-x86-64.so.2"))
        libraries = ":".join((str(cuda_path), str(library_root / "usr/lib/x86_64-linux-gnu"),
                              str(server.parent), "/usr/local/cuda-12.8/lib64", "/usr/lib/x86_64-linux-gnu"))
        manifest = {"command_prefix": [str(loader), "--library-path", libraries, str(server)], "packages": packages,
                    "cuda_compat": {"version": CUDA_COMPAT_VERSION, "sha256": CUDA_COMPAT_SHA, "path": str(cuda_path)}}
        (root / "portable_runtime.json").write_text(json.dumps(manifest, indent=2))
        key = root / "benchmark-api-key.txt"
        if not key.exists():
            key.write_text(secrets.token_urlsafe(32))
        key.chmod(0o600)
        wrapper_source = Path(__file__).with_name("elice_llama_completion.py")
        if wrapper_source.is_file():
            wrapper = root / "llama-completion-gpu"
            wrapper.write_bytes(wrapper_source.read_bytes())
            wrapper.chmod(0o700)
    command = manifest["command_prefix"]
    result = subprocess.run(command + ["--list-devices"], cwd=Path(command[-1]).parent,
                            capture_output=True, text=True, check=True)
    if "MIG 1g.10gb" not in result.stdout:
        raise RuntimeError("CUDA MIG device was not found by the model runtime")
    print(json.dumps({"model_verified": True, "runtime_verified": True,
                      "host_driver": driver, "cuda_compat": CUDA_COMPAT_VERSION,
                      "devices": result.stdout.strip()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
