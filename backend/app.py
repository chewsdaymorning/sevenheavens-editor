"""Local UI service. Offline analysis is an explicit blocked stage until configured."""
from __future__ import annotations

import os
import json
import re
import math
import shutil
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from .contracts import Asset, Brief, CandidateWindow, Correction, EditPlan, Job, MusicMap, SCHEMA_VERSION, new_id, now, validate_plan
from .jobs import JobManager, JobBlocked, JobCancelled
from .store import Store


class RecreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = "Reel recreation"
    directions: str = ""
    reference_asset_id: str | None = None
    source_asset_ids: list[str] = Field(default_factory=list)
    music_asset_id: str | None = None
    use_reference_audio: bool = False
    music_offset_s: float = Field(default=0, ge=0)
    duration_s: float | None = Field(default=None, gt=0)
    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    fps_num: int = Field(default=30, gt=0)
    fps_den: int = Field(default=1, gt=0)
    allow_crop: bool = False
    product_group: str | None = None
    hard_constraints: list[str] = Field(default_factory=list)


def create_app(data_dir: str | Path | None = None, *, analysis_runner=None, provider_status: dict | None = None) -> FastAPI:
    """Optional runner/status injection is a Python-only fixture-test boundary."""
    store = Store(data_dir or os.environ.get("SEVENHEAVENS_DATA_DIR", "data"))
    manager = JobManager(store)

    @asynccontextmanager
    async def lifespan(application):
        yield
        manager.close()

    application = FastAPI(title="Sevenheavens Editor", version="0.1.0", lifespan=lifespan)
    application.state.store = store
    application.state.jobs = manager
    def default_analysis(*args):
        from .analysis import run_analysis
        return run_analysis(*args)

    application.state.analysis_runner = analysis_runner or default_analysis

    def model_status():
        if provider_status is not None:
            return dict(provider_status)
        try:
            from .analysis import configuration_status
            return configuration_status(store.setting("provider_config", {}))
        except ImportError:
            return {"configured": False, "reason": "Local visual-analysis adapter is unavailable; finish optional setup without downloading automatically.", "stage": "setup_runtime", "provider": "mlx-vlm", "model_path_configured": False}

    @application.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.url.hostname
        if host not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            return JSONResponse({"detail": "Localhost access only"}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            if parsed.hostname != host or parsed.port != request.url.port:
                return JSONResponse({"detail": "Cross-origin changes are not permitted"}, status_code=403)
        return await call_next(request)

    @application.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @application.exception_handler(sqlite3.IntegrityError)
    async def duplicate_error(request, exc):
        return JSONResponse({"detail": "This version already exists; create a new ID/version"}, status_code=409)

    def require(kind: str, record_id: str) -> dict:
        value = store.get(kind, record_id)
        if value is None:
            raise HTTPException(404, f"Unknown {kind} record")
        return value

    def assets_by_id() -> dict[str, Asset]:
        return {a["id"]: Asset.model_validate(a) for a in store.list("assets")}

    def candidates_by_id() -> dict[str, CandidateWindow]:
        return {c["id"]: CandidateWindow.model_validate(c) for c in store.list("candidates")}

    def validate_live_evidence(plan: EditPlan, candidates: dict[str, CandidateWindow], brief: Brief):
        if plan.mode != "live_ai":
            return
        recipe = store.get("recipes", plan.provenance.get("recipe_id", ""))
        planning_id = plan.provenance.get("planning_run_id")
        if not recipe or not planning_id:
            raise ValueError("Live plan lacks a recorded actual model call for reference/sequence planning")
        if recipe.get("asset_id") != brief.reference_asset_id or not recipe.get("evidence_ids"):
            raise ValueError("Live reference recipe does not match the brief and recorded reference calls")

        def actual_document(identifier, stages):
            record = store.get("analysis_runs", identifier)
            if not record or record.get("actual_call") is not True or record.get("mode") != "live_ai" or record.get("status") != "succeeded":
                raise ValueError("Live plan requires a successful recorded actual model call")
            artifact = Path(record.get("artifact_path", "")).resolve()
            if not artifact.is_relative_to(store.root / "analysis") or not artifact.is_file():
                raise ValueError("Live plan model evidence artifact is missing")
            try:
                document = json.loads(artifact.read_text())
            except (UnicodeError, ValueError):
                raise ValueError("Live model evidence artifact is not valid JSON")
            if not isinstance(document, dict) or document.get("id") != identifier or document.get("actual_call") is not True or document.get("mode") != "live_ai" or document.get("status") != "succeeded" or document.get("stage") not in stages or not isinstance(document.get("parsed"), dict):
                raise ValueError("Live model evidence does not establish the required successful call")
            return document

        def call_task(document):
            try:
                return json.loads(document["prompt"].split("\n", 1)[1])["task"]
            except (KeyError, ValueError, AttributeError, IndexError, TypeError):
                raise ValueError("Live call is missing its recorded structured task")

        for identifier in recipe["evidence_ids"]:
            document = actual_document(identifier, {"reference_analysis"})
            if not document.get("samples") or any(s.get("asset_id") != brief.reference_asset_id for s in document["samples"]):
                raise ValueError("Reference call samples do not match the supplied reference")
        for shot in plan.shots:
            candidate = candidates[shot.candidate_id]
            document = actual_document(candidate.analysis_run_id, {"source_refinement", "source_window_assembly"})
            samples = document.get("samples", [])
            sample_ids = {sample.get("sample_id") for sample in samples if sample.get("asset_id") == candidate.asset_id}
            if not set(candidate.evidence_ids).issubset(sample_ids):
                raise ValueError("Candidate evidence does not resolve to recorded source samples")
            windows = document["parsed"].get("windows", [])
            if not isinstance(windows, list):
                raise ValueError("Candidate call has no structured window decisions")
            if not any(isinstance(window, dict) and window.get("start_s") == candidate.start_s and window.get("end_s") == candidate.end_s and set(candidate.evidence_ids).issubset(window.get("evidence_ids", [])) for window in windows):
                raise ValueError("Candidate interval differs from the actual model decision")
            if document["stage"] == "source_window_assembly":
                observations = call_task(document).get("dense_observations", [])
                if not observations:
                    raise ValueError("Assembled source window lacks its dense call chain")
                for observation in observations:
                    actual_document(observation.get("analysis_run_id"), {"source_refinement"})
        planning = actual_document(planning_id, {"sequence_planning"})
        decisions = planning["parsed"]
        selections = decisions.get("selections", [])
        slots = call_task(planning).get("slots", [])
        if decisions.get("constraints_satisfied") is not True or decisions.get("coverage_gaps") != [] or len(selections) != len(plan.shots) or len(slots) != len(plan.shots):
            raise ValueError("Actual planning call does not establish a complete valid sequence")
        by_slot = {choice.get("slot_index"): choice for choice in selections if isinstance(choice, dict)}
        slot_bounds = {slot.get("slot_index"): slot for slot in slots if isinstance(slot, dict)}
        for index, shot in enumerate(plan.shots):
            choice, slot = by_slot.get(index, {}), slot_bounds.get(index, {})
            start = choice.get("source_start_s")
            if choice.get("candidate_id") != shot.candidate_id or type(start) not in (float, int) or not math.isfinite(start) or abs(start - shot.source_start_s) > 0.000001 or slot.get("start_frame") != shot.timeline_start_frame or slot.get("end_frame") != shot.timeline_end_frame:
                raise ValueError("Plan sequence/timing differs from the actual model planning decision")
            expected_end = start + (shot.timeline_end_frame - shot.timeline_start_frame) * plan.fps_den / plan.fps_num
            if abs(expected_end - shot.source_end_s) > 0.000001:
                raise ValueError("Plan source out differs from the model choice and quantized timeline duration")

    def public_run(record: dict) -> dict:
        allowed = {"id", "mode", "actual_call", "provider", "model", "created_at", "status", "cost_usd", "input_sample_count"}
        return {key: record[key] for key in allowed if key in record}

    def sanitize_evidence(value):
        if isinstance(value, dict):
            return {key: sanitize_evidence(item) for key, item in value.items() if not any(word in key.lower() for word in ("token", "secret", "password", "credential", "authorization", "cookie", "api_key", "path"))}
        if isinstance(value, list):
            return [sanitize_evidence(item) for item in value]
        if isinstance(value, str):
            return re.sub(r"/(?:Users|home|private|tmp|Volumes)/[^\s\"']+", "[local path]", value)
        return value

    def check_plan(plan: EditPlan):
        brief = Brief.model_validate(require("projects", plan.project_id))
        assets, candidates = assets_by_id(), candidates_by_id()
        validate_plan(plan, assets, candidates, brief)
        validate_live_evidence(plan, candidates, brief)
        return brief, assets

    def validate_brief_assets(brief: Brief):
        assets = assets_by_id()
        for identifier in brief.source_asset_ids:
            if identifier not in assets or assets[identifier].role != "source":
                raise ValueError("Brief source IDs must identify registered source footage")
        for identifier, role in [(brief.reference_asset_id, "reference"), (brief.music_asset_id, "music")]:
            if identifier and (identifier not in assets or assets[identifier].role != role):
                raise ValueError(f"Brief {role} must identify a registered {role} asset")

    @application.get("/api/health")
    def health():
        return {"ok": True, "schema_version": SCHEMA_VERSION, "mode": "offline", "real_media_accepted": False}

    @application.get("/api/state")
    def state():
        status = model_status()
        return {"schema_version": SCHEMA_VERSION, "mode": "local", "ai_configured": status["configured"], "provider_status": status, "cloud_budget_usd": 0, "media_roots": store.setting("media_roots", []), "analysis_runs": [public_run(r) for r in store.list("analysis_runs")], **{kind: store.list(kind) for kind in ("assets", "projects", "plans", "jobs", "corrections", "candidates", "recipes")}}

    @application.get("/api/provider/status")
    def provider_get():
        return model_status()

    @application.post("/api/provider/config")
    def provider_config(payload: dict = Body(...)):
        if set(payload) - {"model_path", "python_path"} or not payload.get("model_path"):
            raise ValueError("Choose an existing local model directory and optional Python executable; this endpoint never downloads anything")
        path = Path(payload["model_path"]).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Model directory is unavailable. Downloads are on hold; select existing files only")
        python_path = payload.get("python_path")
        if python_path:
            python_path = str(Path(python_path).expanduser().resolve())
            if not Path(python_path).is_file() or not os.access(python_path, os.X_OK):
                raise ValueError("Selected Python executable is unavailable")
        store.set_setting("provider_config", {"provider": "mlx-vlm", "model_path": str(path), "python_path": python_path})
        return model_status()

    @application.get("/api/analysis-runs/{run_id}/evidence")
    def analysis_evidence(run_id: str):
        record = require("analysis_runs", run_id)
        path = Path(record.get("artifact_path", "")).resolve()
        if not path.is_relative_to(store.root / "analysis") or not path.is_file():
            raise HTTPException(404, "Analysis evidence is unavailable")
        if path.stat().st_size > 5_000_000:
            raise HTTPException(422, "Evidence document is too large for inline review")
        try:
            evidence = json.loads(path.read_text())
        except (UnicodeError, json.JSONDecodeError):
            raise HTTPException(422, "Evidence must be a structured JSON document")
        return {"run": public_run(record), "evidence": sanitize_evidence(evidence)}

    @application.post("/api/media-roots")
    def add_root(payload: dict = Body(...)):
        root = Path(payload.get("path", "")).expanduser().resolve()
        if not payload.get("path") or not root.is_dir():
            raise ValueError("Select an existing media directory")
        roots = store.setting("media_roots", [])
        if str(root) not in roots:
            roots.append(str(root))
            store.set_setting("media_roots", roots)
        return {"path": str(root), "media_roots": roots}

    @application.get("/api/assets")
    def list_assets():
        return store.list("assets")

    @application.post("/api/assets")
    def register(payload: dict = Body(...)):
        if not payload.get("path"):
            raise ValueError("Provide the actual local media path")
        path = Path(payload["path"]).expanduser().resolve()
        roots = [Path(p) for p in store.setting("media_roots", [])] + [store.root / "incoming"]
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError("Choose the containing media directory first")
        if not path.is_file():
            raise ValueError("Media file is unavailable")
        role = payload.get("role", "source")
        if role not in {"source", "reference", "music"}:
            raise ValueError("Unknown media role")
        group = payload.get("product_group")
        if group is not None and (not isinstance(group, str) or not group.strip()):
            raise ValueError("Product group must be an explicitly supplied nonempty label")
        from .media import register_asset, assert_source_unchanged
        asset = register_asset(path, role=role, product_group=group)
        asset.display_name = re.sub(r"[\x00-\x1f\x7f]", "", str(payload.get("display_name", path.name)))[:240]
        for existing in store.list("assets"):
            if existing["sha256"] == asset.sha256 and existing["role"] == role:
                if group is not None and existing.get("product_group") != group:
                    raise HTTPException(409, "This content is already registered with a different product group. Open Footage and explicitly save its confirmed group; importing never silently changes grouping.")
                if not Path(existing["original_path"]).is_file():
                    restored = {**existing, "original_path": str(path)}
                    store.put("asset_revisions", {"id": new_id(), "asset_id": existing["id"], "before": {"original_path": existing["original_path"]}, "after": {"original_path": str(path)}, "reason": "Reimported identical media after registered file became unavailable", "created_at": now()}, immutable=True)
                    return store.put("assets", Asset.model_validate(restored))
                if Path(existing["original_path"]) != path:
                    assert_source_unchanged(Asset.model_validate(existing))
                return existing
        return store.put("assets", asset, immutable=True)

    @application.post("/api/uploads")
    async def upload(request: Request, role: str = "source", product_group: str | None = None):
        """Parse multipart incrementally directly to an isolated local temporary copy."""
        from python_multipart import MultipartParser
        from python_multipart.multipart import parse_options_header

        if role not in {"source", "reference", "music"}:
            raise ValueError("Unknown media role")
        content_type, options = parse_options_header(request.headers.get("content-type", ""))
        if content_type != b"multipart/form-data" or not options.get(b"boundary"):
            raise HTTPException(415, "Choose a file with the browser file picker")
        configured_limit = int(os.environ.get("SEVENHEAVENS_MAX_UPLOAD_BYTES", "2000000000"))
        reserve = int(os.environ.get("SEVENHEAVENS_DISK_RESERVE_BYTES", "536870912"))
        free = shutil.disk_usage(store.root).free
        limit = min(configured_limit, max(0, free - reserve))
        if limit <= 0:
            raise HTTPException(507, "Not enough free working space; free disk space before importing")
        envelope_limit = limit + 65536
        try:
            content_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise HTTPException(400, "Invalid upload length")
        if content_length > envelope_limit:
            raise HTTPException(413, f"Upload exceeds the current {limit}-byte file/disk limit")
        directory = store.root / "incoming" / {"source": "footage", "reference": "references", "music": "music"}[role]
        directory.mkdir(parents=True, exist_ok=True)
        temp = directory / f"{new_id()}.part"
        target = None
        stream = None
        total = file_bytes = files_seen = 0
        finished = False
        headers: dict[bytes, bytes] = {}
        field = bytearray()
        value = bytearray()
        display_name = ""

        def header_field(data, start, end):
            field.extend(data[start:end])
            if len(field) + len(value) > 8192:
                raise HTTPException(413, "Upload header is too large")

        def header_value(data, start, end):
            value.extend(data[start:end])
            if len(field) + len(value) > 8192:
                raise HTTPException(413, "Upload header is too large")

        def header_end():
            headers[bytes(field).lower()] = bytes(value)
            field.clear()
            value.clear()

        def headers_finished():
            nonlocal stream, files_seen, display_name, target
            _, disposition = parse_options_header(headers.get(b"content-disposition", b""))
            if disposition.get(b"name") != b"file" or not disposition.get(b"filename") or files_seen:
                raise HTTPException(422, "Upload exactly one file per request using the file field")
            files_seen += 1
            display_name = re.sub(r"[\x00-\x1f\x7f]", "", disposition[b"filename"].decode("utf-8", errors="replace").replace("\\", "/").split("/")[-1])[:240]
            suffix = Path(display_name).suffix.lower()
            suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"
            target = directory / f"{temp.stem}{suffix}"
            stream = temp.open("xb")

        def part_data(data, start, end):
            nonlocal file_bytes
            size = end - start
            file_bytes += size
            if stream is None:
                raise HTTPException(422, "Upload data is missing its file header")
            if file_bytes > limit:
                raise HTTPException(413, f"File exceeds the current {limit}-byte file/disk limit")
            if shutil.disk_usage(store.root).free < size + reserve:
                raise HTTPException(507, "Working disk filled during import; partial copy removed")
            stream.write(data[start:end])

        def end():
            nonlocal finished
            finished = True

        parser = MultipartParser(options[b"boundary"], {"on_header_field": header_field, "on_header_value": header_value, "on_header_end": header_end, "on_headers_finished": headers_finished, "on_part_data": part_data, "on_end": end})
        try:
            async for chunk in request.stream():
                total += len(chunk)
                if total > envelope_limit:
                    raise HTTPException(413, "Upload request exceeds the configured file/disk limit")
                await run_in_threadpool(parser.write, chunk)
            parser.finalize()
            if not finished or not file_bytes or stream is None or target is None:
                raise HTTPException(400, "Upload was incomplete; select the file again")
            stream.close()
            stream = None
            temp.rename(target)
            record = await run_in_threadpool(register, {"path": str(target), "role": role, "product_group": product_group, "display_name": display_name})
            if Path(record["original_path"]) != target:
                target.unlink(missing_ok=True)
            return record
        except BaseException:
            if target:
                target.unlink(missing_ok=True)
            raise
        finally:
            if stream:
                stream.close()
            temp.unlink(missing_ok=True)

    @application.patch("/api/assets/{asset_id}")
    def asset_metadata(asset_id: str, payload: dict = Body(...)):
        previous = Asset.model_validate(require("assets", asset_id))
        if set(payload) != {"product_group", "reason"}:
            raise ValueError("Grouping changes require product_group and a reason; source identity is immutable")
        group, reason = payload["product_group"], payload["reason"]
        if group is not None and (not isinstance(group, str) or not group.strip()):
            raise ValueError("Use a nonempty confirmed product group or null to clear it")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Record why the confirmed grouping changed")
        updated = previous.model_copy(update={"product_group": group})
        store.put("asset_revisions", {"id": new_id(), "asset_id": asset_id, "before": {"product_group": previous.product_group}, "after": {"product_group": group}, "reason": reason, "created_at": now()}, immutable=True)
        return store.put("assets", updated)

    @application.get("/api/assets/{asset_id}/media")
    def play_source(asset_id: str):
        asset = Asset.model_validate(require("assets", asset_id))
        path = Path(asset.original_path)
        if not path.is_file():
            raise HTTPException(404, "Registered media is currently unavailable")
        return FileResponse(path)

    @application.get("/api/projects")
    def projects():
        return store.list("projects")

    @application.post("/api/projects")
    def project_create(brief: Brief):
        validate_brief_assets(brief)
        return store.put("projects", brief, immutable=True)

    @application.patch("/api/projects/{project_id}")
    def project_update(project_id: str, payload: dict = Body(...)):
        previous = require("projects", project_id)
        if any(key in payload for key in ("id", "schema_version")):
            raise ValueError("Project identity cannot change")
        brief = Brief.model_validate({**previous, **payload})
        validate_brief_assets(brief)
        return store.put("projects", brief)

    @application.get("/api/projects/{project_id}")
    def project_get(project_id: str):
        return {"brief": require("projects", project_id), **{kind: [r for r in store.list(kind) if r["project_id"] == project_id] for kind in ("plans", "jobs", "corrections")}}

    @application.post("/api/plans")
    def plan_create(plan: EditPlan):
        check_plan(plan)
        return store.put("plans", plan, immutable=True)

    @application.get("/api/plans/{plan_id}")
    def plan_get(plan_id: str):
        return require("plans", plan_id)

    @application.get("/api/plans/{plan_id}/output")
    def plan_output(plan_id: str):
        require("plans", plan_id)
        completed = [j for j in store.list("jobs") if j.get("plan_id") == plan_id and j["status"] == "succeeded" and j.get("artifacts", {}).get("output_path")]
        if not completed:
            raise HTTPException(404, "No completed render is available for this plan")
        path = Path(completed[-1]["artifacts"]["output_path"]).resolve()
        if not path.is_relative_to(store.root / "exports") or not path.is_file():
            raise HTTPException(404, "Output is unavailable")
        return FileResponse(path, media_type="video/mp4")

    def queue_pipeline(brief: Brief, *, render_output: bool = True, input_error: str | None = None) -> Job:
        job = Job(project_id=brief.id, stage="inputs", mode="offline")
        assets = assets_by_id()
        error = input_error
        if not brief.reference_asset_id:
            error = error or "Choose one reference Reel before recreating it"
        elif not brief.source_asset_ids:
            error = error or "Choose your own source footage before recreating the reference"
        elif not brief.music_asset_id:
            error = error or "Choose a music track or explicitly use the reference audio"
        else:
            selected = [brief.reference_asset_id, brief.music_asset_id, *brief.source_asset_ids]
            if any(not Path(assets[identifier].original_path).is_file() for identifier in selected):
                error = error or "A selected media file is unavailable; reconnect or import it again"
            elif brief.music_offset_s + (brief.duration_s or 0) > assets[brief.music_asset_id].duration_s + 0.000001:
                error = error or "The chosen music excerpt is too short; choose another start time or track"
            elif brief.product_group and not any(assets[a].product_group == brief.product_group for a in brief.source_asset_ids):
                error = error or "No source has the required confirmed product group; confirm grouping or choose matching footage"
        if error:
            job.status, job.error = "blocked", error
            manager.save(job)
            return job
        status = model_status()
        if not status["configured"]:
            job.status = "blocked"
            job.stage = status.get("stage", "model_setup")
            job.error = status["reason"]
            job.artifacts = {"setup_required": True, "provider_status": status}
            manager.save(job)
            return job
        feedback = store.applicable_corrections(brief)
        job.mode = "fixture" if provider_status and provider_status.get("provider") == "fixture" else "live_ai"
        store.put("job_briefs", {"id": job.id, "brief": brief.model_dump(mode="json"), "correction_ids": [c["id"] for c in feedback]}, immutable=True)

        def recreate(cancel, progress):
            def analysis_progress(value, stage=None):
                progress(float(value) * (0.75 if render_output else 1), stage or "visual_analysis")

            progress(0.01, "reference_analysis")
            try:
                result = application.state.analysis_runner(brief, assets, store.root, cancel, analysis_progress, feedback, store)
            except JobCancelled:
                raise
            except Exception as exc:
                if type(exc).__name__ == "AnalysisBlocked":
                    artifacts = getattr(exc, "artifacts", {})
                    raise JobBlocked(str(exc), artifacts.get("blocked_stage", artifacts.get("stage", "visual_analysis")), artifacts) from exc
                raise
            if cancel():
                raise JobCancelled()
            if not isinstance(result, dict) or not result.get("plan_id"):
                raise JobBlocked("Analysis did not produce an evidenced edit plan", "planning", result if isinstance(result, dict) else {})
            plan = EditPlan.model_validate(require("plans", result["plan_id"]))
            if plan.project_id != brief.id:
                raise ValueError("Analysis plan belongs to another project")
            _, current_assets = check_plan(plan)
            job.plan_id, job.mode = plan.id, plan.mode
            progress(0.78 if render_output else 1, "plan_validation", result)
            if not render_output:
                return result
            from .render import render_plan
            progress(0.80, "render", result)
            rendered = render_plan(plan, current_assets, store.root / "exports" / job.id, music_asset=current_assets.get(plan.music.asset_id) if plan.music else None, cancel_check=cancel)
            return {**result, **rendered, "plan_id": plan.id, "mode": plan.mode}

        return manager.submit(job, recreate)

    @application.post("/api/recreations")
    def recreate_create(payload: RecreationRequest):
        values = payload.model_dump(exclude={"use_reference_audio"})
        values["reference_mode"] = "recreate"
        assets = assets_by_id()
        error = None
        if payload.reference_asset_id:
            reference = Asset.model_validate(require("assets", payload.reference_asset_id))
            if reference.role != "reference":
                raise ValueError("The reference must be registered as a reference video")
            if values["duration_s"] is None:
                frames = max(1, math.floor(reference.duration_s * payload.fps_num / payload.fps_den))
                values["duration_s"] = frames * payload.fps_den / payload.fps_num
            if payload.use_reference_audio:
                if payload.music_asset_id:
                    raise ValueError("Choose either separate music or reference audio")
                if not reference.has_audio:
                    error = "This reference has no audio. Choose a separate music track"
                else:
                    from .media import register_asset
                    music = register_asset(reference.original_path, role="music")
                    existing = next((a for a in assets.values() if a.role == "music" and a.sha256 == music.sha256), None)
                    if existing:
                        music = existing
                    else:
                        music.display_name = reference.display_name
                        store.put("assets", music, immutable=True)
                    values["music_asset_id"] = music.id
        brief = Brief.model_validate(values)
        validate_brief_assets(brief)
        store.put("projects", brief, immutable=True)
        return {"project": brief, "job": queue_pipeline(brief, input_error=error)}

    @application.post("/api/projects/{project_id}/runs")
    def run(project_id: str, payload: dict = Body(...)):
        brief = Brief.model_validate(require("projects", project_id))
        action = payload.get("action", "analyze")
        if action not in {"analyze", "recreate", "render"}:
            raise ValueError("Unknown run action")
        if action in {"analyze", "recreate"}:
            return queue_pipeline(brief, render_output=action == "recreate")
        plan = EditPlan.model_validate(require("plans", payload.get("plan_id", "")))
        if plan.project_id != project_id:
            raise ValueError("Plan belongs to another project")
        _, assets = check_plan(plan)
        job = Job(project_id=project_id, plan_id=plan.id, stage="render", mode=plan.mode)

        def render(cancel, progress):
            from .render import render_plan
            progress(0.05, "render")
            return render_plan(plan, assets, store.root / "exports" / job.id, music_asset=assets.get(plan.music.asset_id) if plan.music else None, cancel_check=cancel)

        return manager.submit(job, render)

    @application.get("/api/jobs/{job_id}")
    def job_get(job_id: str):
        return require("jobs", job_id)

    @application.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str):
        require("jobs", job_id)
        return manager.cancel(job_id)

    @application.post("/api/projects/{project_id}/corrections")
    def correction_create(project_id: str, payload: dict = Body(...)):
        brief = Brief.model_validate(require("projects", project_id))
        old_plan = EditPlan.model_validate(require("plans", payload.get("plan_id", "")))
        if old_plan.project_id != project_id:
            raise ValueError("Correction plan belongs to another project")
        payload = dict(payload)
        rerender = payload.pop("rerender", False)
        if not isinstance(rerender, bool):
            raise ValueError("rerender must be true or false")
        allowed = {"plan_id", "shot_id", "reason", "scope", "changes"}
        if set(payload) - allowed:
            raise ValueError("Unknown correction fields")
        correction = Correction(project_id=project_id, format_key=f"{brief.reference_mode}:{brief.width}x{brief.height}:{brief.fps_num}/{brief.fps_den}", **payload)
        new_plan = None
        if correction.shot_id:
            allowed_changes = {"asset_id", "source_start_s", "source_end_s", "crop"}
            if not correction.changes or set(correction.changes) - allowed_changes:
                raise ValueError("Shot corrections allow source replacement, boundaries or permitted crop")
            values = old_plan.model_dump()
            shot = next((s for s in values["shots"] if s["id"] == correction.shot_id), None)
            if not shot:
                raise ValueError("Correction shot is unavailable")
            correction.before = dict(shot)
            shot.update(correction.changes)
            shot["candidate_id"] = None
            shot["manual_override_reason"] = correction.reason
            correction.after = dict(shot)
            values.update(id=new_id(), version=old_plan.version + 1, parent_plan_id=old_plan.id, mode="assisted")
            values["provenance"] = {**values["provenance"], "correction_id": correction.id}
            new_plan = EditPlan.model_validate(values)
            check_plan(new_plan)
            correction.new_plan_id = new_plan.id
            store.put("plans", new_plan, immutable=True)
        elif set(correction.changes) != {"direction_rule"} or not isinstance(correction.changes["direction_rule"], str) or not correction.changes["direction_rule"].strip():
            raise ValueError("A rule correction requires a nonempty direction_rule")
        store.put("corrections", correction, immutable=True)
        next_job = None
        if rerender:
            next_job = run(project_id, {"action": "render", "plan_id": new_plan.id}) if new_plan else queue_pipeline(brief)
        return {"correction": correction, "plan": new_plan, "job": next_job}

    @application.post("/api/music-maps")
    def save_music_map(music_map: MusicMap):
        asset = Asset.model_validate(require("assets", music_map.asset_id))
        if asset.role != "music":
            raise ValueError("Music map must refer to a registered music asset")
        if any(t > asset.duration_s for t in music_map.beats_s + music_map.onsets_s + music_map.downbeats_s + music_map.manual_anchors_s):
            raise ValueError("Music anchor exceeds source duration")
        return store.put("music_maps", music_map, immutable=True)

    @application.get("/api/music-maps/{asset_id}")
    def music_map_get(asset_id: str):
        values = [v for v in store.list("music_maps") if v["asset_id"] == asset_id]
        if not values:
            raise HTTPException(404, "No music anchors recorded")
        return values[-1]

    frontend = Path(__file__).resolve().parents[1] / "frontend"
    if frontend.is_dir():
        application.mount("/static", StaticFiles(directory=frontend), name="static")
        application.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return application


app = create_app()
