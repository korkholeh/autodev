# Intake — the only conversation with a human

Read by the `/autodev` launcher skill while the developer is still at the keyboard. Everything after this point runs
unattended, so a question skipped here becomes a guess logged in `DECISIONS.md` at 3am.

Ask **only what the spec does not already answer**, at most **6 questions in one message**, each with a recommended
default so the developer can reply "defaults" and go to bed. Write the answers to `.autodev/INTAKE.md`, and append a
`## Clarifications (pre-run)` section to the spec file itself.

## 1. Always resolve (ask only when the spec is silent)

**Target and delivery.** What is being built and how it reaches its user — a native macOS app, an iOS app, a terminal
program, a web app someone deploys, a library, a CLI. This picks the stack profile. If the spec names the stack, just
confirm the profile choice in one line instead of asking.

**Stack inside that target.** Language/framework where more than one is reasonable (SwiftUI vs AppKit; Django
templates + htmx vs Django + a React SPA; FastAPI vs Django for an API). Recommend one and say why in half a line.

**Data and persistence.** Where state lives and whether it must survive an upgrade: a local file or embedded database,
a server database, a cloud service, nothing at all.

**Identity and access.** Is there sign-in? Are there roles that see different things? Is there anything one user must
never see from another? "No auth" is a valid answer, but it must be an answer.

**Test and e2e commands.** The doctor guesses these; confirm or correct. For a project that does not exist yet, ask
what the developer expects to type — that becomes the contract phase 1 must satisfy.

**Scope boundary for tonight.** What must exist by morning versus what can wait. The roadmap orders phases from this.

## 2. Ask when the spec's domain implies them

- **Money, payments, or anything irreversible** — what must be idempotent, who approves, what reconciliation looks like.
- **External integrations** — which service, whether credentials exist locally, and what to do when it is unreachable.
  If credentials are missing, decide now: stub it, or let that phase report `blocked`.
- **Multi-user or multi-tenant data** — the isolation rule, stated once, plainly.
- **Existing codebase** — which conventions are binding, which parts must not be touched, whether a migration path
  from live data is required.
- **Distribution constraints** — code signing, notarization, app-store review, an offline install, a supported
  version floor.
- **Non-functional numbers that change the design** — expected data volume, concurrency, a latency the product is
  judged on, a binary size limit.
- **Localization and accessibility** — whether either is in scope for this run.

## 3. Never ask

- Anything the spec already states, or the repository already shows (framework in use, existing layout, lint config).
- Naming, file layout, library choices inside a settled stack, or any decision a later phase can reverse cheaply —
  those are the autonomous run's job, and it logs them in `DECISIONS.md`.
- More than one question about the same thing phrased differently.

## 4. Write `.autodev/INTAKE.md`

```markdown
# Intake — <project>

- **Date:** YYYY-MM-DD
- **Spec:** <path>
- **Profile:** <profile name>

## Answers
- **<question topic>:** <the developer's answer, verbatim in substance>

## Defaults the developer accepted
- <default>, because <the reason given when it was offered>

## Left open on purpose
- <what was not decided, and what the run should do about it>
```

The architect step reads this file and treats it as outranking its own preferences.
