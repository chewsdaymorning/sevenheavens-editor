# Product brief — first prototype
Status: proposed implementation brief; user-specific intake decisions remain open.

## Product
A local tool for Sevenheavens that turns Tony's own shooting material, a supplied reference and written directions into complete clean-cut content for TikTok, Instagram and Meta ads.

Tony supplies references. Automatic inspiration discovery is excluded.

## Proposed first slice
- One small shoot and one content family, such as a clean outfit montage.
- One supplied reference, one chosen music excerpt and explicit directions.
- First produce one complete playable portrait edit. Then produce three independent pieces or variants from the cached catalogue with agreed editorial differences. Label variants versus distinct concepts; do not count renamed copies.
- Hard cuts, permitted reframing, music placement and simple optional text.
- Real visual analysis for source-window selection; deterministic plan validation and rendering.
- Preview selected shots, source times, coverage gaps and finished outputs.
- Replace a shot/change a rule, save correction scope, and rerender.
- Persist projects and job state across restarts.

9:16 at 1080x1920 is a proposed initial delivery preset, not a requirement that all Meta placements use that format. Confirm the actual brief. Frame rate follows the chosen workflow and input inspection.

## Important distinctions
- Reference reconstruction: reproduce shot roles, structure and timing where footage allows.
- Style adaptation: make a new edit with selected characteristics of a reference.
- Preference memory: reuse approved profiles, examples and scoped corrections.
- Model training: change parameters using a defined dataset and evaluation; outside first build.
- Technical validity: the file decodes and conforms.
- Editorial acceptance: Tony judges the piece useful and on brief.
- Performance: audience or commercial outcomes; cannot be inferred causally from a reference alone.

## Learning record
Store the brief, available source pool, selected and explicitly rejected candidates, exact timeline decisions, Tony's corrections/reasons, scope, recipe version and approved result. Unused footage is not inherently a negative label.

## Input organization
Use a selected media root or imported copies. Originals remain unchanged. Assign stable IDs and register technical metadata. Confirm product/outfit grouping from reliable supplied metadata; do not guarantee SKU from visual appearance alone. Analyze usable intervals inside long takes, not only cut boundaries.

## Proposed architecture
Python backend + SQLite + local job worker + minimal browser UI. Separate:
1. media/indexing,
2. reference/music analysis,
3. constrained footage selection/planning,
4. plan validation,
5. renderer/editor adapters,
6. review/feedback.

Choose actual UI/server libraries after environment checks. A simple shot list with preview/replacement is sufficient; no general timeline editor is needed.

Canonical internal plans must remain editor independent. FFmpeg is the minimal execution candidate. Resolve/OpenShot is an optional or required native adapter depending on Tony's editability answer.

## Operating modes
- Live AI: actual permitted analysis/selection calls.
- Assisted: user supplies or corrects selections; clearly labeled.
- Fixture: development/test data only; clearly labeled.

Never silently switch modes.

## Boundaries
- Local prototype first; no public deployment, social posting or ad-account changes.
- No generated replacement footage, VFX-heavy collage, scraping, model fine-tuning or distributed cluster initially.
- No selected model/provider or recurring spend has been authorized by this starter pack.
- No fixed video quality, automation percentage or throughput has been demonstrated.
- Existing research should guide spikes, not lock the architecture to a vendor.

## Runtime data
Keep originals, references, proxies, models, databases, outputs and secrets outside source control. A remote code repository does not store the media library.
