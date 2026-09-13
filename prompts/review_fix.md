Step: APPLY REVIEW FIXES — phase {{n}}/{{total}}: "{{title}}" (round {{round}})

Read the review `{{phase_dir}}/REVIEW-r{{round}}.md` and the plan `{{phase_dir}}/PLAN.md`.

- Fix every blocker and major finding.
- Fix minor findings when the fix is small and safe; skip nits unless trivial.
- If a finding is wrong (it contradicts the spec, the architecture, or a logged decision), leave the code and append
  your reasoning to `.autodev/DECISIONS.md`. Do not silently ignore it.
- Add or adjust tests for every bug you fix — a fix with no test invites the same regression back.

Run `{{test_command}}` and make sure it passes. Never weaken a test to get there. Do not commit.
Structured output: status, summary listing fixed / rejected findings.
