"""Constrained assembly of model-selected windows, using absolute frame boundaries."""
from __future__ import annotations

from math import isfinite

from .contracts import Brief, CandidateWindow, EditPlan, MusicPlacement, Shot, TextOverlay, quantize_seconds, validate_plan


class CoverageError(ValueError):
    pass


def timeline_slots(reference_cuts, reference_duration, brief: Brief, music_anchors=None):
    duration = brief.duration_s or reference_duration
    if not isfinite(duration) or duration <= 0:
        raise CoverageError("A positive reference/output duration is required")
    points = [0.] + sorted(set(float(t) for t in reference_cuts if 0 < t < reference_duration)) + [reference_duration]
    boundaries = [p / reference_duration * duration for p in points]
    # Another selected track requires rhythm adaptation. Manual anchors or
    # measured onsets are absolute excerpt-relative proposals, never called beats.
    anchors = sorted(set(float(t) for t in (music_anchors or []) if 0 < t < duration))
    if brief.music_asset_id and anchors:
        aligned = [0.]
        for i, wanted in enumerate(boundaries[1:-1], 1):
            tolerance = min(boundaries[i]-boundaries[i-1], boundaries[i+1]-boundaries[i]) * .3
            options = [a for a in anchors if abs(a-wanted) <= tolerance and a > aligned[-1]]
            aligned.append(min(options, key=lambda a: abs(a-wanted)) if options else wanted)
        boundaries = aligned + [duration]
    frames = [quantize_seconds(t, brief.fps_num, brief.fps_den) for t in boundaries]
    if any(b <= a for a, b in zip(frames, frames[1:])):
        raise CoverageError("Reference cuts collapse at the selected output frame rate; revise duration or cut structure")
    return [{"slot_index": i, "start_frame": a, "end_frame": b,
             "duration_s": (b-a)*brief.fps_den/brief.fps_num,
             "reference_start_s": points[i], "reference_end_s": points[i+1]}
            for i, (a, b) in enumerate(zip(frames, frames[1:]))]


def build_plan(brief, assets, candidates, slots, decision, *, recipe_id, planning_run_id,
               analysis_run_ids, version=1, mode="live_ai", music_warning=None):
    """The model chooses candidate and offset; this layer only rejects invalid choices."""
    if decision.get("coverage_gaps"):
        raise CoverageError("; ".join(str(g) for g in decision["coverage_gaps"]))
    if decision.get("constraints_satisfied") is not True:
        raise CoverageError("The model could not confirm the explicit editorial constraints")
    choices = decision.get("selections")
    if not isinstance(choices, list) or len(choices) != len(slots):
        raise CoverageError("The model did not fill every reference shot slot")
    by_slot = {}
    by_id = {c.id: c for c in candidates}
    for choice in choices:
        index = choice.get("slot_index")
        if type(index) is not int or index in by_slot or not 0 <= index < len(slots):
            raise CoverageError("Model returned duplicate or unknown shot slots")
        by_slot[index] = choice
    shots = []
    reasons = []
    for slot in slots:
        choice = by_slot[slot["slot_index"]]
        candidate = by_id.get(choice.get("candidate_id"))
        if candidate is None:
            raise CoverageError("Model selected an unknown candidate ID")
        start = choice.get("source_start_s")
        if type(start) not in (int, float) or not isfinite(start):
            raise CoverageError("Model source start must be finite seconds")
        end = start + slot["duration_s"]
        if start < candidate.start_s - 1e-6 or end > candidate.end_s + 1e-6:
            raise CoverageError(f"Selected candidate cannot cover reference slot {slot['slot_index']+1}")
        if choice.get("confidence", 0) < .5 or not choice.get("reason"):
            raise CoverageError("A sequence choice is uncertain or lacks an editorial reason")
        if any(s.asset_id == candidate.asset_id and max(s.source_start_s,start) < min(s.source_end_s,end)-1e-6 for s in shots):
            raise CoverageError("Reference slots reuse overlapping source footage; choose distinct usable moments or report missing coverage")
        shots.append(Shot(asset_id=candidate.asset_id, candidate_id=candidate.id,
                          source_start_s=start, source_end_s=end,
                          timeline_start_frame=slot["start_frame"], timeline_end_frame=slot["end_frame"]))
        reasons.append({**choice, "source_end_s": end})
    text = [TextOverlay.model_validate(value) for value in decision.get("text", [])]
    plan = EditPlan(project_id=brief.id, brief_id=brief.id, version=version, mode=mode,
                    fps_num=brief.fps_num, fps_den=brief.fps_den, width=brief.width, height=brief.height,
                    shots=shots, text=text, music=MusicPlacement(asset_id=brief.music_asset_id, source_start_s=brief.music_offset_s) if brief.music_asset_id else None,
                    operations=["cut", "scale"] + (["music"] if brief.music_asset_id else []) + (["text"] if text else []),
                    variation_label="Reference recreation" if brief.reference_mode == "recreate" else "Reference adaptation",
                    provenance={"recipe_id": recipe_id, "planning_run_id": planning_run_id,
                                "analysis_run_ids": analysis_run_ids, "selection_decisions": reasons,
                                "source_time_basis": "decoded original-relative PTS seconds",
                                "music_timing_warning": music_warning,
                                "semantic_acceptance": "pending human review"})
    validate_plan(plan, assets, by_id, brief)
    return plan
