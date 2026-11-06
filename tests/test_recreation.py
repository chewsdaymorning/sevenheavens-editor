"""Real upload/analysis/plan/render plumbing with an explicit fixture-only provider.

These generated colors and deterministic replies cannot establish semantic AI
quality, actual local model inference, or user-media acceptance.
"""
from functools import partial
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app


@pytest.fixture(scope="module")
def generated_media(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required for actual media plumbing")
    root = tmp_path_factory.mktemp("recreation-generated-fixtures")
    source, reference, music = root / "source.mp4", root / "reference.mp4", root / "music.wav"
    common = ["ffmpeg", "-v", "error", "-y"]
    subprocess.run(common + ["-f", "lavfi", "-i", "color=c=red:s=108x192:r=30:d=2", "-f", "lavfi", "-i", "color=c=blue:s=108x192:r=30:d=2", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(source)], check=True)
    subprocess.run(common + ["-f", "lavfi", "-i", "color=c=green:s=108x192:r=30:d=1", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(reference)], check=True)
    subprocess.run(common + ["-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=2", str(music)], check=True)
    return source, reference, music


class FixtureProvider:
    mode = provider = model = "fixture"
    calls = []

    def __init__(self, config, artifact_dir, cancel_check):
        self.cancel_check = cancel_check

    def complete(self, prompt, images, cancel_check):
        from backend.providers.local import ProviderReply
        payload = json.loads(prompt.split("\n", 1)[1])
        task, frames = payload["task"], payload["frames_in_image_order"]
        stage = task["stage"]
        self.calls.append(stage)
        if stage == "reference_analysis":
            value = {"role": "color fixture", "action": "generated steady color", "framing": "full-frame fixture", "uncertainties": ["Fixture response; no semantic inference"]}
        elif stage in {"source_scouting", "source_refinement", "source_window_assembly"}:
            start, end = min(s["source_s"] for s in frames), max(s["source_s"] for s in frames)
            if stage == "source_scouting":
                start, end = max(start, 1), min(end, 3)
            value = {"windows": [{"start_s": start, "end_s": end, "role": "color fixture", "action": "fixture interval", "framing": "full frame", "confidence": .9, "evidence_ids": [frames[0]["sample_id"], frames[-1]["sample_id"]], "warnings": ["No real model inference"]}], "coverage_gaps": []}
        elif stage == "sequence_planning":
            choices = []
            for slot in task["slots"]:
                candidate = next(c for c in task["candidates"] if c["start_s"] <= 1 and c["end_s"] >= 1 + slot["duration_s"])
                choices.append({"slot_index": slot["slot_index"], "candidate_id": candidate["id"], "source_start_s": 1, "confidence": .9, "reason": "Explicit fixture decision for pipeline check"})
            value = {"constraints_satisfied": True, "selections": choices, "coverage_gaps": []}
        else:
            raise AssertionError(f"Unknown fixture stage {stage}")
        return ProviderReply(json.dumps(value), {"fixture": True}, actual_call=False, mode="fixture")

    def close(self):
        pass


def wait_job(client, job_id):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(.03)
    pytest.fail("Fixture pipeline did not finish within its bound")


def upload(client, path, role):
    with path.open("rb") as stream:
        response = client.post(f"/api/uploads?role={role}", files={"file": (path.name, stream, "application/octet-stream")})
    assert response.status_code == 200, response.text
    return response.json()


def test_default_missing_model_keeps_real_uploads_and_never_invents_output(tmp_path, generated_media):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        source, reference, music = [upload(client, file, role) for file, role in zip(generated_media, ["source", "reference", "music"])]
        result = client.post("/api/recreations", json={"reference_asset_id": reference["id"], "source_asset_ids": [source["id"]], "music_asset_id": music["id"]}).json()
        assert result["project"]["duration_s"] == 1
        assert result["job"]["status"] == "blocked"
        assert result["job"]["stage"] in {"model_missing", "runtime_missing", "model_setup", "setup_runtime"}
        state = client.get("/api/state").json()
        assert state["ai_configured"] is False and not state["plans"]
        assert len(state["assets"]) == 3 and not list((tmp_path / "exports").rglob("*.mp4"))
        assert all(Path(a["original_path"]).is_file() for a in state["assets"])
        assert client.post("/api/provider/config", json={"model_path": str(tmp_path / "not-downloaded")}).status_code == 422


def test_actual_api_fixture_analysis_auto_render_reference_audio_and_revision(tmp_path, generated_media, monkeypatch):
    from backend import analysis
    monkeypatch.setattr(analysis, "COARSE_INTERVAL_S", 1)
    monkeypatch.setattr(analysis, "DENSE_INTERVAL_S", .25)
    FixtureProvider.calls = []
    runner = partial(analysis.run_analysis, provider_factory=FixtureProvider)
    app = create_app(tmp_path, analysis_runner=runner, provider_status={"configured": True, "ready": True, "provider": "fixture", "reason": "Fixture-only test injection"})
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in generated_media]
    with TestClient(app) as client:
        source = upload(client, generated_media[0], "source")
        reference = upload(client, generated_media[1], "reference")
        response = client.post("/api/recreations", json={"name": "Fixture automatic recreation", "reference_asset_id": reference["id"], "source_asset_ids": [source["id"]], "use_reference_audio": True, "width": 108, "height": 192})
        assert response.status_code == 200, response.text
        result = response.json()
        job = wait_job(client, result["job"]["id"])
        assert job["status"] == "succeeded", job.get("error")
        assert job["mode"] == "fixture" and job["artifacts"]["mode"] == "fixture"
        assert job["plan_id"] == job["artifacts"]["plan_id"]
        assert {"reference_analysis", "source_scouting", "source_refinement", "sequence_planning"}.issubset(FixtureProvider.calls)
        plan = client.get(f"/api/plans/{job['plan_id']}").json()
        assert plan["mode"] == "fixture" and plan["shots"][0]["source_start_s"] == 1
        assert plan["music"]["asset_id"] == result["project"]["music_asset_id"]
        output = client.get(f"/api/plans/{job['plan_id']}/output")
        assert output.status_code == 200 and output.headers["content-type"] == "video/mp4"
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", job["artifacts"]["output_path"]], check=True, capture_output=True, text=True).stdout)
        assert any(s["codec_type"] == "audio" for s in probe["streams"])
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        assert int(video["nb_frames"]) == 30
        state = client.get("/api/state").json()
        assert state["analysis_runs"] and all(not run["actual_call"] and run["mode"] == "fixture" for run in state["analysis_runs"])
        evidence = client.get(f"/api/analysis-runs/{state['candidates'][0]['analysis_run_id']}/evidence").json()
        assert evidence["evidence"]["raw_response"] and evidence["evidence"]["samples"]
        correction = client.post(f"/api/projects/{result['project']['id']}/corrections", json={"plan_id": plan["id"], "shot_id": plan["shots"][0]["id"], "scope": "edit", "reason": "Fixture shift to later source range", "changes": {"source_start_s": 2, "source_end_s": 3}, "rerender": True})
        assert correction.status_code == 200, correction.text
        corrected = correction.json()
        new_job = wait_job(client, corrected["job"]["id"])
        assert new_job["status"] == "succeeded", new_job
        assert corrected["plan"]["parent_plan_id"] == plan["id"]
        assert new_job["artifacts"]["output_path"] != job["artifacts"]["output_path"]
        assert client.get(f"/api/plans/{plan['id']}/output").status_code == 200
        assert client.get(f"/api/plans/{corrected['plan']['id']}/output").status_code == 200
    assert hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in generated_media]


