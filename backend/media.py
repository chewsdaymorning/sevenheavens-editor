"""Read-only source inspection and FFmpeg working media (contract 0.1).

Source times are seconds relative to the first decoded stream PTS. Neither VFR
inspection nor visual samples infer source frame indices from nominal FPS.
"""
from __future__ import annotations

import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from fractions import Fraction
from typing import Callable

from .contracts import Asset, TimestampPoint


class MediaError(ValueError):
    pass


class UnsupportedColorError(MediaError):
    pass


class MediaCancelled(MediaError):
    pass


def _run(command: list[str], cancel_check: Callable[[], bool] | None = None,
         timeout: float = 600) -> subprocess.CompletedProcess:
    """Capture diagnostics, kill FFmpeg on cancellation, never invoke a shell."""
    if cancel_check and cancel_check():
        raise MediaCancelled("Media job cancelled")
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                if cancel_check and cancel_check():
                    raise MediaCancelled("Media job cancelled")
                if time.monotonic() - started > timeout:
                    raise MediaError("Media command exceeded its bounded timeout")
    except BaseException:
        proc.terminate()
        try:
            proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        raise
    if proc.returncode:
        raise MediaError(f"{Path(command[0]).name} failed ({proc.returncode}): "
                         + err.decode("utf-8", "replace")[-3000:])
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def _binary(name: str) -> str:
    result = shutil.which(name)
    if not result:
        raise MediaError(f"Required executable unavailable: {name}")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_source_unchanged(asset: Asset) -> None:
    if _sha256(Path(asset.original_path)) != asset.sha256:
        raise MediaError(f"Registered source changed: {asset.id}; re-register before proceeding")


def _probe(path: Path, *, frames: bool = False, count: bool = False) -> dict:
    args = [_binary("ffprobe"), "-v", "error"]
    if frames:
        args += ["-select_streams", "v:0", "-show_frames", "-show_entries",
                 "frame=best_effort_timestamp_time,pkt_duration_time,duration_time"]
    else:
        args += ["-show_streams", "-show_format"]
    if count:
        args += ["-count_frames"]
    args += ["-of", "json", str(path)]
    return json.loads(_run(args).stdout)


def _float(value, default=0.) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _frame_times(path: Path) -> tuple[list[float], list[float]]:
    frames = _probe(path, frames=True).get("frames", [])
    points = [(float(f["best_effort_timestamp_time"]),
               _float(f.get("duration_time", f.get("pkt_duration_time"))))
              for f in frames if f.get("best_effort_timestamp_time") is not None]
    points.sort()
    return [p[0] for p in points], [p[1] for p in points]


def _color_warnings(video: dict) -> list[str]:
    warnings = []
    transfer = video.get("color_transfer")
    primaries = video.get("color_primaries")
    pixel_format = video.get("pix_fmt", "unknown")
    bit_depth = int(video.get("bits_per_raw_sample") or 0)
    if not bit_depth:
        if any(s in pixel_format for s in ("10", "12", "14", "16", "f32")):
            bit_depth = 10
        else:
            bit_depth = 8
    if (transfer in ("smpte2084", "arib-std-b67", "log", "log_sqrt", "bt2020-10", "bt2020-12", "smpte428")
            or primaries in ("bt2020", "smpte431", "smpte432")
            or video.get("color_space") in ("bt2020nc", "bt2020c")):
        warnings.append("Unsupported HDR/Log/wide-gamut source: explicit color conversion required")
    if not transfer or transfer == "unknown":
        warnings.append("Color unverified; no color transform; untagged footage may be Log")
        if bit_depth > 8:
            warnings.append("Unsupported untagged >8-bit source: color interpretation required")
    warnings.append(f"Decoded pixel format {pixel_format}; estimated component depth {bit_depth} bit")
    return warnings


def ensure_renderable_color(asset: Asset) -> None:
    if any(w.startswith("Unsupported ") for w in asset.warnings):
        raise UnsupportedColorError("; ".join(w for w in asset.warnings if w.startswith("Unsupported ")))
    if (asset.color_transfer in ("smpte2084", "arib-std-b67", "log", "log_sqrt", "bt2020-10", "bt2020-12", "smpte428")
            or asset.color_primaries in ("bt2020", "smpte431", "smpte432")
            or asset.color_space in ("bt2020nc", "bt2020c")):
        raise UnsupportedColorError("HDR/Log/wide-gamut conversion is not implemented")


