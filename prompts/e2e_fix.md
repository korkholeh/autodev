Step: FIX FAILING E2E — phase {{n}}/{{total}}: "{{title}}" (attempt {{attempt}}/{{max}})

The orchestrator ran `{{e2e_command}}` against the running surfaces and it failed. The output tail is in
`{{phase_dir}}/E2E_OUTPUT.txt`; the artefacts (screenshots, traces, logs) are under `e2e/artifacts/`.

Guides: `.autodev/guides/systematic-debugging.md`, then `.autodev/guides/qa-oracles.md` when you need to decide
whether an assertion is right.

A red end-to-end row is a product bug until proven otherwise:

- Find the root cause from the artefacts and the code. Reproduce it before changing anything.
- **Fix the product**, not the assertion. Add the unit test that should have caught it, then re-run.
- Change a spec only when the spec contradicts the plan's oracle or the spec file drove the app incorrectly (wrong
  locator, wrong step order). Log the reasoning in `.autodev/DECISIONS.md`.
- Never delete, skip or weaken a case to go green. If a case genuinely cannot be decided without a human, move it to
  the plan's `deferred_not_authored` with the reason and record it in `.autodev/DECISIONS.md` — that is visible;
  a quietly deleted test is not.
- A surface that is not reachable is an environment problem: report it and return `blocked` rather than deleting the
  cases that need it.

Re-run `{{e2e_command}}` until it passes. Do not start or stop the surfaces. Do not commit.
Structured output: status done|partial|blocked, summary of root causes, product fixes, and anything deferred.
