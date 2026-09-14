Step: DOCUMENTATION — phase {{n}}/{{total}}: "{{title}}"

The phase is built, tested and reviewed. Make the documentation true again before it is committed.

Read: `{{phase_dir}}/PLAN.md`, this phase's diff (`git diff {{base_sha}}`), `.autodev/ARCHITECTURE.md`,
this phase's decisions (`{{decisions_tail}}`), and the current `CLAUDE.md`, `docs/dev/`, `docs/user/`.

Guides: `.autodev/guides/write-project-docs.md` for anything a developer reads,
`.autodev/guides/user-docs.md` for anything a user reads.

Phase goal: {{goal}}

User-facing: {{user_facing}}

## Update, in this order

1. **`CLAUDE.md`** — the root index every future session reads. Commands, stack, conventions, layout. ≤ 80 lines.
   If a command changed in this phase, it changes here.
2. **`docs/dev/`** — architecture (components and contracts as they now exist, not as planned), testing (how to run
   each layer and how to add a case), development (set up, build, run, debug), operations (build, release, upgrade,
   roll back, where data lives), troubleshooting (symptom → cause → fix). Create only the pages this project has
   something true to say in; do not scaffold empty files.
3. **ADRs** — if this phase made a decision that is expensive to reverse and no ADR covers it, write one now under
   `docs/dev/adr/`. If it contradicted an existing ADR, mark that ADR superseded rather than editing history.
4. **`docs/user/`** — only when this phase is user-facing. Task-shaped pages using the exact labels, keys, flags or
   URLs the product now shows. Update `getting-started.md` when the first-run flow changed.
5. **`CHANGELOG.md`** — one entry per user-visible change, written in the user's language, under an `## Unreleased`
   heading. Breaking changes and migrations first.
6. **`README.md`** — keep the install/run instructions correct. Do not turn it into a manual; link into `docs/`.

## Rules

- Every command you write must be one you ran, or one that is already in `.autodev/PROFILE.md` and verified by this
  phase. Do not document an aspirational command.
- Where a doc contradicts the code, the code wins — fix the doc.
- Do not invent motivation, numbers, benchmarks, or features that do not exist in this build.
- Prose only where it carries information. A phase that changed nothing user-visible gets a `CLAUDE.md` line and a
  `docs/dev/` paragraph, not a new page.

Do not change application code or tests in this step. Do not commit.
Structured output: status done|partial|blocked, summary listing the files you updated and what is now documented.
