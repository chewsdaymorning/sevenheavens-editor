# Sevenheavens Edit Studio

Local editing infrastructure with registered originals, typed plans, durable jobs and scoped revisions. **The required result is an editable CapCut project on this Mac; that native route is not yet proven.** Real AI selection and own-footage acceptance also remain pending: no selected model, actual shoot, reference or music has been supplied to this build yet. Manual and generated-fixture paths are labeled assisted/fixture.

Requires Python 3.11, `uv`, and released `ffmpeg`/`ffprobe` executables on PATH.

```sh
uv sync --locked
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

Open [the local studio](http://127.0.0.1:8765). Stop with Ctrl-C. Restart with the same command; state remains in ignored `data/`. To use another working disk, set `SEVENHEAVENS_DATA_DIR` before starting. `.env.example` documents configuration; `.env` is not loaded automatically.

Optional local intake folders, relative to this project root, are `data/incoming/footage/`, `data/incoming/references/` and `data/incoming/music/`. They are ignored by Git. You may keep originals elsewhere and register those paths instead. No automatic folder scan or media move occurs; choose the containing root and register exact files in the UI. CapCut desktop is the target; no browser sign-in is required by this local app.

Create an edit, choose an explicit media directory and register full source/reference/music paths, then save the brief. No source is moved or modified. When visual selection is unavailable, its job reports `blocked` rather than inventing shots. Explicit manual shot lists are assisted operation and can exercise rendering/corrections without satisfying AI acceptance. Inspect source intervals and original output versions in Review.

```sh
uv run pytest -q
```

Tests use labeled fixtures and cannot establish useful selection or editorial acceptance. See `docs/STATUS.md`, `docs/EVIDENCE.md` and the starter pack's `ACCEPTANCE.md` for pending gates. Remote connection identifies the user-supplied repository; no remote push is part of setup.

Optional text rendering is not verified: Pillow is absent and its test is explicitly skipped. The fixture path supports clean cuts/music and permitted crops; no CapCut live desktop adapter or native project round-trip has been established. The installed official remote connector targets a different browser/cloud route; OAuth was interrupted, with no media uploads or proven account access/allowance.
