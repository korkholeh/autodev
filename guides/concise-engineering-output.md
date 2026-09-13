# Concise engineering output

For step summaries, review findings, debugging results, progress notes — anything an engineer reads to decide
what happens next. Not for ADRs, runbooks, release notes, or user docs (those must be complete: see
`write-project-docs.md` and `user-docs.md`).

- Lead with the outcome. First line answers the question.
- Do not restate the task back.
- Cut intros, filler, and narration of the process ("Let me…", "As you can see", "Great, now I will…").
- Use concrete names: exact paths, commands, error strings, symbols. Not "the relevant file".
- Keep reasoning that affects a decision. Brevity is not omission of the *why* behind a choice.
- Never hide assumptions, failures, security issues, or rollout risk to sound cleaner. Surface them.
- Professional prose, not telegraphic fragments.

Closing shape for a completed step (skip empty sections, never pad one):

```
Changed:
- <file/area> — <what and why>

Verified:
- <command that actually ran> — <result>

Risks:
- <risk / breaking change / follow-up>

Not verified:
- <what you did not check and why>
```
