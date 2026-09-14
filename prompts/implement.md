Step: IMPLEMENT — phase {{n}}/{{total}}: "{{title}}" (session {{run}})

Read first: `{{phase_dir}}/PLAN.md`, `CLAUDE.md`, `.autodev/PROFILE.md`, `.autodev/DECISIONS.md`. Spec: `{{spec}}`.

Guides for this step: `.autodev/guides/context-efficient-work.md` and `.autodev/guides/verify-change.md`.
If something behaves unexpectedly, switch to `.autodev/guides/systematic-debugging.md` instead of guessing a patch.

Work through the unchecked tasks of PLAN.md in order. For each task:
1. Implement it together with its tests.
2. Run the narrowest sufficient checks for what you touched (the full suite is `{{test_command}}`).
3. Immediately mark it done in PLAN.md (`- [x]`) so the work is resumable if this session is interrupted.
   If a task proves wrong or unnecessary, mark it `- [~] … (reason)`; if something is missing, add a task.
   An environment limitation is only a reason with the command that proves it, and its output, in `.autodev/DECISIONS.md`.

Already-checked tasks were completed by a previous session: don't redo them, but repair them if they're broken.
Keep the code consistent with `CLAUDE.md` and the patterns already in the repository; update `CLAUDE.md` when you add
a command or a convention.

Before finishing, run the full test suite once, and the linter from `.autodev/PROFILE.md`. Do not commit.
If your context is getting full before all tasks are done, stop at a clean point with PLAN.md up to date and return `partial`.
Structured output: status done|partial|blocked, summary of what was built, remaining_tasks (unchecked count).
