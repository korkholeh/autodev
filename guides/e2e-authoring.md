# End-to-end specs

An e2e spec drives the real product the way a user does, and asserts what the user can observe. It is the only layer
that sees the seams the unit suite cannot: the wiring between a UI and its backend, the packaging, the startup path,
the real database, the real router, the real terminal.

The driver for this project is named in `.autodev/PROFILE.md` (browser, XCUITest, a pty harness, a CLI runner).
Everything below is independent of which one it is.

## The tree

```
e2e/
  plans/<feature>.plan.yaml   the cases and the oracle, written first (see qa-oracles.md)
  <surface>/                  specs grouped by what they drive, not by which module owns the feature
  support/                    the shared library: config, fixtures, personas, helpers, reporting
  README.md                   how to run it, what a surface is, how to add a case
  RESULTS.md                  generated after every run, gitignored
  artifacts/                  screenshots, traces, recordings, logs — gitignored
```

## Surfaces

A **surface** is one runnable thing a spec can drive: the app binary, the web UI, the API, the CLI. A spec asks for a
surface by name and gets an address or a handle from it — it never hardcodes a port, a path, or a hostname.
Surface definitions live in one committed config (`e2e/surfaces.toml` or the project's equivalent) with a
per-developer override file that is gitignored.

Rules that stop the suite from lying to you:

- **The suite attaches; the orchestrator starts.** A test harness that starts servers grabs ports, races an instance
  the developer already has open, and leaves orphan processes on Ctrl-C. If a required surface is not up, fail with
  the exact command that starts it. The autodev orchestrator runs that command itself before the suite.
- **A missing *optional* surface skips its specs; a missing *required* surface fails the run.** A run that silently
  skips everything looks exactly like a green one.
- **One address per surface, derived where possible** from the app's own configuration rather than duplicated in the
  test config. Two components reachable under two hostnames that are not interchangeable is a real bug class.

## Data and personas

- Seed the data the suite needs through the product's own mechanism (a seed command, a fixture file, a factory the
  app ships), not by writing into storage behind the app's back.
- Personas are named roles with stable identities — `USER_ADMIN`, `USER_MEMBER`, `USER_NEW`. Reference them by name;
  never paste a credential into a spec. Test credentials come from the seed and the local config.
- Make each spec independent: it creates or resets what it needs. A suite whose tests must run in one order will
  eventually run in another.
- Never point an e2e run at production or at real user data.

## Writing a case

1. Open with the tag and a one-line description of intended behaviour:
   `[qa:<feature>:<case-id>] The password changes and the card says so.`
2. Drive the product through the steps a person would take. No back doors: if the flow requires signing in, sign in.
   (Caching one real sign-in per persona per run and reusing the resulting session is fine — it is the same journey,
   performed once.)
3. Assert on what the user can observe: the rendered text, the visible control, the status, the file that lands, the
   exit code, the message on stderr. Never on internal state the user cannot reach.
4. **Follow the chain to its observable end.** Read the code to discover that an upload triggers a job that produces a
   total; then assert the total that appears, waiting on that signal — not on a fixed sleep, and not on the queue.
   If a chain has no observable end state, say so in `findings` instead of faking a backend assertion.
5. Scope assertions to what is actually offered: visible, enabled, focusable. Many labels exist in a UI tree while
   hidden, and "present in the DOM" is not "offered to this user".
6. Prefer semantic locators — role, accessible name, label, test id — over structural paths and CSS chains that break
   on the next layout change.
7. Keep one case per test function. A test that asserts five unrelated things reports one failure and hides four.

## When a spec fails

A red e2e row is a product bug until proven otherwise. Diagnose with `systematic-debugging.md`, fix the **product**,
and leave the assertion pinned to the intended outcome. Change a spec only when the spec itself contradicts the
oracle, and say so in `.autodev/DECISIONS.md`.

Flake is a defect too: a timing-dependent assertion, a fixed sleep, or a dependency on test order. Fix the wait, do
not add a retry.

## The report

Every run writes `e2e/RESULTS.md`: the command, when it ran, and one row per test — test name, the plan case and its
priority, a one-line description, the group, the result, and links to the artifacts. It is generated and gitignored;
the plans and the specs remain the sources of truth. A run replaces only the rows for the tests it ran, so the
timestamp column shows how old everything else is.

Capture an artifact on failure at minimum — a screenshot, a trace, the terminal buffer, the app log. A failure with
no artifact costs the next session a full re-run to see anything.
