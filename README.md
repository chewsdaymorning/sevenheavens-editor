# Sevenheavens Reel recreation

Choose **one reference Reel, your own footage and music**, then click **Recreate this Reel**. The default application path analyzes the reference, scouts/refines source windows, validates a model-selected plan and renders the complete piece automatically. Review source intervals/evidence, play the output, and save a correction that rerenders a new version.

**Downloads are on hold.** The local visual model/runtime is not installed, so the normal app currently reports a named blocked setup stage and preserves imported files. It never substitutes manual choices for AI. The automatic path has passed generated-media tests with an explicitly labeled fixture provider; actual local inference, own-footage selection and editorial acceptance remain pending.

Requires Python 3.11, `uv`, and `ffmpeg`/`ffprobe` on PATH. Install only the lightweight application environment:

```sh
uv sync --locked
./scripts/start.sh
```

Open [the local application](http://127.0.0.1:8765). Stop with Ctrl-C; restart using the same command. State remains in ignored `data/`. Set `SEVENHEAVENS_DATA_DIR` before starting to use another working disk. `.env.example` documents variables; `.env` is not loaded automatically.

Use the browser file pickers for the reference, source clips and optional separate soundtrack. **Use reference audio** is an explicit alternative when that reference actually contains audio. Uploads copy incrementally to UUID paths on this Mac; browser originals remain unchanged. Imports have configured file/disk bounds and remove partial copies on failure. Existing exact content is deduplicated; reimport can restore a missing registered location with a revision record. Advanced local media-root registration remains available.

Optional intake folders relative to this project root are `data/incoming/footage/`, `data/incoming/references/` and `data/incoming/music/`. They are ignored. No automatic folder scan or media move occurs. Upload maximum defaults to 2,000,000,000 bytes/file with a 512 MiB disk reserve; see `.env.example`.

For a later authorized local-model setup, see [the setup guide](docs/LOCAL_MODEL_SETUP.md). No startup, status or configuration endpoint downloads packages/weights. The application uses the registered default analysis runner; no manual Python hook is required. Runtime inference is isolated and offline, with one queued local job at a time.

```sh
uv run pytest -q
```

Latest full suite: **29 passed / 1 skipped**. Fixture results establish plumbing, not semantic AI quality. Optional text remains unverified because Pillow is absent. See `docs/STATUS.md` and `docs/EVIDENCE.md` for evidence and pending gates.

Editable **CapCut on this Mac** remains a required handoff, currently paused behind the automatic recreation slice. No connected desktop adapter or GUI reopen acceptance is claimed. The official remote connector targets a different browser/cloud route; its OAuth was interrupted without media uploads. Source-only Git publication excludes originals, runtime data, model weights and credentials.
