Step: FIX FAILING TESTS — phase {{n}}/{{total}}: "{{title}}" (attempt {{attempt}}/{{max}})

The orchestrator ran `{{test_command}}` and it failed. The output tail is in `{{phase_dir}}/TEST_OUTPUT.txt` — read it,
then read `{{phase_dir}}/PLAN.md` for intent.

Guide for this step: `.autodev/guides/systematic-debugging.md`. Reproduce, localize, form one hypothesis, change one
thing, re-test. Do not shotgun edits.

- Fix the code, not the tests. Change a test only if the test itself contradicts the spec or PLAN.md, and log why in
  `.autodev/DECISIONS.md`.
- Never skip, delete, `xfail` or weaken a test to get green. A suite that certifies the bug is worse than a red one.
- Environmental failures (missing dependency, service, env var, fixture) → fix the project setup so the command works
  non-interactively on a clean machine (dependency files, test config, fixtures, an in-process database for tests).
- If the test command itself is wrong for this project, fix the project so the command works; don't silently change
  what it runs. If it must change, say so in the summary.

Re-run `{{test_command}}` until it passes. Do not commit.
Structured output: status done (suite passes) | partial | blocked, summary of root causes and fixes.
