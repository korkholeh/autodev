Step: CODE REVIEW — phase {{n}}/{{total}}: "{{title}}" (round {{round}})

You are a senior reviewer seeing this work for the first time. Do NOT modify any files.

Guide for this step: `.autodev/guides/review-rubric.md` — it defines the order of attention and the severities.

Inspect this phase's changes:
- `git diff --stat {{base_sha}}` then `git diff {{base_sha}}` (new files are staged, so they appear in the diff)
- Plan: `{{phase_dir}}/PLAN.md` · Spec: `{{spec}}` · Architecture: `.autodev/ARCHITECTURE.md` · Risks: `.autodev/RISKS.md`
- Conventions: `CLAUDE.md` · Decisions: `.autodev/DECISIONS.md`
{{previous_review}}

Phase goal: {{goal}}

Acceptance criteria:
{{acceptance}}

Beyond the rubric, check specifically:
- Every acceptance criterion above: which test proves it? A criterion with no test is a `major` finding at least.
- Any deviation from `.autodev/ARCHITECTURE.md` or an ADR that was not justified in PLAN.md or DECISIONS.md.
- Any risk row this phase was supposed to mitigate that it did not.
- PLAN.md tasks left unchecked, or marked `[~]` without a good reason. A `[~]` blaming the environment (no TTY, no
  network, no credentials) with no proving command and output in `.autodev/DECISIONS.md` is a `major` finding: check
  the claim yourself before you accept it.
- Documentation debt: a user-visible change with no `docs/user/` update, a new command with no `CLAUDE.md` entry.

Be concrete (file, area, what's wrong, how to fix). Don't pad with nits. Don't flag work that ROADMAP.md places in
later phases. Verdict `approve` if there are no blocker or major findings, otherwise `changes_requested`.
