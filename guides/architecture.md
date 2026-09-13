# Architecture, decisions, and risk

Complexity is not proof of quality. Choose the simplest structure that survives the requirements and the risks
the spec actually states. Every abstraction needs a reason you can write down in one sentence.

## Choosing the shape

Work from constraints, in this order:

1. **What the product must do** — the spec's user-visible behaviour and its data.
2. **What it must not get wrong** — money, identity, permissions, data loss, privacy, legal/offline requirements.
3. **How it is delivered** — a desktop app the user installs, a mobile app that goes through review, a terminal
   binary, a server someone deploys and operates. Delivery decides packaging, updates, and migrations.
4. **Who operates it** — one developer, or a team with CI and on-call. Operability cost is design input.

Defaults that are usually right until a stated requirement breaks them: one process, one datastore, a single
deployable unit, a synchronous path, a plain library boundary instead of a service boundary. Reach for queues,
caches, extra services, event sourcing, or plugins only when the spec's own numbers or constraints demand it.

State the shape as: **components → their responsibilities → the contracts between them → where state lives →
what crosses a trust boundary.**

## Non-functional requirements

Pin numbers, not adjectives. If the spec gives none, choose defensible ones and log the assumption:
expected data volume and growth, concurrency, acceptable latency for the slowest common operation, offline
behaviour, startup time, binary/bundle size where it is user-visible, target OS/runtime versions, accessibility
and localization needs, and the backup/restore story for anything the user cannot recreate.

## ADRs

One decision per file, `docs/dev/adr/NNNN-<kebab-title>.md`:

```markdown
# NNNN. <Decision in a full sentence>

- **Status:** accepted | superseded by NNNN
- **Date:** YYYY-MM-DD

## Context
The forces: what the spec requires, what constrains us, what we do not know yet.

## Decision
What we will do, stated so someone can act on it.

## Alternatives considered
- <option> — rejected because <reason>.

## Consequences
What this buys, what it costs, what becomes harder, and what would make us revisit it.
```

Write an ADR for a choice that is expensive to reverse: the storage engine, the sync model, the auth model, the
process/threading model, the UI framework, the packaging/distribution channel, the cross-platform boundary,
the public API shape. Do not write one for a choice a later phase can change freely.

## Failure modes — design past the happy path

For every external dependency and every multi-step operation, name what happens on: timeout, retry, duplicate,
out-of-order delivery, partial completion, an unknown outcome (the call may or may not have landed), a version
mismatch, and a restart in the middle. Idempotency and reconciliation are design decisions, not implementation details.

For local-first and offline software the equivalents are: an interrupted write, a corrupt or half-written file, a
schema from an older version, two devices editing the same record, and a crash between two dependent writes.

## Risk register

`.autodev/RISKS.md`, one table, ordered by expected cost:

| # | Risk | Likelihood | Impact | Mitigation | Where it is handled |
|---|---|---|---|---|---|

Match control to risk: a mistake in a label and a mistake in a payment do not deserve the same scrutiny. High-risk
areas earn extra tests, explicit invariants, and a named phase in the roadmap. Low-risk areas earn speed.

## What to check before calling a design done

- Every acceptance criterion in the spec maps to a component that owns it.
- Authorization and data isolation are stated, not implied.
- Secrets: where they live, and how they stay out of the repo and the logs.
- Upgrade path: how existing user data survives the next release.
- Observability: what a developer looks at when a user says "it does not work".
