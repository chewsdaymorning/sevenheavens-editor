# Optional local visual model — downloads currently on hold

The app code is wired to its default offline `backend.analysis.run_analysis` runner. No optional vision package or weight was installed during this build. Missing setup creates a durable blocked job; imports survive and **Retry recreation** uses the same inputs after setup. No manual selections or mock replies enter the normal path.

For a later explicitly authorized setup, create a separate Python environment and install `requirements-vision.txt`. The pinned [MLX-VLM 0.7.12 release](https://pypi.org/project/mlx-vlm/0.7.12/) and [tagged multi-image API](https://github.com/Neywa-Labs/mlx-vlm/blob/v0.7.12/README.md) were checked from primary sources. [MLX requires supported Apple Silicon/macOS](https://ml-explore.github.io/mlx/build/html/install.html). These commands are instructions for later, not actions already executed:

```sh
uv venv --python python3.11 .venv-vision
uv pip install --python .venv-vision/bin/python -r requirements-vision.txt
```

Model weights are a separate decision and are not fetched by these instructions. The [community Qwen3-VL-2B-Instruct 4-bit snapshot](https://huggingface.co/mlx-community/Qwen3-VL-2B-Instruct-4bit/tree/main) is a researched candidate (about 1.8 GB, Apache-2.0); local memory use, speed, temporal accuracy and editorial usefulness remain untested. Do not treat that candidate as installed or accepted.

After an authorized snapshot exists locally, select its existing directory and the separate Python executable in the UI. Alternatively set `SEVENHEAVENS_MODEL_PATH` and `SEVENHEAVENS_MODEL_PYTHON` before startup. Both UI status and inference resolve the same persisted configuration with environment fallbacks. Configuration validates local files/runtime metadata; it does not load a model or prove inference quality. No secret/API credential is needed for this route.

Inference uses an isolated subprocess, a local directory, offline Hugging Face/Transformers flags and no cloud fallback. Cancellation terminates the worker. Actual call prompts, ordered sample IDs/PTS/hashes, raw decisions and runtime metadata remain in ignored `data/analysis/`; sanitized evidence is inspectable through the UI. Dense sampling narrows windows, but exact action timing and creative quality still need real-media review. Interrupted jobs require inspection before retry, with no automatic inference resubmission.

The first genuine configured-model test must establish reference observations → source-window decisions → validated plan → actual rendered own-footage output. Current fixture tests explicitly mark `fixture`/`actual_call=false` and cannot satisfy that gate.
