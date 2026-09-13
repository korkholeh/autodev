Step: FINALIZE — all {{total}} phases are built, tested, reviewed and committed.

This is the last session of the run. A developer will read what you leave behind, in the morning, with no memory of
any of it. Make the repository self-explanatory and tell the truth about its state.

Read: `.autodev/ROADMAP.md`, `.autodev/PROGRESS.md`, `.autodev/DECISIONS.md`, `.autodev/RISKS.md`,
`.autodev/ARCHITECTURE.md`, every `.autodev/phases/*/PLAN.md` and `REVIEW-r*.md` (skim), the current `docs/` tree,
and `git log --oneline {{base_sha}}..HEAD`.

Guides: `.autodev/guides/write-project-docs.md`, `.autodev/guides/user-docs.md`,
`.autodev/guides/concise-engineering-output.md` for the summaries.

## Produce

1. **A documentation consistency pass.** `README.md`, `CLAUDE.md`, `docs/dev/`, `docs/user/`: remove what is no longer
   true, fill what phases left open, make every command in them one that works from a clean checkout. Verify the
   install/build/test/run/e2e commands by running them — do not certify a command you did not run.
2. **`docs/user/README.md`** — the index a user starts from: what this product does, how to install it, and the path
   through the pages in the order a new user needs them.
3. **`docs/dev/architecture.md`** — reconciled with what was actually built. Where the implementation diverged from
   `.autodev/ARCHITECTURE.md`, the built system is the truth; note the divergence and link the decision.
4. **`CHANGELOG.md`** — turn `## Unreleased` into the first release section with today's date, grouped by impact,
   breaking changes first.
5. **`.autodev/HANDOFF.md`** — the morning briefing, one screen:
   - **What was built** — three sentences.
   - **State** — every check that ran and its result, by name (`{{test_command}}`, the e2e command, the linter).
     Separate verified from assumed.
   - **Decisions a human should confirm** — the entries from `DECISIONS.md` that a developer might overrule,
     with the reasoning, not all of them.
   - **Known gaps** — unfinished tasks, warnings from PROGRESS.md, every `deferred_not_authored` case in the e2e
     plans, and anything that needs credentials, hardware or a product answer.
   - **Open risks** — the rows of `RISKS.md` that are still live.
   - **Next steps** — what you would do first tomorrow, in order.
6. **`.autodev/PR_BODY.md`** — a reviewer-facing description of the whole branch: one sentence on what now works,
   a short *Why*, then **Worth a close look** — only the parts that need human judgment (a security or money path, a
   migration, a public contract, a deliberate trade-off, anything incomplete). Do not narrate the diff.

Do not change application code in this step, except to fix a command or a path that the documentation must state
correctly. Do not commit.

Structured output: status done|partial|blocked, summary (what is shippable, what is not, and the single most
important thing for the developer to look at first).
