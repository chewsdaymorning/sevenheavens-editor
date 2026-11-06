# Project instructions — seed for the new application repository
Adapt after checking the chosen project root. This is not an installed skill.

## Goal
Ship the agreed local AI footage-selection/editing prototype. Completion requires actual user-media acceptance, not only scaffolding.

## Context sources
Read PROJECT_BRIEF.md, docs/STATUS.md and current docs/DECISIONS.md. The user's direct answers override proposed defaults. Treat old research as leads to reverify.

## Collaboration
- Orchestrator owns shared schemas, integration, dependency declarations and commits.
- Assign non-overlapping paths before parallel edits.
- Workers report actual changes, checks, evidence and blockers.
- Use available native subagent tools; do not invent a delegation API.
- When unavailable, run specialist workstreams sequentially.

## Media and execution
- Originals are read-only. Work with explicit source IDs, valid ranges and defined timestamp mapping.
- Do not scan unrelated personal folders.
- Do not submit source media externally or exceed configured spend without applicable authorization.
- Keep originals, references, generated media, local databases, model files and secrets out of Git.
- Do not auto-post, buy ads, create cloud infrastructure or push a remote.
- Preserve existing user changes and prior output versions.

## Truthful modes and feedback
- Distinguish live AI, assisted and fixture modes.
- No filename/random/clip-start fallback masquerading as visual selection.
- Persist scoped user feedback. Workflow memory is not model-weight training.
- Record material unknowns and actual failed checks. Ask specific open questions when blocked.

## Verification and handoff
- Meaningful tests check media integrity, timing, constraints, persistence and failures.
- Semantic quality needs human-confirmed expectations and real footage.
- Keep docs/STATUS.md, DECISIONS.md, TASKS.md and EVIDENCE.md concise enough to resume.
- Run independent critique, targeted repair and recheck before delivery.
- State what actually works, how to reproduce it, and which acceptance checks remain pending.
