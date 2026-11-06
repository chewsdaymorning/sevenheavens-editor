"""Private JSONL subprocess, using MLX-VLM's published multi-image API.

Run only through LocalVisionProvider. Loading is restricted to an existing local
snapshot and HF offline mode. No image generation, training or remote provider.
"""
from contextlib import redirect_stdout
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1")


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def main():
    model_path = Path(sys.argv[1]).resolve(strict=True)
    if not model_path.is_dir() or not (model_path / "config.json").is_file():
        raise ValueError("Existing local model snapshot required")
    with redirect_stdout(sys.stderr):
        from mlx_vlm import load, generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config
        import mlx.core as mx
        version = importlib.metadata.version("mlx-vlm")
        if version != "0.7.12":
            raise ValueError("This adapter was implemented against mlx-vlm==0.7.12")
        model, processor = load(str(model_path))
        config = load_config(str(model_path))
    # A local repository name is not an immutable model version. Retain the
    # exact config/tokenizer/weight identities used, without publishing paths.
    model_files = []
    for file in sorted(model_path.iterdir()):
        if file.is_file() and file.suffix in {".json", ".safetensors"}:
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(1024*1024), b""):
                    digest.update(block)
            model_files.append({"name": file.name, "sha256": digest.hexdigest(), "bytes": file.stat().st_size})
    emit({"event": "ready", "provider": "mlx-vlm", "model": model_path.name,
          "runtime_version": version, "offline": True, "input_mode": "timestamped_multi_image", "model_files": model_files})
    for line in sys.stdin:
        try:
            request = json.loads(line)
            images = request["images"]
            if len(images) > 16 or any(not Path(p).is_file() for p in images):
                raise ValueError("At most sixteen existing sampled frames per local request")
            started = time.monotonic()
            with redirect_stdout(sys.stderr):
                prompt = apply_chat_template(processor, config, request["prompt"], num_images=len(images))
                answer = generate(model, processor, prompt, image=images or None,
                                  max_tokens=1800, temperature=0.0, verbose=False)
                text = answer.text if hasattr(answer, "text") else str(answer)
            emit({"event": "result", "text": text, "metadata": {"elapsed_s": time.monotonic()-started,
                  "peak_memory_bytes": int(mx.get_peak_memory()), "cost_usd": 0}})
        except Exception as exc:
            emit({"event": "error", "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit({"event": "error", "error": f"{type(exc).__name__}: {exc}"})
        sys.exit(1)
