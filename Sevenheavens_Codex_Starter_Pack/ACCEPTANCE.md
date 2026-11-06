# Prototype acceptance contract
This is the proposed test contract. Confirm the creative brief and required outputs during intake.

## The tangible result
Tony opens a local UI, selects real source footage plus his reference and music, gives directions, sees genuine analysis/selection progress, inspects selected source moments, plays a complete own-footage edit, corrects a decision and renders a new version.

First accept one vertical slice; then test three independent pieces sharing cached analysis.
The human creative-quality decision is separate from automated technical checks.

| Scenario | Required evidence |
|---|---|
| Local start and persistence | Documented setup/start works; project, job and correction remain after restart. |
| Real end-to-end editing | Actual configured visual analysis selects intervals and a complete video plays; all shots resolve to imported sources. Sanitized model inputs/results tie selected candidate IDs and source windows to the plan; manual overrides are identified. |
| Moment inside a long take | Human-confirmed relevant action occurs within a longer recording; selection finds a useful bounded interval rather than only clip beginnings. |
| Reference and directions | Observed recipe and explicit hard constraints are reflected in the plan/output; uncertainty remains visible. |
| Correct product/crop | Confirmed product groups are honored and required garment/product areas remain visible. |
| Missing coverage | A deliberately unavailable shot produces a gap or explicit approved redesign, not fabricated media or false completion. |
| Musical timing | Absolute timestamp quantization passes known fixtures; real selected track/anchors receive listening and visual review. |
| Media integrity | Original hashes remain unchanged; source bounds, rotation, mixed rates, VFR mapping, color and audio are handled or explicitly blocked. |
| Feedback | A scoped correction persists, produces a new version and affects the next appropriate plan without rewriting old outputs. |
| Independent batch | Three jobs have distinct plans/output paths and agreed meaningful editorial differences, such as different opening/source sequences or separate briefs. Cache is reused; one failure does not overwrite another job. Label variants versus distinct concepts; renamed duplicates do not pass. |
| Failure and cancellation | Missing credentials, invalid model response, unavailable media, budget exhaustion and cancellation create honest recoverable states. |
| Native handoff, if required | Actual project reopens with available media and tested editable operations. MP4 existence does not establish NLE editability. |

## Evidence ladder
1. Researched: primary documentation describes it.
2. Installed: local executable/package/version found.
3. Executed: the specific operation ran with recorded results.
4. Technically verified: output decoded/inspected and invariants passed.
5. Editorially accepted: Tony judges the real piece on brief.

Never collapse these levels into "verified." Fixture tests establish plumbing only.
If footage or model access is unavailable, report implemented infrastructure and the exact pending real-media checks.

## Independent review questions
- Can Tony reproduce the flow without the original agent session?
- Does the live path genuinely analyze/select footage?
- Are source windows and user directions traceable?
- Did any fallback weaken the goal silently?
- Are decisions, corrections and outputs durable?
- Does the result satisfy the brief, not merely render?
- Which claim has no observed evidence?
- What fails on an unseen shoot?

## Practical measurement
Record cold-start setup/indexing cost separately from repeat-use cost. Include preparation, review, correction, failed attempts, model charges and render time. Report accepted distinct pieces, not only render count. A saved correction influencing a plan demonstrates preference reuse; it does not prove a generally trained editor or commercial lift.
