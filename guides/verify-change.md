# Verify change

Match the checks to what actually changed. Do not run everything for a one-line edit; do not skip verification
because a change "looks trivial". Commands for this stack are in `.autodev/PROFILE.md`.

## Pick the scope

Look at `git status` / `git diff --name-only`, then choose the narrowest sufficient check:

| What changed | Check |
|---|---|
| One module's logic | That module's unit tests, plus the linter on the changed files |
| A public contract (API route, exported type, CLI flag, protocol, schema) | Contract/integration tests on both sides of the boundary; regenerate any schema/client the project checks in |
| Data model / migration | Domain tests, the migration applied to a scratch database and rolled back if the project supports it, plus the project's "no missing migration" check |
| UI surface | The e2e case that covers it (`.autodev/PROFILE.md` names the runner); a unit test alone does not prove a screen renders |
| Background job / async chain | A test of the job's effect, plus retry and idempotency behaviour |
| Build config, dependency, toolchain | A clean build from the declared commands |
| Docs or comments only | No tests. Say so. |

Before finishing a step, the full suite named in `.autodev/PROFILE.md` must pass at least once.

## Report honestly

- Never state that a command passed unless you ran it and saw it pass. Quote the failing output when it fails.
- Separate failures your change caused from failures already present on the base commit. Check the base if unsure.
- Name what you could **not** verify, and why. An unverifiable claim reported as verified is worse than a gap.
