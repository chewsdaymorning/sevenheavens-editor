"""Shared provisional contracts. Source seconds are PTS relative to stream origin."""
from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
from math import isfinite
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1-provisional"
Mode = Literal["live_ai", "assisted", "fixture"]


def new_id() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["0.1-provisional"] = SCHEMA_VERSION


class TimestampPoint(Contract):
    working_s: float = Field(ge=0)
    source_s: float = Field(ge=0)


class Asset(Contract):
    id: str = Field(default_factory=new_id)
    sha256: str
    original_path: str
    display_name: str | None = None
    working_path: str | None = None
    role: Literal["source", "reference", "music"] = "source"
    duration_s: float = Field(gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps_num: int = Field(default=0, ge=0)
    fps_den: int = Field(default=1, gt=0)
    rate_mode: Literal["cfr", "vfr", "unknown"] = "unknown"
    stream_origin_s: float = 0
    rotation_degrees: int = 0
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    pixel_format: str | None = None
    product_group: str | None = None
    has_audio: bool = False
    timestamp_mapping: list[TimestampPoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CandidateWindow(Contract):
    id: str = Field(default_factory=new_id)
    asset_id: str
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    evidence_ids: list[str] = Field(default_factory=list)
    sample_times_s: list[float] = Field(default_factory=list)
    analysis_run_id: str | None = None
    selection_mode: Mode
    action: str = ""
    framing: str = ""
    role: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    usable_handle_before_s: float = Field(default=0, ge=0)
    usable_handle_after_s: float = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_s <= self.start_s:
            raise ValueError("Candidate interval must have positive duration")
        if any(not isfinite(t) or t < 0 for t in self.sample_times_s):
            raise ValueError("Sample times must be nonnegative source PTS seconds")
        if self.selection_mode == "live_ai" and not (
            self.analysis_run_id and self.evidence_ids and self.sample_times_s
        ):
            raise ValueError("Live AI candidates require call and sampled-media evidence")
        return self


class ReferenceRecipe(Contract):
    id: str = Field(default_factory=new_id)
    asset_id: str
    mode: Literal["recreate", "adapt"]
    cut_times_s: list[float] = Field(default_factory=list)
    shot_roles: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    analysis_run_id: str | None = None


class MusicMap(Contract):
    id: str = Field(default_factory=new_id)
    asset_id: str
    excerpt_offset_s: float = Field(default=0, ge=0)
    beats_s: list[float] = Field(default_factory=list)
    onsets_s: list[float] = Field(default_factory=list)
    downbeats_s: list[float] = Field(default_factory=list)
    manual_anchors_s: list[float] = Field(default_factory=list)
    analysis_version: str = "manual"
    verified: bool = False
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered(self):
        for values in [self.beats_s, self.onsets_s, self.downbeats_s, self.manual_anchors_s]:
            if any(not isfinite(v) or v < 0 for v in values) or values != sorted(set(values)):
                raise ValueError("Music timestamps must be unique, ordered absolute source seconds")
        return self


class Brief(Contract):
    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1)
    directions: str = ""
    source_asset_ids: list[str] = Field(default_factory=list)
    reference_asset_id: str | None = None
    music_asset_id: str | None = None
    music_offset_s: float = Field(default=0, ge=0)
    reference_mode: Literal["recreate", "adapt"] = "recreate"
    duration_s: float | None = Field(default=None, gt=0)
    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    fps_num: int = Field(default=30, gt=0)
    fps_den: int = Field(default=1, gt=0)
    product_group: str | None = None
    allow_crop: bool = False
    hard_constraints: list[str] = Field(default_factory=list)
    processing_boundary: Literal["local_only"] = "local_only"
    cloud_budget_usd: float = Field(default=0, ge=0, le=0)


class Crop(Contract):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def bounds(self):
        if self.x + self.width > 1.00000001 or self.y + self.height > 1.00000001:
            raise ValueError("Crop exceeds normalized source bounds")
        return self


class Shot(Contract):
    id: str = Field(default_factory=new_id)
    asset_id: str
    candidate_id: str | None = None
    manual_override_reason: str | None = None
    source_start_s: float = Field(ge=0)
    source_end_s: float = Field(gt=0)
    timeline_start_frame: int = Field(ge=0)
    timeline_end_frame: int = Field(gt=0)
    crop: Crop | None = None

    @model_validator(mode="after")
    def boundaries(self):
        if self.source_end_s <= self.source_start_s or self.timeline_end_frame <= self.timeline_start_frame:
            raise ValueError("Shot source and timeline ranges must have positive duration")
        if not self.candidate_id and not self.manual_override_reason:
            raise ValueError("Shot requires candidate provenance or an explicit manual override")
        return self


class MusicPlacement(Contract):
    asset_id: str
    source_start_s: float = Field(default=0, ge=0)
    volume: float = Field(default=1, ge=0, le=2)


class TextOverlay(Contract):
    text: str = Field(min_length=1, max_length=500)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.85, ge=0, le=1)

    @model_validator(mode="after")
    def boundaries(self):
        if self.end_frame <= self.start_frame:
            raise ValueError("Text interval must have positive duration")
        return self


class EditPlan(Contract):
    id: str = Field(default_factory=new_id)
    project_id: str
    brief_id: str
    version: int = Field(default=1, gt=0)
    parent_plan_id: str | None = None
    mode: Mode
    fps_num: int = Field(default=30, gt=0)
    fps_den: int = Field(default=1, gt=0)
    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    shots: list[Shot] = Field(min_length=1)
    music: MusicPlacement | None = None
    text: list[TextOverlay] = Field(default_factory=list)
    operations: list[Literal["cut", "crop", "scale", "music", "text"]] = Field(default_factory=lambda: ["cut", "scale"])
    variation_label: str = "first edit"
    provenance: dict = Field(default_factory=dict)
    coverage_gaps: list[str] = Field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return self.shots[-1].timeline_end_frame * self.fps_den / self.fps_num


