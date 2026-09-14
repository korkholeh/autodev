Step: PLAN — phase {{n}}/{{total}}: "{{title}}"

Context:
- Spec: `{{spec}}` · Architecture: `.autodev/ARCHITECTURE.md` · Risks: `.autodev/RISKS.md`
- Roadmap (all phases; this is #{{n}}): `.autodev/ROADMAP.md`
- Decisions so far (this phase and the one before it): `{{decisions_tail}}` — grep the older entries by topic
  rather than reading the whole file · Progress: `.autodev/PROGRESS.md`
- Conventions: `CLAUDE.md` · Stack commands: `.autodev/PROFILE.md`
- Plans of earlier phases: `.autodev/phases/*/PLAN.md` (skim only what's relevant)

Guides for this step: `.autodev/guides/context-efficient-work.md`, and `.autodev/guides/case-taxonomy.md` when you
decide which tests this phase needs.

Phase goal: {{goal}}

Deliverables:
{{deliverables}}

Acceptance criteria:
{{acceptance}}

Explore the current code to learn what already exists. Then write `{{phase_dir}}/PLAN.md` with sections:
1. `## Context` — what exists, what this phase changes, key files.
2. `## Design` — data models, interfaces/APIs, module layout, error handling, and how this phase honours the
   architecture. Any deviation from `.autodev/ARCHITECTURE.md` must be justified here and appended to DECISIONS.md.
3. `## Tasks` — ordered checklist `- [ ] T1: …`. Each task is small (one reviewable change), names the files to touch
   and the tests to add. Tests are tasks, not an afterthought.
4. `## Verification` — exact commands, and a table mapping every acceptance criterion to the test that proves it.
5. `## Risks` — which rows of `RISKS.md` this phase touches, and what the plan does about them.
6. `## Out of scope` — what belongs to later phases.

Do NOT implement anything now: the only files you may change are PLAN.md and DECISIONS.md.

Current test command: `{{test_command}}`. If it must change for this phase (e.g. the skeleton uses a different
runner), return the new command in `test_command`; otherwise return an empty string.
Structured output: status "done", summary (1–3 sentences), remaining_tasks = number of tasks.
