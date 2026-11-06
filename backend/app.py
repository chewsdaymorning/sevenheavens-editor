"""Local UI service. Offline analysis is an explicit blocked stage until configured."""
from __future__ import annotations

import os
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .contracts import Asset, Brief, CandidateWindow, Correction, EditPlan, Job, MusicMap, SCHEMA_VERSION, new_id, now, validate_plan
from .jobs import JobManager
from .store import Store


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    store = Store(data_dir or os.environ.get("SEVENHEAVENS_DATA_DIR", "data"))
    manager = JobManager(store)

    @asynccontextmanager
    async def lifespan(application):
        yield
        manager.close()

    application = FastAPI(title="Sevenheavens Editor", version="0.1.0", lifespan=lifespan)
    application.state.store = store
    application.state.jobs = manager
    application.state.analysis_runner = None

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

    def validate_live_evidence(plan: EditPlan, candidates: dict[str, CandidateWindow]):
        if plan.mode != "live_ai":
            return
        for shot in plan.shots:
            candidate = candidates[shot.candidate_id]
            record = store.get("analysis_runs", candidate.analysis_run_id)
            if not record or not record.get("actual_call") or record.get("mode") != "live_ai":
                raise ValueError("Live plan lacks a recorded actual model call")
            artifact = Path(record.get("artifact_path", "")).resolve()
            if not artifact.is_relative_to(store.root / "analysis") or not artifact.is_file():
                raise ValueError("Live plan model evidence artifact is missing")

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
        validate_live_evidence(plan, candidates)
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
        return {"schema_version": SCHEMA_VERSION, "mode": "offline", "ai_configured": callable(application.state.analysis_runner), "cloud_budget_usd": 0, "media_roots": store.setting("media_roots", []), "analysis_runs": [public_run(r) for r in store.list("analysis_runs")], **{kind: store.list(kind) for kind in ("assets", "projects", "plans", "jobs", "corrections", "candidates", "recipes")}}

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
        from .media import register_asset
        asset = register_asset(path, role=role, product_group=group)
        for existing in store.list("assets"):
            if existing["sha256"] == asset.sha256 and existing["role"] == role:
                if group is not None and existing.get("product_group") != group:
                    raise HTTPException(409, "This content is already registered with a different product group. Open Footage and explicitly save its confirmed group; importing never silently changes grouping.")
                return existing
        return store.put("assets", asset, immutable=True)

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

    @application.post("/api/projects/{project_id}/runs")
    def run(project_id: str, payload: dict = Body(...)):
        brief = Brief.model_validate(require("projects", project_id))
        action = payload.get("action", "analyze")
        if action not in {"analyze", "render"}:
            raise ValueError("Unknown run action")
        if action == "analyze":
            job = Job(project_id=project_id, stage="visual_analysis", mode="offline")
            if not callable(application.state.analysis_runner):
                job.status = "blocked"
                job.error = "Real visual selection is unavailable: no permitted local model is installed/configured. Sources, reference and music are still required. Cloud calls are disabled; no weights download has been authorized."
                manager.save(job)
                return job
            feedback = store.applicable_corrections(brief)
            return manager.submit(job, lambda cancel, progress: application.state.analysis_runner(brief, assets_by_id(), store.root, cancel, progress, feedback, store))
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
        return {"correction": correction, "plan": new_plan}

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
