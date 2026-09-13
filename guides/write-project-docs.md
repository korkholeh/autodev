# Write project docs

Prose for the engineers who will maintain this code. Complete, specific, and true — this is the opposite end of the
scale from a step summary. Facts come from the repository, `.autodev/ARCHITECTURE.md`, `.autodev/DECISIONS.md`,
and the spec. Never from invention.

## Voice

- Lead with concrete facts and the commands and paths the reader needs. Do not restate the title in the first sentence.
- Short paragraphs, one idea each. Second person for instructions.
- State trade-offs and limits directly: what this does not do, where it breaks down, what would change the decision.
- Use the project's real names, real paths, real commands. Never a placeholder like `<your-app>` where a real name exists.
- Do not invent motivation, requirements, benchmarks, incidents, or numbers. If a fact was never established, leave it out.
- No marketing language. Phrases like "robust and scalable", "seamless", "comprehensive", "leverage", "delve into",
  "it is important to note", "in today's fast-paced world" are padding — cut them. This is guidance, not a word ban:
  use the word when it is the precise one.

## Where dev docs live

```
docs/dev/
  architecture.md      components, contracts, where state lives, why this shape
  adr/NNNN-*.md        one decision each (format in architecture.md)
  testing.md           how to run each layer of the suite, how to add a case, what is deliberately not tested
  development.md       set up, build, run, debug, common tasks
  operations.md        build/release/distribute; for a service: deploy, migrate, roll back, monitor
  troubleshooting.md   symptom → cause → fix, written to be followed while something is broken
```

`CLAUDE.md` at the repo root stays a short index (≤80 lines): stack, the exact commands, conventions, and links
into `docs/dev/`. It is read by every future agent session — keep it dense and current.

## Per document type

- **README** — what this is, who it is for, how to install and run it, then links. One screen.
- **Architecture** — a component map, the contracts between components, the data model, and the decisions that are
  expensive to reverse (link the ADRs rather than repeating them).
- **Testing** — the layers, the command for each, how to write a new case, and the known gaps.
- **Runbook / troubleshooting** — a symptom, then numbered steps with exact commands, then how to confirm recovery.
  Written to be followed by a tired person at 3am.
- **Release notes / CHANGELOG** — user-visible changes grouped by impact; breaking changes and migrations first.

## Keeping them true

A doc that contradicts the code is worse than a missing doc. When you change behaviour, change the document in the
same step. When you find a stale statement, fix it where you find it.
