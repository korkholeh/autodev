Step: ROADMAP

Read the specification `{{spec}}`, then `.autodev/ARCHITECTURE.md`, `.autodev/RISKS.md` and `.autodev/PROFILE.md`
(the architect step wrote all three), then explore the repository.

Guide for this step: `.autodev/guides/context-efficient-work.md`.

Design a phased development roadmap:
- Scale to the spec: typically 3–10 phases. Each phase is a coherent, shippable increment that leaves the project
  building, with the full test suite passing.
- If there is no project skeleton yet, phase 1 creates it: structure, dependency management, test runner,
  linter/formatter, the end-to-end harness with one trivial passing case, one trivial passing unit test, and every
  command from `.autodev/PROFILE.md` working from the repository root on a clean checkout.
- Order by dependency, and put the top entries of `RISKS.md` early — data model, auth, the risky integration. Polish late.
- Size each phase so one focused session can implement it (roughly ≤ 15 concrete tasks).
- Every phase ships automated tests for what it delivers. Acceptance criteria must be verifiable by a test, a command,
  or observable behaviour — never "works well".
- Mark a phase `user_facing: true` when it delivers something a user can see or operate. Those phases get end-to-end
  cases and user documentation; the others do not.
- Every acceptance criterion in the spec must be covered by exactly one phase. Say which phase closes which risk.

Also in this step:
- Confirm or correct the one shell command that runs the whole unit/integration suite from the repository root,
  non-interactively (`.autodev/PROFILE.md` has the candidate). Return it in `test_command`.
- Create or update `CLAUDE.md` in the repository root (≤ 80 lines): overview, stack, install/test/lint/run/e2e
  commands, conventions, and the line:
  "Autodev docs: .autodev/ (ARCHITECTURE.md, RISKS.md, ROADMAP.md, PROGRESS.md, DECISIONS.md, phases/NN-*/PLAN.md)".
- Record assumptions about gaps in the spec in `.autodev/DECISIONS.md`.
- Do NOT write application code.

Structured output: project_name, summary (3–5 sentences), test_command, assumptions, phases[] with title,
slug (kebab-case), goal, deliverables[], acceptance_criteria[], user_facing (boolean).
