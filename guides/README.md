# Guides

Universal working rules for autonomous sessions. The orchestrator copies this directory into
`.autodev/guides/` at the start of a run; prompts point sessions at the one or two files they need.

Keep every guide short — a fresh session pays tokens for each read.

| Guide | Read it when |
|---|---|
| `context-efficient-work.md` | Starting any step: how much of the repo to read before editing |
| `architecture.md` | The architect step: choosing a shape, writing ADRs, building the risk register |
| `write-project-docs.md` | Writing README / ADR / runbook / dev docs prose |
| `user-docs.md` | Writing documentation for the people who use the product |
| `verify-change.md` | Before claiming a change works |
| `systematic-debugging.md` | A test fails or behaviour is wrong and needs diagnosis |
| `qa-oracles.md` | Deciding what "correct" means before writing a test |
| `case-taxonomy.md` | Enumerating the cases a feature needs |
| `e2e-authoring.md` | Writing or fixing an end-to-end spec that drives the real app |
| `screenshot-capture.md` | Photographing the product at the end of a phase |
| `review-rubric.md` | Reviewing a phase's diff |
| `concise-engineering-output.md` | Writing a summary, review, or progress note for an engineer |

Stack-specific commands and layout live in `.autodev/PROFILE.md`, not here.
