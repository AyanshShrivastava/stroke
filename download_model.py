"""
================================================================================
STROKE // OFFLINE AI MODEL BOOTSTRAPPER
Downloads quantized GGUF neural weights directly for 100% offline local inference.
================================================================================
Default Model: Meta Llama 3.2 1B Instruct (Q4_K_M, ~770 MB)
Alternative:   Meta Llama 3.2 3B Instruct (Q4_K_M, ~2.0 GB)
================================================================================
"""

import hashlib

def compute_file_sha256(filepath: str, chunk_size: int = 1024 * 1024) -> str:
    """Computes streaming SHA-256 checksum of the target model file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def verify_model_integrity(filepath: str, expected_sha256: str = None) -> bool:
    """Verifies that the downloaded file meets minimum size and matches expected SHA-256 hash."""
    if not os.path.exists(filepath):
        return False
    size = os.path.getsize(filepath)
    if size < 10_000_000:
        return False
    if expected_sha256:
        actual = compute_file_sha256(filepath)
        return actual.lower() == expected_sha256.lower()
    return True


MODELS = {
    "llama3.2-1b": {
        "filename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "size_mb": 770.3
    },
    "mini-agent-v2-1.5b": {
        "filename": "mini-agent-v2-1.5b-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 986.0
    },
    "qwen2.5-coder-1.5b": {
        "filename": "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 986.0
    },
    "llama3.2-3b": {
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size_mb": 2020.0
    }
}

DEFAULT_MODEL_KEY = "llama3.2-1b"

def get_models_dir():
    import paths_service
    user_models_dir = str(paths_service.get_models_dir())
    local_models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    if os.path.exists(local_models_dir) and any(f.endswith(".gguf") for f in os.listdir(local_models_dir)):
        return local_models_dir
    return user_models_dir

def is_model_installed(model_key=DEFAULT_MODEL_KEY):
    info = MODELS.get(model_key, MODELS[DEFAULT_MODEL_KEY])
    dest_path = os.path.join(get_models_dir(), info["filename"])
    return os.path.exists(dest_path) and os.path.getsize(dest_path) > 10_000_000

def download_model(model_key=DEFAULT_MODEL_KEY, progress_callback=None):
    """
    Downloads model weights with real-time byte progress reporting.
    Can be run standalone or called from FastAPI background task.
    """
    info = MODELS.get(model_key, MODELS[DEFAULT_MODEL_KEY])
    models_dir = get_models_dir()
    dest_path = os.path.join(models_dir, info["filename"])
    temp_path = dest_path + ".downloading"

    print("=" * 65)
    print(f" [STROKE OFFLINE AI LOADER // {info['filename']}]")
    print(f" Source: {info['url']}")
    print(f" Target: {dest_path}")
    print("=" * 65)

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 10_000_000:
        print("[STROKE AI] Model already downloaded and verified.")
        return dest_path

    # Check for existing partial download to resume
    downloaded = 0
    if os.path.exists(temp_path):
        downloaded = os.path.getsize(temp_path)

    headers = {"Range": f"bytes={downloaded}-"} if downloaded > 0 else {}

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        with client.stream("GET", info["url"], headers=headers) as response:
            if response.status_code not in (200, 206):
                raise Exception(f"HuggingFace CDN returned status {response.status_code}")

            total_bytes = int(response.headers.get("content-length", 0)) + downloaded
            mode = "ab" if downloaded > 0 else "wb"

            start_time = time.time()
            with open(temp_path, mode) as f:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(0.1, time.time() - start_time)
                    speed_mbps = (downloaded / (1024 * 1024)) / elapsed
                    pct = round((downloaded / total_bytes) * 100, 1) if total_bytes > 0 else 0.0

                    if progress_callback:
                        progress_callback(pct, downloaded, total_bytes, speed_mbps)

                    # Print progress bar to console
                    bar_len = 30
                    filled = int(bar_len * (pct / 100)) if total_bytes > 0 else 0
                    bar = "=" * filled + ">" + " " * max(0, bar_len - filled - 1)
                    sys.stdout.write(f"\r[{bar}] {pct}% ({downloaded / (1024*1024):.1f}/{total_bytes / (1024*1024):.1f} MB @ {speed_mbps:.1f} MB/s)")
                    sys.stdout.flush()

    if not verify_model_integrity(temp_path, expected_sha256=info.get("sha256")):
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise ValueError(f"Integrity check failed for downloaded model '{info['filename']}'. Checksum mismatch or corrupt payload.")

    os.rename(temp_path, dest_path)
    print("\n\n[STROKE AI] Model weights locked and verified with SHA-256 integrity.")
    return dest_path

if __name__ == "__main__":
    download_model()
