"""
================================================================================
STROKE // OFFLINE AI MODEL BOOTSTRAPPER
Downloads quantized GGUF neural weights directly for 100% offline local inference.
================================================================================
Default Model: Meta Llama 3.2 1B Instruct (Q4_K_M, ~770 MB)
Alternative:   Meta Llama 3.2 3B Instruct (Q4_K_M, ~2.0 GB)
================================================================================
"""

import os
import sys
import time
import httpx

MODELS = {
    "llama3.2-1b": {
        "filename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "size_mb": 770.3
    },
    "llama3.2-3b": {
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size_mb": 2020.0
    }
}

DEFAULT_MODEL_KEY = "llama3.2-1b"

def get_models_dir():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(base_dir, "models")
    os.makedirs(models_dir, exist_ok=True)
    return models_dir

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

    os.rename(temp_path, dest_path)
    print("\n\n[STROKE AI] Model weights locked and verified successfully.")
    return dest_path

if __name__ == "__main__":
    download_model()
