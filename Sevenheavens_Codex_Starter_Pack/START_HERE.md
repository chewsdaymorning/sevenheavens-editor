# Sevenheavens AI Editor — Codex starter pack
Prepared 6 November 2026. This pack specifies a build; it does not contain an implemented editor.

## Intended result
A local application in which Tony selects his own shooting footage, provides a reference and directions, generates complete clean-cut videos, previews the actual outputs, and saves corrections that influence subsequent edits.

## Setup before starting
1. Choose a separate project folder outside the Obsidian vault. Suggested path: /Users/tony/Projects/sevenheavens-editor.
2. Extract this pack into that folder. Keep its files together.
3. Open that folder as the active Codex workspace. Do not execute the build from /Users/tony/Desktop/Obsidian.
4. Create a local Git repository there, or let Codex do this after checking the location.
5. Keep footage, model files, caches, credentials and generated videos outside Git. Use an explicitly selected media folder or SSD. GitHub and Git LFS are not required for the first test.
6. Paste the launch instruction below. Codex should perform intake and read-only preflight, ask material open questions, then build once the necessary decisions are answered.

Optional terminal preparation — instructions for you, not actions already performed:
```sh
mkdir -p "$HOME/Projects/sevenheavens-editor"
cd "$HOME/Projects/sevenheavens-editor"
git init
```

The suggested folder must be opened in Codex to become its active writable workspace. Installing or opening another editor is not required before the toolchain check.

## Launch instruction
```text
Read MASTER_PROMPT.md and PROJECT_BRIEF.md completely. Treat TASK_GRAPH.md as the dependency plan and UPSTREAM_REGISTRY.md as candidate research leads, not verified installed capabilities. Start with Phase 0: inspect this workspace, identify the few consequential missing decisions, and ask me open questions. Continue independent read-only checks while waiting. Once I answer the decisions needed for implementation, carry the project through to the real-media prototype and acceptance gates. Do not stop at a plan or UI scaffold, and do not claim an untested feature works.
```

## Git versus GitHub
- The project directory contains the application and its own instructions.
- Local Git records code changes and supports controlled integration between agents. It is recommended from the start.
- A private GitHub remote is optional for backup, sharing and later collaboration. You can start without an account or remote.
- Reading public upstream repositories does not require creating your own GitHub repository.
- Do not create or push a remote until Tony identifies the intended account/repository and authorizes it. Do not upload footage to the code repository.
- This current Obsidian workspace was checked and was not a Git repository. Do not initialize Git at its root for this project.

## Pack contents
- MASTER_PROMPT.md — full orchestrator instruction to paste or have Codex read.
- PROJECT_BRIEF.md — product boundary, proposed defaults and unresolved decisions.
- TASK_GRAPH.md — dependency graph, owners and completion evidence.
- UPSTREAM_REGISTRY.md — GitHub sources and adoption rules.
- OPEN_QUESTIONS.md — open intake questions and how to record the answers.
- AGENTS.template.md — project instruction seed; Codex adapts it after preflight.
- ACCEPTANCE.md — technical, editorial and delivery checks.

No application was installed, no project repository was initialized, and no footage was processed while preparing this pack.
