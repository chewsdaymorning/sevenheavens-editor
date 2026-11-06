"""Isolated, offline MLX-VLM 0.7.12 worker. No acquisition or cloud fallback."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time


class ProviderUnavailable(ValueError):
    pass


@dataclass
class ProviderReply:
    text: str
    metadata: dict
    actual_call: bool = True
    mode: str = "live_ai"


def resolved_config(config=None):
    values = dict(config or {})
    return {"provider": values.get("provider", "mlx-vlm"),
            "model_path": values.get("model_path") or os.environ.get("SEVENHEAVENS_MODEL_PATH"),
            "python_path": values.get("python_path") or os.environ.get("SEVENHEAVENS_MODEL_PYTHON") or sys.executable}


def provider_status(config=None):
    values = resolved_config(config)
    result = {"provider": "mlx-vlm", "ready": False, "configured": False,
              "stage": "model_missing", "reason": "Select an existing local Qwen3-VL model snapshot. Downloads are disabled."}
    if values["provider"] != "mlx-vlm":
        return {**result, "stage": "provider_unsupported", "reason": "Only the offline mlx-vlm adapter is supported."}
    if not values["model_path"]:
        return result
    model = Path(values["model_path"]).expanduser()
    if not model.is_dir() or not (model / "config.json").is_file() or not any(model.glob("*.safetensors")):
        return {**result, "reason": "The selected local model snapshot has no config.json and safetensors weights; nothing was downloaded."}
    python = Path(values["python_path"]).expanduser()
    if not python.is_file() or not os.access(python, os.X_OK):
        return {**result, "stage": "runtime_missing", "reason": "Select an executable Python from the optional local vision environment."}
    try:
        check = subprocess.run([str(python), "-c", "import importlib.metadata,json; print(json.dumps({'mlx_vlm':importlib.metadata.version('mlx-vlm')}))"],
                               capture_output=True, text=True, timeout=10)
        version = json.loads(check.stdout).get("mlx_vlm") if check.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        version = None
    if version != "0.7.12":
        return {**result, "stage": "runtime_missing", "reason": "The selected Python needs the separately installed mlx-vlm==0.7.12 runtime; no dependencies were installed.", "runtime_version": version}
    return {**result, "ready": True, "configured": True, "stage": "ready", "reason": "Local snapshot and declared runtime found; actual inference remains to be tested.",
            "model": model.name, "runtime_version": version}


class LocalVisionProvider:
    mode = "live_ai"
    provider = "mlx-vlm"

    def __init__(self, config, artifact_dir, cancel_check=lambda: False):
        self.config = resolved_config(config)
        self.status = provider_status(config)
        if not self.status["ready"]:
            raise ProviderUnavailable(self.status["reason"])
        self.model = Path(self.config["model_path"]).expanduser().resolve().name
        self.config["python_path"] = str(Path(self.config["python_path"]).expanduser().resolve())
        self.cancel_check = cancel_check
        self.directory = Path(artifact_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log = (self.directory / "provider.stderr.log").open("wb")
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"}
        worker = Path(__file__).with_name("mlx_worker.py")
        self.process = subprocess.Popen([self.config["python_path"], str(worker), str(Path(self.config["model_path"]).expanduser().resolve())],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, env=env, text=True, bufsize=1)
        try:
            ready = self._read(180)
            if ready.get("event") != "ready":
                raise ProviderUnavailable(ready.get("error", "Local model could not load; inspect the private provider log."))
            self.runtime = ready
        except BaseException:
            self.close()
            raise

    def _read(self, timeout):
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            if self.cancel_check():
                from ..jobs import JobCancelled
                raise JobCancelled()
            if select.select([self.process.stdout], [], [], .1)[0]:
                line = self.process.stdout.readline(2_000_001)
                if not line or len(line) > 2_000_000:
                    raise ProviderUnavailable("Local model worker ended or exceeded its response limit; inspect its private log.")
                try:
                    return json.loads(line)
                except ValueError as exc:
                    raise ProviderUnavailable("Local model worker returned an invalid protocol response.") from exc
            if self.process.poll() is not None:
                raise ProviderUnavailable("Local model worker stopped; inspect its private log.")
        raise ProviderUnavailable("Local inference exceeded its bounded timeout; no automatic resubmission.")

    def complete(self, prompt, images, cancel_check=None):
        if cancel_check:
            self.cancel_check = cancel_check
        request = {"prompt": prompt, "images": [str(Path(p).resolve()) for p in images]}
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        result = self._read(300)
        if result.get("event") != "result":
            raise ProviderUnavailable(result.get("error", "Local inference failed; inspect its private log."))
        return ProviderReply(result["text"], {**self.runtime, **result.get("metadata", {})})

    def close(self):
        if hasattr(self, "process") and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if hasattr(self, "log"):
            self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
