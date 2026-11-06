"""Plumbing fixtures only: these tests do not establish semantic AI selection."""
import math
import sqlite3
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app
from backend.contracts import Asset, Brief, CandidateWindow, Correction, EditPlan, Job, Shot, quantize_seconds, validate_plan
from backend.jobs import JobManager
from backend.store import Store


def source(**changes):
    return Asset(id="source", sha256="fixture-hash", original_path="fixture-only.mov", duration_s=30, width=1920, height=1080, **changes)


def plan(**changes):
    values = dict(id="plan", project_id="project", brief_id="project", mode="assisted", shots=[Shot(id="shot", asset_id="source", source_start_s=10, source_end_s=12, timeline_start_frame=0, timeline_end_frame=60, manual_override_reason="Fixture interval for plumbing test")])
    values.update(changes)
    return EditPlan(**values)


def test_invalid_bounds_provenance_and_product_are_rejected():
    asset = source(product_group="A")
    brief = Brief(id="project", name="fixture", source_asset_ids=[asset.id], product_group="A")
    validate_plan(plan(), {asset.id: asset}, brief=brief)
    for edit in [plan(project_id="wrong"), plan(width=1081), plan(shots=[Shot(id="shot", asset_id="source", source_start_s=29, source_end_s=31, timeline_start_frame=0, timeline_end_frame=60, manual_override_reason="fixture")]), plan(mode="live_ai")]:
        with pytest.raises(ValueError):
            validate_plan(edit, {asset.id: asset}, brief=brief)
    with pytest.raises(ValueError, match="product"):
        validate_plan(plan(), {asset.id: source(product_group="B")}, brief=brief)
    with pytest.raises(ValidationError):
        CandidateWindow(asset_id="source", start_s=10, end_s=12, selection_mode="live_ai")
    with pytest.raises(ValidationError):
        CandidateWindow(asset_id="source", start_s=10, end_s=12, selection_mode="live_ai", analysis_run_id="fake", evidence_ids=["fake"], sample_times_s=[math.nan])


def test_absolute_quantization_avoids_cumulative_rounding():
    cuts = [quantize_seconds(index * 0.017, 30000, 1001) for index in range(1001)]
    assert cuts[-1] == 509
    assert cuts == sorted(cuts)
    assert 1000 * quantize_seconds(0.017, 30000, 1001) != cuts[-1]


def test_store_immutable_versions_and_scoped_reuse(tmp_path):
    store = Store(tmp_path)
    store.put("plans", plan(), immutable=True)
    with pytest.raises(sqlite3.IntegrityError):
        store.put("plans", plan(), immutable=True)
    brief = Brief(id="project", name="fixture")
    for record in [Correction(id="edit", project_id=brief.id, plan_id="plan", reason="fixture", scope="edit", changes={"direction_rule": "new opening"}), Correction(id="format", project_id="other", plan_id="other", reason="fixture", scope="format", format_key="recreate:1080x1920:30/1", changes={"direction_rule": "no text"}), Correction(id="global", project_id="other", plan_id="other", reason="fixture", scope="reusable_rule", changes={"direction_rule": "preserve product"}), Correction(id="rejected", project_id=brief.id, plan_id="plan", reason="fixture", scope="reusable_rule", approval_state="rejected", changes={"direction_rule": "unused"})]:
        store.put("corrections", record, immutable=True)
    reopened = Store(tmp_path)
    assert {r["id"] for r in reopened.applicable_corrections(brief)} == {"edit", "format", "global"}
    unrelated = Brief(id="unrelated", name="fixture", reference_mode="adapt")
    assert {r["id"] for r in reopened.applicable_corrections(unrelated)} == {"global"}


def test_job_recovery_and_cancellation(tmp_path):
    store = Store(tmp_path)
    store.put("jobs", Job(id="interrupted", project_id="project", stage="analysis", status="running", provider_request_id="existing-request"))
    manager = JobManager(store)
    assert store.get("jobs", "interrupted")["status"] == "needs_attention"
    assert store.get("jobs", "interrupted")["provider_request_id"] == "existing-request"
    entered, release = Event(), Event()

    def work(cancel, progress):
        entered.set()
        assert release.wait(5)
        return {"fixture": True}

    job = manager.submit(Job(project_id="project", stage="fixture", mode="fixture"), work)
    assert entered.wait(5)
    manager.cancel(job.id)
    release.set()
    manager.close()
    assert store.get("jobs", job.id)["status"] == "cancelled"


def test_api_honest_blocked_mode_and_durable_correction(tmp_path):
    app = create_app(tmp_path)
    app.state.store.put("assets", source(), immutable=True)
    with TestClient(app) as client:
        assert client.post("/api/projects", json={"id": "project", "name": "fixture", "source_asset_ids": ["source"]}).status_code == 200
        blocked = client.post("/api/projects/project/runs", json={"action": "analyze"}).json()
        assert blocked["status"] == "blocked"
        assert client.get("/api/state").json()["ai_configured"] is False
        assert client.post("/api/plans", json=plan().model_dump()).status_code == 200
        response = client.post("/api/projects/project/corrections", json={"plan_id": "plan", "shot_id": "shot", "reason": "Fixture replacement", "scope": "edit", "changes": {"source_start_s": 14, "source_end_s": 16}})
        assert response.status_code == 200, response.text
        newer = response.json()["plan"]
        assert newer["version"] == 2 and newer["parent_plan_id"] == "plan"
        assert newer["mode"] == "assisted" and newer["id"] != "plan"
        assert client.get("/api/plans/plan").json()["shots"][0]["source_start_s"] == 10
        assert client.post("/api/projects/project/runs", json={"action": "render", "plan_id": "missing"}).status_code == 404
        assert client.post("/api/media-roots", json={"path": str(tmp_path)}, headers={"Origin": "https://example.com"}).status_code == 403
        assert client.get("/api/state", headers={"Host": "example.com"}).status_code == 403
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get(f"/api/plans/{newer['id']}").status_code == 200
        assert len(restarted.get("/api/state").json()["corrections"]) == 1


