Step: ARCHITECT — the design pass that happens before any roadmap or code.

Read, in this order: the specification `{{spec}}`, `.autodev/INTAKE.md` if it exists (the developer's answers —
they outrank your preferences), `.autodev/PROFILE.md` (the stack profile chosen for this run), then explore the
repository (it may be empty, or an existing codebase you must fit into).

Guides for this step: `.autodev/guides/architecture.md`, then `.autodev/guides/context-efficient-work.md`.

Your job is the judgment a generated codebase cannot supply for itself: what this system must not get wrong, what
shape survives that, and what it will cost to run. Do not write application code.

Produce:

**1. `.autodev/ARCHITECTURE.md`** — the design of record:
- `## Problem` — what the product does and for whom, in the spec's own terms.
- `## Constraints` — platform, runtime versions, delivery channel, team size, offline/network assumptions, anything
  the intake fixed.
- `## Shape` — components, each one's responsibility, the contracts between them, where state lives, and every trust
  boundary. Justify each component's existence in one sentence; delete any you cannot justify.
- `## Data` — the entities, their relationships, identity and ownership, and what must never be lost.
- `## Cross-cutting` — authentication and authorization, input validation, error handling, logging/observability,
  configuration and secrets, internationalization if required, accessibility if the product has a UI.
- `## Non-functional requirements` — concrete numbers (volume, concurrency, latency, size, supported versions). Where
  the spec is silent, choose defensible values and mark them as assumptions.
- `## Failure modes` — for each external dependency and each multi-step operation: timeout, retry, duplicate,
  partial completion, unknown outcome, restart mid-flight. Say which are handled and how.
- `## Delivery and operations` — how it is built, packaged, released, upgraded, and how user data survives an upgrade.
- `## Rejected alternatives` — the shapes you considered and why they lost.

**2. `docs/dev/adr/NNNN-<kebab-title>.md`** — one ADR per decision that is expensive to reverse (storage, auth model,
sync model, process/threading model, UI framework, packaging, public API shape). Use the format in the architecture
guide. Expect roughly 3–8 of them. Do not write an ADR for a choice a later phase can freely change.

**3. `.autodev/RISKS.md`** — the risk register table from the guide, ordered by expected cost, each row naming the
mitigation and where it will be handled. Include product risk (we build the wrong thing), not only technical risk.

**4. `.autodev/PROFILE.md`** — correct it against reality: replace every `TODO` with the exact command this project
will use, fix anything the profile assumed wrongly, and delete guidance that does not apply here. The `screenshot`
row is one of those commands: the screenshot step reads it to photograph the product at the end of each phase, so
name the way this project can actually capture a frame headlessly (or say plainly that it has no visual surface).
Later sessions trust this file; leave nothing aspirational in it.

Also append the assumptions you made to `.autodev/DECISIONS.md`.

The orchestrator runs the commands you return, so it accepts only plain toolchain invocations: each one must
start with a known build or test binary (`make`, `uv`, `python`, `pytest`, `npm`, `npx`, `cargo`, `swift`,
`xcodebuild`, `go`, `docker`, `gradle`, …), optionally chained with `&&`. A command that fetches or evaluates code,
needs `sudo`, or runs a shell script of the project's own is refused, and the run keeps whatever command it had.
`e2e_up_command` must return once the surfaces are up — background what keeps running.

Commands you return must be non-interactive and runnable from the repository root. If the project does not exist yet,
give the commands that will work once phase 1 has created the skeleton — phase 1 is then responsible for making them
true. Use `-` for a command that is genuinely not needed (for example an e2e suite that starts nothing).

Structured output: status, summary (3–5 sentences: the shape and the single biggest risk), stack (one line),
test_command, lint_command, e2e_command, e2e_up_command, e2e_down_command, adrs (list of titles), top_risks (list).