def register_asset(path, role="source", product_group=None) -> Asset:
    """Hash/register a real file. Access authorization belongs to the API layer."""
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise MediaError("Media path must be a file")
    before = source.stat()
    digest = _sha256(source)
    metadata = _probe(source)
    streams = metadata.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and
                  not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if role != "music" and not video:
        raise MediaError("Source/reference must have a decodable video stream")
    if role == "music" and not audio:
        raise MediaError("Music asset must have an audio stream")
    primary = audio if role == "music" else video
    origin = _float(primary.get("start_time"))
    duration = _float(primary.get("duration"), _float(metadata.get("format", {}).get("duration")))
    width = height = None
    rotation = 0
    rate_mode = "unknown"
    fps = Fraction(0, 1)
    mapping = []
    warnings = []
    if video and role != "music":
        pts, frame_durations = _frame_times(source)
        if not pts:
            raise MediaError("No decoded video timestamps found")
        origin = pts[0]
        intervals = [b - a for a, b in zip(pts, pts[1:]) if b > a]
        last_duration = frame_durations[-1] or (statistics.median(intervals) if intervals else 0)
        decoded_duration = pts[-1] - origin + last_duration
        if decoded_duration > 0:
            duration = decoded_duration
        try:
            fps = Fraction(video.get("avg_frame_rate", "0/1"))
        except (ValueError, ZeroDivisionError):
            fps = Fraction(0, 1)
        if intervals:
            median = statistics.median(intervals)
            rate_mode = "vfr" if any(abs(d - median) > max(1e-5, median * .01) for d in intervals) else "cfr"
        width, height = video.get("width"), video.get("height")
        rotation = int(_float(video.get("tags", {}).get("rotate")))
        for side in video.get("side_data_list", []):
            if "rotation" in side:
                rotation = round(float(side["rotation"]))
        if abs(rotation) % 180 == 90:
            width, height = height, width
        mapping = [TimestampPoint(source_s=round(t - origin, 9), working_s=round(t - origin, 9)) for t in pts]
        warnings = _color_warnings(video)
        if rate_mode == "vfr":
            warnings.append("VFR source: decisions use decoded timestamps, not nominal frame indices")
    if duration <= 0:
        raise MediaError("Could not establish a positive decoded media duration")
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise MediaError("Source changed during registration")
    return Asset(id=f"asset_{role}_{digest[:24]}", sha256=digest, original_path=str(source),
                 role=role, duration_s=duration, width=width, height=height,
                 fps_num=fps.numerator, fps_den=fps.denominator, rate_mode=rate_mode,
                 stream_origin_s=origin, rotation_degrees=rotation,
                 color_space=video.get("color_space") if video else None,
                 color_transfer=video.get("color_transfer") if video else None,
                 color_primaries=video.get("color_primaries") if video else None,
                 pixel_format=video.get("pix_fmt") if video else None,
                 product_group=product_group, has_audio=bool(audio),
                 timestamp_mapping=mapping, warnings=warnings)


inspect_asset = register_asset


def _actual_source_times(asset: Asset) -> list[float]:
    # Proxies can replace working_s; source_s always remains the original PTS.
    return sorted(set(p.source_s for p in asset.timestamp_mapping))


def sample_frames(asset: Asset, output_dir, timestamps_s=None, interval_s=1.0,
                  cancel_check=None) -> list[dict]:
    """Return JPEG evidence with requested and *actual* original-relative PTS."""
    if asset.role == "music":
        raise MediaError("Music has no visual frames")
    ensure_renderable_color(asset)
    assert_source_unchanged(asset)
    if interval_s <= 0:
        raise MediaError("Sampling interval must be positive")
    targets = timestamps_s if timestamps_s is not None else [i * interval_s for i in range(math.ceil(asset.duration_s / interval_s))]
    times = _actual_source_times(asset)
    if not times:
        raise MediaError("Source decoded timestamp mapping unavailable")
    directory = Path(output_dir).resolve() / asset.id
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for index, target in enumerate(targets):
        if not 0 <= target < asset.duration_s:
            raise MediaError("Sample time outside registered source")
        actual = min(times, key=lambda t: abs(t - target))
        position = times.index(actual)
        # FFprobe's decimal PTS output rounds to microseconds. Keep the select
        # threshold just before that rounded value, bounded away from the prior
        # decoded PTS; this also retains the final frame of a take.
        tolerance = min(.000001, (actual - times[position - 1]) / 2) if position else .000001
        output = directory / f"frame_{index:05d}_{actual:.6f}.jpg"
        temporary = directory / f".frame-{uuid.uuid4().hex}.jpg"
        # copyts preserves nonzero source PTS; select retains the measured frame.
        command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts",
                   "-i", asset.original_path, "-vf",
                   f"select=gte(t\\,{asset.stream_origin_s + actual - tolerance:.9f}),scale=480:480:force_original_aspect_ratio=decrease:in_range=auto:out_range=pc,format=yuvj420p",
                   "-color_range", "pc",
                   "-frames:v", "1", "-q:v", "3", str(temporary)]
        if not output.is_file():
            try:
                _run(command, cancel_check)
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
        if not output.is_file() or not output.stat().st_size:
            raise MediaError("Sample decode produced no image")
        results.append({"asset_id": asset.id, "requested_s": target, "source_s": actual,
                        "source_pts_s": asset.stream_origin_s + actual, "path": str(output),
                        "sha256": _sha256(output)})
    assert_source_unchanged(asset)
    return results