def test_stream_upload_bounds_cleanup_filename_and_no_audio_choice(tmp_path, generated_media, monkeypatch):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/uploads?role=source", files={"file": ("../../fixture.mp4", generated_media[0].read_bytes(), "video/mp4")})
        assert response.status_code == 200, response.text
        asset = response.json()
        assert asset["display_name"] == "fixture.mp4"
        assert Path(asset["original_path"]).parent == tmp_path / "incoming" / "footage"
        assert Path(asset["original_path"]).name != "fixture.mp4"
        bad = client.post("/api/uploads", files={"file": ("bad.mp4", b"not video")})
        assert bad.status_code == 422
        monkeypatch.setenv("SEVENHEAVENS_MAX_UPLOAD_BYTES", "10")
        oversized = client.post("/api/uploads", files={"file": ("big.mp4", b"x" * 100)})
        assert oversized.status_code == 413
        assert not list((tmp_path / "incoming").rglob("*.part"))
        assert len(list((tmp_path / "incoming" / "footage").glob("*"))) == 1
        monkeypatch.delenv("SEVENHEAVENS_MAX_UPLOAD_BYTES")
        truncated = client.post("/api/uploads", content=b'--test\r\nContent-Disposition: form-data; name="file"; filename="cut.mp4"\r\n\r\npartial', headers={"Content-Type": "multipart/form-data; boundary=test"})
        assert truncated.status_code == 400
        assert not list((tmp_path / "incoming").rglob("*.part"))
        # A source-only generated fixture has no audio: explicit reference-audio
        # choice must block, rather than silently producing a silent edit.
        reference = upload(client, generated_media[0], "reference")
        result = client.post("/api/recreations", json={"reference_asset_id": reference["id"], "source_asset_ids": [asset["id"]], "use_reference_audio": True}).json()
        assert result["job"]["status"] == "blocked" and "no audio" in result["job"]["error"]


def test_exact_reupload_restores_missing_location_with_identity_revision(tmp_path, generated_media):
    with TestClient(create_app(tmp_path)) as client:
        original = upload(client, generated_media[0], "source")
        Path(original["original_path"]).unlink()
        restored = upload(client, generated_media[0], "source")
        assert restored["id"] == original["id"] and restored["sha256"] == original["sha256"]
        assert restored["display_name"] == original["display_name"]
        assert restored["original_path"] != original["original_path"]
        assert Path(restored["original_path"]).is_file()
        media = client.get(f"/api/assets/{restored['id']}/media")
        assert media.status_code == 200 and hashlib.sha256(media.content).hexdigest() == original["sha256"]
        revisions = client.app.state.store.list("asset_revisions")
        assert revisions[-1]["before"]["original_path"] == original["original_path"]
        assert "identical media" in revisions[-1]["reason"]


def test_limited_untagged_sdr_jpeg_samples_include_final_decoded_pts(tmp_path, generated_media):
    from backend.media import register_asset, sample_frames
    reference = register_asset(generated_media[1], role="reference")
    before = hashlib.sha256(generated_media[1].read_bytes()).hexdigest()
    samples = sample_frames(reference, tmp_path, timestamps_s=[0, reference.duration_s - .001])
    assert samples[-1]["source_s"] == max(point.source_s for point in reference.timestamp_mapping)
    for sample in samples:
        image = Path(sample["path"])
        assert hashlib.sha256(image.read_bytes()).hexdigest() == sample["sha256"]
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(image)], capture_output=True, check=True, text=True).stdout)
        video = probe["streams"][0]
        assert video["pix_fmt"] == "yuvj420p" and video["color_range"] == "pc"
        assert sample["source_pts_s"] == reference.stream_origin_s + sample["source_s"]
    assert hashlib.sha256(generated_media[1].read_bytes()).hexdigest() == before
