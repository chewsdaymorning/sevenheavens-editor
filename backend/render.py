"""Deterministic FFmpeg execution of validated source/timeline intervals."""
from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path
import re
import uuid

from .contracts import Asset, EditPlan
from .media import (MediaError, _binary, _probe, _run, _sha256,
                    assert_source_unchanged, ensure_renderable_color)


def _validate(plan: EditPlan, assets: dict[str, Asset]) -> None:
    allowed = {"cut", "crop", "scale", "music", "text"}
    if set(plan.operations) - allowed:
        raise MediaError("Unknown render operation")
    if plan.coverage_gaps:
        raise MediaError("Coverage gaps require an approved revised plan before render")
    if not plan.shots or "cut" not in plan.operations:
        raise MediaError("At least one shot and cut operation required")
    if plan.width % 2 or plan.height % 2 or plan.width <= 0 or plan.height <= 0:
        raise MediaError("Output dimensions must be positive even integers")
    fps = Fraction(plan.fps_num, plan.fps_den)
    if not 1 <= fps <= 120:
        raise MediaError("Unsupported output frame rate")
    cursor = 0
    for shot in plan.shots:
        asset = assets.get(shot.asset_id)
        if asset is None or asset.role != "source":
            raise MediaError("Shot must resolve to a registered source asset")
        if not asset.width or not asset.height:
            raise MediaError("Shot source is not video")
        if shot.timeline_start_frame != cursor or shot.timeline_end_frame <= cursor:
            raise MediaError("Timeline has a gap, overlap or invalid duration")
        if not 0 <= shot.source_start_s < shot.source_end_s <= asset.duration_s + .000001:
            raise MediaError("Shot source interval outside asset")
        frame_duration = float(1 / fps)
        duration = (shot.timeline_end_frame - shot.timeline_start_frame) * frame_duration
        if abs(duration - (shot.source_end_s - shot.source_start_s)) > frame_duration + 1e-6:
            raise MediaError("Source/timeline durations differ; retiming is unsupported")
        if shot.crop and "crop" not in plan.operations:
            raise MediaError("Crop not allowed by plan operations")
        if "scale" not in plan.operations and (asset.width != plan.width or asset.height != plan.height):
            raise MediaError("Scale operation required for differing dimensions")
        ensure_renderable_color(asset)
        cursor = shot.timeline_end_frame
    if plan.music:
        if "music" not in plan.operations:
            raise MediaError("Music not allowed by plan operations")
        music = assets.get(plan.music.asset_id)
        if not music or not music.has_audio:
            raise MediaError("Unknown or non-audio music source")
        if plan.music.source_start_s + float(cursor / fps) > music.duration_s + .001:
            raise MediaError("Music excerpt cannot cover requested timeline")
    if plan.text and "text" not in plan.operations:
        raise MediaError("Text not allowed by plan operations")
    for text in plan.text:
        if not 0 <= text.start_frame < text.end_frame <= cursor:
            raise MediaError("Text interval outside timeline")