def create_proxy(asset: Asset, output_dir, cancel_check=None) -> Asset:
    if asset.role == "music":
        return asset
    ensure_renderable_color(asset)
    assert_source_unchanged(asset)
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{asset.id}.mp4"
    temporary = directory / f".{asset.id}-{uuid.uuid4().hex}.mp4"
    command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts",
               "-i", asset.original_path, "-map", "0:v:0", "-an", "-vf",
               f"setpts=PTS-({asset.stream_origin_s:.9f})/TB,scale=720:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
               "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary)]
    cache_hit = output.exists()
    if not output.exists():
        try:
            _run(command, cancel_check)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    working_pts, _ = _frame_times(output)
    sources = _actual_source_times(asset)
    if len(working_pts) != len(sources):
        raise MediaError("Proxy changed decoded frame count; timestamp mapping cannot be assumed")
    mapping = [TimestampPoint(source_s=s, working_s=max(0, w - working_pts[0])) for s, w in zip(sources, working_pts)]
    sidecar = directory / f"{asset.id}.mapping.json"
    if not cache_hit or not sidecar.exists():
        sidecar.write_text(json.dumps({"source_sha256": asset.sha256,
            "proxy_sha256": _sha256(output), "source_stream_origin_s": asset.stream_origin_s,
            "points": [p.model_dump() for p in mapping], "command": command if not cache_hit else None,
            "cache_hit": cache_hit}, indent=2))
    assert_source_unchanged(asset)
    return asset.model_copy(update={"working_path": str(output), "timestamp_mapping": mapping})


def detect_reference_cuts(asset: Asset, threshold=10., cancel_check=None) -> dict:
    """Technical hard-cut proposals, independent of semantic shot selection."""
    if not 0 < threshold <= 100:
        raise MediaError("Scene threshold must be in (0, 100]")
    ensure_renderable_color(asset)
    assert_source_unchanged(asset)
    command = [_binary("ffmpeg"), "-hide_banner", "-nostdin", "-copyts", "-i", asset.original_path,
               "-an", "-vf", f"scdet=threshold={threshold}:sc_pass=1", "-f", "null", "-"]
    result = _run(command, cancel_check)
    assert_source_unchanged(asset)
    import re
    cuts = [float(s) - asset.stream_origin_s for s in re.findall(r"lavfi\.scd\.time:\s*([-\d.]+)", result.stderr.decode("utf-8", "replace"))]
    return {"asset_id": asset.id, "method": "ffmpeg_scdet", "threshold": threshold,
            "cuts_s": [t for t in cuts if 0 < t < asset.duration_s], "command": command,
            "warning": "Hard-cut proposals; not action selection or verified editorial structure"}


def extract_music_map(asset: Asset, excerpt_start_s=0., duration_s=None,
                      manual_anchors_s=None, cancel_check=None) -> dict:
    """Lightweight energy-onset proposals; manual anchors are explicit evidence."""
    if not asset.has_audio:
        raise MediaError("Selected asset has no audio")
    assert_source_unchanged(asset)
    duration = duration_s if duration_s is not None else asset.duration_s - excerpt_start_s
    if excerpt_start_s < 0 or duration <= 0 or excerpt_start_s + duration > asset.duration_s + .001:
        raise MediaError("Music excerpt outside source")
    sample_rate = 16000
    command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", asset.original_path,
               "-ss", str(excerpt_start_s), "-t", str(duration), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"]
    samples = array.array("h", _run(command, cancel_check).stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    hop = 160
    energy = [math.sqrt(sum((v / 32768.) ** 2 for v in samples[i:i + hop]) / len(samples[i:i + hop]))
              for i in range(0, len(samples), hop)]
    novelty = [max(0., value - (energy[i - 1] if i else 0.)) for i, value in enumerate(energy)]
    candidates = []
    for i in range(1, len(novelty) - 1):
        neighborhood = novelty[max(0, i - 50):min(len(novelty), i + 50)]
        threshold = max(.015, statistics.median(neighborhood) * 3)
        if novelty[i] > threshold and novelty[i] >= novelty[i - 1] and novelty[i] >= novelty[i + 1]:
            timestamp = i * hop / sample_rate
            if not candidates or timestamp - candidates[-1] >= .15:
                candidates.append(round(timestamp, 6))
    anchors = list(manual_anchors_s or [])
    if any(not 0 <= t <= duration for t in anchors):
        raise MediaError("Manual music anchor outside excerpt")
    assert_source_unchanged(asset)
    return {"asset_id": asset.id, "excerpt_start_s": excerpt_start_s, "duration_s": duration,
            "method": "pcm_rms_positive_difference_v1", "onsets_s": candidates,
            "source_onsets_s": [excerpt_start_s + t for t in candidates],
            "manual_anchors_s": anchors, "beat_grid_verified": False,
            "warning": "Onset proposals are not verified beats/downbeats; review anchors before beat-cut claims"}