def test_live_plan_ids_without_actual_evidence_do_not_pass(tmp_path):
    app = create_app(tmp_path)
    app.state.store.put("assets", source(), immutable=True)
    candidate = CandidateWindow(id="candidate", asset_id="source", start_s=10, end_s=12, selection_mode="live_ai", analysis_run_id="invented", evidence_ids=["not-proof"], sample_times_s=[10, 11, 12])
    app.state.store.put("candidates", candidate, immutable=True)
    live = plan(mode="live_ai", shots=[Shot(id="shot", asset_id="source", candidate_id="candidate", source_start_s=10, source_end_s=12, timeline_start_frame=0, timeline_end_frame=60)])
    with TestClient(app) as client:
        client.post("/api/projects", json={"id": "project", "name": "fixture", "source_asset_ids": ["source"]})
        response = client.post("/api/plans", json=live.model_dump())
        assert response.status_code == 422
        assert "actual model call" in response.json()["detail"]


def test_content_dedup_and_explicit_group_revision(tmp_path, monkeypatch):
    """Stub inspection only: exercise API identity/group behavior, not codec evidence."""
    import hashlib
    from backend import media

    first = tmp_path / "first.mov"
    copied = tmp_path / "copy.mov"
    first.write_bytes(b"fixture content")
    copied.write_bytes(first.read_bytes())

    def inspect(path, role="source", product_group=None):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return Asset(id=f"{role}-{digest}", sha256=digest, original_path=str(path), duration_s=20, role=role, product_group=product_group)

    monkeypatch.setattr(media, "register_asset", inspect)
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        client.post("/api/media-roots", json={"path": str(tmp_path)})
        registered = client.post("/api/assets", json={"path": str(first), "product_group": "A"}).json()
        for path in [first, copied]:
            same = client.post("/api/assets", json={"path": str(path), "product_group": "A"})
            assert same.status_code == 200 and same.json()["id"] == registered["id"]
            conflict = client.post("/api/assets", json={"path": str(path), "product_group": "B"})
            assert conflict.status_code == 409 and "explicitly save" in conflict.json()["detail"]
        assert len(client.get("/api/assets").json()) == 1
        changed = client.patch(f"/api/assets/{registered['id']}", json={"product_group": "B", "reason": "User confirmed outfit B"})
        assert changed.status_code == 200
        assert changed.json()["product_group"] == "B"
        assert changed.json()["sha256"] == registered["sha256"]
        assert changed.json()["original_path"] == registered["original_path"]
        revision = app.state.store.list("asset_revisions")[0]
        assert revision["before"]["product_group"] == "A" and revision["after"]["product_group"] == "B"
        assert client.patch(f"/api/assets/{registered['id']}", json={"sha256": "changed", "reason": "invalid"}).status_code == 422


def test_candidate_metadata_and_scoped_evidence_are_available_sanitized(tmp_path):
    import json
    app = create_app(tmp_path / "runtime")
    store = app.state.store
    artifact = store.root / "analysis" / "fixture-call.json"
    artifact.write_text(json.dumps({"samples": [{"asset_id": "source", "source_s": 11, "sha256": "sample-hash", "path": "/Users/private/input.jpg"}], "model_decisions": [{"candidate_id": "candidate", "start_s": 10, "end_s": 12}], "authorization": "secret-test-key"}))
    store.put("analysis_runs", {"id": "fixture-run", "mode": "fixture", "actual_call": False, "provider": "fixture", "model": "fixture", "artifact_path": str(artifact), "api_key": "secret-test-key"})
    store.put("candidates", CandidateWindow(id="candidate", asset_id="source", start_s=10, end_s=12, selection_mode="fixture", sample_times_s=[10, 11, 12], analysis_run_id="fixture-run"))
    store.put("recipes", {"id": "recipe", "asset_id": "reference", "observations": ["fixture only"]})
    outside = tmp_path / "outside.json"
    outside.write_text('{"private":"not served"}')
    store.put("analysis_runs", {"id": "outside", "artifact_path": str(outside)})
    with TestClient(app) as client:
        state = client.get("/api/state").json()
        assert state["candidates"][0]["sample_times_s"] == [10, 11, 12]
        assert state["recipes"][0]["id"] == "recipe"
        assert "artifact_path" not in state["analysis_runs"][0] and "api_key" not in state["analysis_runs"][0]
        evidence = client.get("/api/analysis-runs/fixture-run/evidence")
        assert evidence.status_code == 200
        assert evidence.json()["evidence"]["model_decisions"][0]["start_s"] == 10
        assert "secret-test-key" not in evidence.text and "/Users/private" not in evidence.text
        assert client.get("/api/analysis-runs/outside/evidence").status_code == 404
