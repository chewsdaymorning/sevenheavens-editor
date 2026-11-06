# Adopted dependency record

Actual versions are locked in `uv.lock`. License fields below were inspected from installed distribution metadata; no model weights or optional candidate packages were installed.

| Package | Resolved | License | Purpose / local evidence | Replacement |
|---|---|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 0.162.0 | MIT | Local routes; core API tests passed | stdlib or another local HTTP service |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.14.3 | MIT | Typed shared validation; invalid plans/candidates tested | explicit validation/dataclasses |
| [Uvicorn](https://www.uvicorn.org/) | 0.54.0 | BSD-3-Clause | Local ASGI runner; server smoke pending | another ASGI runner |
| [Starlette](https://github.com/Kludex/starlette) | 1.10.0 | BSD-3-Clause | FastAPI HTTP/static/file runtime | framework adapter change |
| [HTTPX](https://github.com/encode/httpx) | 0.28.1 | BSD-3-Clause | Test client only; upstream compatibility warning observed | supported test transport update |
| [pytest](https://github.com/pytest-dev/pytest) | 9.2.0 | MIT | Infrastructure tests executed | unittest |
| [python-multipart](https://pypi.org/project/python-multipart/0.0.33/) | 0.0.33 | Apache-2.0 | Incremental browser upload parser; file bounds/cleanup/real-media API tests passed | another bounded streaming parser |

FFmpeg/FFprobe actual build/codecs/licenses and media operations belong to the media specialist's executed report. Candidate registry is not evidence that Resolve, CapCut, scene/beat detectors, interchange or models work locally. Native editor export is unimplemented until a concrete round-trip passes.

Optional, not installed: [MLX-VLM 0.7.12](https://pypi.org/project/mlx-vlm/0.7.12/) (MIT) released package/tag and multi-image API checked by research worker. Separate `requirements-vision.txt` is never consumed by normal app setup. Adapter forces local snapshot/offline subprocess execution; memory/speed/semantic behavior remain unexecuted. Model candidate and later opt-in setup are documented in `LOCAL_MODEL_SETUP.md`; no checkpoint was downloaded or hash invented.
