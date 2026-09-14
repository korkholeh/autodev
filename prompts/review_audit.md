Step: AUDIT THE FIXES — phase {{n}}/{{total}}: "{{title}}" (round {{round}})

This phase has used up its review rounds, so these fixes are the last thing that happens to the code before it is
committed. Nobody has looked at them. You are that look — and only at them. Do NOT modify any files.

What the fix session changed, and nothing else:
- `git diff --stat {{fix_tree}}` then `git diff {{fix_tree}}` (the tree as it was before the fixes ran)

What it was supposed to do:
- The review it was answering: `{{phase_dir}}/{{review_file}}`
- Plan: `{{phase_dir}}/PLAN.md` · Conventions: `CLAUDE.md` · Decisions for this phase: `{{decisions_tail}}`
- Guide: `.autodev/guides/review-rubric.md` — the same severities as a full review

Three questions, in this order:
1. Is every blocker and major finding in that review actually fixed — in the product, by this diff — and is there a
   test that fails without the fix? A finding the summary calls fixed but the diff does not fix is a `blocker`.
2. Did the fixes break something else, or contradict the spec, `.autodev/ARCHITECTURE.md` or a logged decision?
3. Was any finding rejected? A rejection is legitimate only if `.autodev/DECISIONS.md` argues it from the spec, the
   architecture or a decision already logged. An unargued rejection is a `major`.

Do not re-review the rest of the phase: anything outside this diff has already been through its rounds, and raising
it here only delays the commit. Do not raise nits.

Verdict `approve` if the fixes hold, otherwise `changes_requested` with the findings that must still be fixed.