class Job(Contract):
    id: str = Field(default_factory=new_id)
    project_id: str
    plan_id: str | None = None
    stage: str
    status: Literal["queued", "running", "blocked", "failed", "succeeded", "cancelled", "needs_attention"] = "queued"
    mode: Literal["offline", "live_ai", "assisted", "fixture"] = "offline"
    progress: float = Field(default=0, ge=0, le=1)
    error: str | None = None
    artifacts: dict = Field(default_factory=dict)
    attempts: int = Field(default=0, ge=0)
    provider_request_id: str | None = None
    reserved_cost_usd: float = Field(default=0, ge=0)
    actual_cost_usd: float | None = Field(default=0, ge=0)
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)


class Correction(Contract):
    id: str = Field(default_factory=new_id)
    project_id: str
    plan_id: str
    new_plan_id: str | None = None
    shot_id: str | None = None
    reason: str = Field(min_length=1)
    scope: Literal["edit", "format", "reusable_rule"]
    changes: dict
    approval_state: Literal["proposed", "approved", "rejected"] = "approved"
    format_key: str | None = None
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now)


def quantize_seconds(seconds: float, fps_num: int, fps_den: int) -> int:
    """Round an absolute timeline timestamp; never sum rounded segment lengths."""
    value = Fraction(str(seconds)) * Fraction(fps_num, fps_den)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def validate_plan(plan: EditPlan, assets: dict[str, Asset], candidates: dict[str, CandidateWindow] | None = None, brief: Brief | None = None) -> EditPlan:
    if plan.width % 2 or plan.height % 2:
        raise ValueError("H.264 output dimensions must be even")
    if brief:
        if plan.project_id != brief.id or plan.brief_id != brief.id:
            raise ValueError("Plan project/brief identity does not match")
        if brief.music_asset_id:
            if not plan.music or plan.music.asset_id != brief.music_asset_id:
                raise ValueError("Required brief music may not be omitted or substituted")
            if abs(plan.music.source_start_s - brief.music_offset_s) > 0.000001:
                raise ValueError("Music excerpt offset differs from brief")
    previous_end = 0
    seen_shots: set[str] = set()
    for shot in plan.shots:
        if shot.id in seen_shots:
            raise ValueError("Duplicate shot ID")
        seen_shots.add(shot.id)
        if shot.asset_id not in assets:
            raise ValueError(f"Unknown asset: {shot.asset_id}")
        asset = assets[shot.asset_id]
        if asset.role != "source":
            raise ValueError("Timeline shots must use registered source footage")
        if shot.source_end_s > asset.duration_s + 0.000001:
            raise ValueError("Source interval exceeds asset duration")
        if shot.timeline_start_frame != previous_end:
            raise ValueError("Timeline contains a gap or overlap")
        previous_end = shot.timeline_end_frame
        source_duration = shot.source_end_s - shot.source_start_s
        timeline_duration = (shot.timeline_end_frame - shot.timeline_start_frame) * plan.fps_den / plan.fps_num
        if abs(source_duration - timeline_duration) > plan.fps_den / plan.fps_num + 0.000001:
            raise ValueError("Shot requires unsupported speed change")
        if shot.crop is not None and "crop" not in plan.operations:
            raise ValueError("Crop operation is not declared")
        if brief:
            if shot.asset_id not in brief.source_asset_ids:
                raise ValueError("Shot is outside the brief's selected source pool")
            if brief.product_group and asset.product_group != brief.product_group:
                raise ValueError("Confirmed product group does not match the brief")
            if shot.crop and not brief.allow_crop:
                raise ValueError("Cropping is not permitted by the brief")
        if shot.candidate_id:
            if candidates is None or shot.candidate_id not in candidates:
                raise ValueError("Unknown candidate; provide evidence or label a manual override")
            candidate = candidates[shot.candidate_id]
            if candidate.asset_id != shot.asset_id or shot.source_start_s < candidate.start_s - 0.000001 or shot.source_end_s > candidate.end_s + 0.000001:
                raise ValueError("Shot exceeds its evidenced candidate window")
            if plan.mode == "live_ai" and candidate.selection_mode != "live_ai":
                raise ValueError("Live AI plans require actual AI candidate provenance")
        elif plan.mode == "live_ai":
            raise ValueError("Manual selections must be labeled assisted")
    if plan.coverage_gaps:
        raise ValueError("Coverage gaps require an approved revised plan before render")
    if plan.music:
        if "music" not in plan.operations:
            raise ValueError("Music operation is not declared")
        music = assets.get(plan.music.asset_id)
        if not music or music.role != "music" or plan.music.source_start_s + plan.duration_s > music.duration_s + 0.000001:
            raise ValueError("Music excerpt is unavailable or too short")
    if plan.text and "text" not in plan.operations:
        raise ValueError("Text operation is not declared")
    if any(t.end_frame > previous_end for t in plan.text):
        raise ValueError("Text extends past the timeline")
    if brief:
        if (plan.width, plan.height, plan.fps_num, plan.fps_den) != (brief.width, brief.height, brief.fps_num, brief.fps_den):
            raise ValueError("Plan delivery format differs from brief")
        if brief.duration_s and abs(plan.duration_s - brief.duration_s) > plan.fps_den / plan.fps_num:
            raise ValueError("Plan duration differs from brief")
    return plan
