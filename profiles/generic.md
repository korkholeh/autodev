# Profile: generic

Use when no shipped profile fits. The architect step must replace every `TODO` below with a real command before
phase 1 ends, and phase 1 must leave those commands working on a clean checkout.

## Layout

Follow the ecosystem's own convention rather than inventing one: source under the idiomatic directory, tests where
that language's runner looks for them, one dependency manifest with a committed lockfile, one formatter and one
linter configured in-repo.

## Commands

| Key | Command |
|---|---|
| install | TODO |
| build | TODO |
| run | TODO |
| test | TODO |
| lint | TODO |
| format | TODO |
| e2e up | TODO (or `-` when the suite needs nothing running) |
| e2e | TODO |
| e2e down | TODO |

## Testing layers

- **Unit** — pure logic, no I/O. Fast, the bulk of the suite.
- **Integration** — the real datastore/filesystem/process boundary, fixtures created and torn down by the suite.
- **End-to-end** — the built artefact, driven the way a user drives it. See `.autodev/guides/e2e-authoring.md`.

Pick the e2e driver from how the product is delivered: a browser driver for a web UI, the platform's UI-test
framework for a native app, a pty harness for a terminal app, a subprocess runner for a CLI, an HTTP client against
a started server for an API-only product. Whatever it is, write it down here.

## Documentation

`docs/dev/` for maintainers, `docs/user/` for users, `CLAUDE.md` as the root index. See the guides.

## Pitfalls

- A test command that only works from one directory, or only with an editor plugin, is not a test command.
- A suite that needs a service running must start it from `e2e up`, not from inside a test.
- Pin versions. An unpinned toolchain turns a green run into a red one with no diff.