def _text_images(plan: EditPlan, directory: Path) -> list[Path]:
    if not plan.text:
        return []
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise MediaError("Text requires Pillow; install project dependencies or remove text") from error
    paths = []
    font_path = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    for index, overlay in enumerate(plan.text):
        image = Image.new("RGBA", (plan.width, plan.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        size = max(16, round(plan.height * .035))
        font = ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default()
        bounds = draw.textbbox((0, 0), overlay.text, font=font, stroke_width=2)
        width = bounds[2] - bounds[0]
        x = overlay.x * plan.width - width / 2
        y = overlay.y * plan.height - (bounds[3] - bounds[1]) / 2
        draw.text((x, y), overlay.text, font=font, fill="white", stroke_width=2, stroke_fill="black")
        path = directory / f"text-{index}.png"
        image.save(path)
        paths.append(path)
    return paths


def render_plan(plan: EditPlan, assets: dict[str, Asset], output_dir,
                music_asset: Asset | None = None, cancel_check=None) -> dict:
    if isinstance(plan, dict):
        plan = EditPlan.model_validate(plan)
    assets = {key: Asset.model_validate(value) if isinstance(value, dict) else value for key, value in assets.items()}
    if music_asset:
        assets[music_asset.id] = music_asset
    _validate(plan, assets)
    used = {s.asset_id for s in plan.shots}
    if plan.music:
        used.add(plan.music.asset_id)
    for asset_id in used:
        assert_source_unchanged(assets[asset_id])
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", plan.id)[:80]
    run_id = f"{safe_id}-v{plan.version}-{uuid.uuid4().hex[:10]}"
    work = directory / run_id
    work.mkdir()
    output = work / "output.mp4"
    fps = Fraction(plan.fps_num, plan.fps_den)
    duration = float(plan.shots[-1].timeline_end_frame / fps)
    commands = []
    shot_evidence = []
    segments = []
    for index, shot in enumerate(plan.shots):
        asset = assets[shot.asset_id]
        frame_count = shot.timeline_end_frame - shot.timeline_start_frame
        segment = work / f"segment-{index:04d}.mp4"
        filters = [f"trim=start={asset.stream_origin_s + shot.source_start_s:.9f}:end={asset.stream_origin_s + shot.source_end_s:.9f}",
                   "setpts=PTS-STARTPTS"]
        if shot.crop:
            # Round crop dimensions/position to legal chroma sample boundaries.
            w = max(2, math.floor(asset.width * shot.crop.width / 2) * 2)
            h = max(2, math.floor(asset.height * shot.crop.height / 2) * 2)
            x = min(asset.width - w, math.floor(asset.width * shot.crop.x / 2) * 2)
            y = min(asset.height - h, math.floor(asset.height * shot.crop.y / 2) * 2)
            filters.append(f"crop={w}:{h}:{x}:{y}")
        filters += [f"scale={plan.width}:{plan.height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
                    f"pad={plan.width}:{plan.height}:(ow-iw)/2:(oh-ih)/2:color=black", "setsar=1",
                    f"fps=fps={fps.numerator}/{fps.denominator}:start_time=0", "format=yuv420p"]
        command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts",
                   "-i", asset.original_path, "-map", "0:v:0", "-an", "-vf", ",".join(filters),
                   "-frames:v", str(frame_count), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                   "-threads", "2", "-video_track_timescale", str(plan.fps_num * 1000), str(segment)]
        _run(command, cancel_check)
        actual = _probe(segment, count=True)
        actual_stream = next(s for s in actual["streams"] if s["codec_type"] == "video")
        if int(actual_stream.get("nb_read_frames", 0)) != frame_count:
            raise MediaError("Source interval did not yield requested output frame count; adjust boundary to decoded PTS")
        source_pts = [p.source_s for p in asset.timestamp_mapping if shot.source_start_s - 1e-8 <= p.source_s < shot.source_end_s - 1e-8]
        if not source_pts:
            raise MediaError("Source interval contains no measured decoded video frames")
        shot_evidence.append({"shot_id": shot.id, "asset_id": asset.id, "source_sha256": asset.sha256,
                              "source_start_s": shot.source_start_s, "source_end_s": shot.source_end_s,
                              "source_stream_origin_s": asset.stream_origin_s,
                              "decoded_first_source_s": min(source_pts), "decoded_last_source_s": max(source_pts),
                              "timeline_start_frame": shot.timeline_start_frame,
                              "timeline_end_frame": shot.timeline_end_frame, "output_frame_count": frame_count,
                              "candidate_id": shot.candidate_id, "manual_override_reason": shot.manual_override_reason,
                              "segment_path": str(segment)})
        commands.append(command)
        segments.append(segment)
    concat = work / "concat.txt"
    # These relative names are generated internally and contain no user input.
    concat.write_text("".join(f"file '{segment.name}'\n" for segment in segments))
    text_images = _text_images(plan, work)
    command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts",
               "-f", "concat", "-safe", "1", "-i", str(concat)]
    music_index = None
    if plan.music:
        music_index = 1
        command += ["-i", assets[plan.music.asset_id].original_path]
    first_text = 2 if plan.music else 1
    for path in text_images:
        command += ["-loop", "1", "-i", str(path)]
    filter_chains = []
    if text_images:
        previous = "0:v"
        for index, overlay in enumerate(plan.text):
            name = f"text{index}"
            start = float(overlay.start_frame / fps)
            end = float(overlay.end_frame / fps)
            filter_chains.append(f"[{previous}][{first_text + index}:v]overlay=0:0:enable='gte(t,{start:.9f})*lt(t,{end:.9f})'[{name}]")
            previous = name
        command += ["-filter_complex", ";".join(filter_chains), "-map", f"[{previous}]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "2", "-pix_fmt", "yuv420p"]
    else:
        command += ["-map", "0:v:0", "-c:v", "copy"]
    if plan.music:
        music = assets[plan.music.asset_id]
        # Music normally registers its audio origin; video references can also
        # supply music, so inspect the actual audio stream rather than guessing.
        audio_stream = next(s for s in _probe(Path(music.original_path))["streams"] if s["codec_type"] == "audio")
        audio_origin = float(audio_stream.get("start_time", 0))
        start = audio_origin + plan.music.source_start_s
        command += ["-map", f"{music_index}:a:0", "-af",
                    f"atrim=start={start:.9f}:end={start + duration:.9f},asetpts=PTS-STARTPTS,volume={plan.music.volume}",
                    "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-an"]
    command += ["-t", f"{duration:.9f}", "-movflags", "+faststart", "-map_metadata", "-1", str(output)]
    _run(command, cancel_check)
    commands.append(command)
    metadata = _probe(output, count=True)
    video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    expected_frames = plan.shots[-1].timeline_end_frame
    actual_frames = int(video.get("nb_read_frames", 0))
    if actual_frames != expected_frames or (video["width"], video["height"]) != (plan.width, plan.height):
        raise MediaError("Rendered output does not match requested frame count/dimensions")
    if abs(float(video["duration"]) - duration) > float(1 / fps) + .001:
        raise MediaError("Rendered duration differs from canonical plan")
    has_audio = any(s["codec_type"] == "audio" for s in metadata["streams"])
    if has_audio != bool(plan.music):
        raise MediaError("Rendered audio presence differs from plan")
    decode_command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-xerror", "-nostdin", "-i", str(output), "-f", "null", "-"]
    _run(decode_command, cancel_check)
    commands.append(decode_command)
    for asset_id in used:
        assert_source_unchanged(assets[asset_id])
    manifest = {"schema_version": plan.schema_version, "operating_mode": plan.mode,
                "plan": plan.model_dump(mode="json"), "output_path": str(output), "output_sha256": _sha256(output),
                "shot_evidence": shot_evidence,
                "sources": {key: {"sha256": assets[key].sha256, "original_path": assets[key].original_path,
                                  "stream_origin_s": assets[key].stream_origin_s, "warnings": assets[key].warnings}
                            for key in sorted(used)},
                "commands": commands, "qc": {"full_decode": "passed", "source_integrity": "passed",
                "frame_count": actual_frames, "duration_s": duration, "width": plan.width, "height": plan.height,
                "has_audio": has_audio, "color": "No color transform; tagged SDR or unverified untagged 8-bit"},
                "native_editability": "Not implemented or verified by FFmpeg renderer"}
    manifest_path = work / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return {"output_path": str(output), "manifest_path": str(manifest_path), "qc": manifest["qc"],
            "warnings": sorted(set(w for key in used for w in assets[key].warnings)),
            "mode": plan.mode, "duration_s": duration}
