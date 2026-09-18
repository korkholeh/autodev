# Profile: terminal application in Python with Textual

## Layout

```
pyproject.toml           project metadata, dependencies, the console-script entry point
src/<pkg>/app.py         the App subclass: bindings, screen stack, composition
src/<pkg>/screens/       one module per screen
src/<pkg>/widgets/       custom widgets — compose + render, no I/O
src/<pkg>/domain/        state, rules, parsing, persistence — importable with no terminal
src/<pkg>/*.tcss         Textual CSS, shipped as package data
tests/                   pytest; domain tests plus Pilot-driven app tests
tests/__snapshots__/     SVG snapshots from pytest-textual-snapshot
e2e/                     pty-driven specs against the installed console script
docs/dev, docs/user
```

The split that makes this stack testable: **the domain layer knows nothing about Textual.** Widgets and screens
read state and emit messages; everything that can be decided without a terminal is decided in `domain/` and
tested there. `app.py` wires them together and owns nothing else.

## Commands

| Key | Command |
|---|---|
| install | `uv sync` (or `pip install -e ".[dev]"`) |
| build | `uv build` (a TUI has no bundle step; this proves the package is installable) |
| run | `uv run <console-script>` (during development: `textual run --dev src/<pkg>/app.py`) |
| test | `pytest -q` |
| lint | `ruff check src tests && mypy src` |
| format | `ruff format src tests` (check with `ruff format --check`) |
| e2e up | `-` |
| e2e | `pytest e2e -q` |
| e2e down | `-` |
| screenshot | `app.save_screenshot(<path>.svg)` from a Pilot script, or `textual run --screenshot 3 <app>` |

## Testing layers

- **Domain tests** — plain pytest against `domain/`. Fast, and where most cases belong. If a rule can only be
  reached by pressing a key, it is in the wrong layer.
- **Pilot tests** — `async with app.run_test() as pilot:` drives the real app headlessly: `await pilot.press("ctrl+s")`,
  `await pilot.click("#save")`, then assert on `app.query_one(...)` state or on `app.screen`. This is the main
  layer for bindings, focus order, screen transitions and message handling.
- **Snapshot tests** — the `snap_compare` fixture of `pytest-textual-snapshot` renders the app to SVG and diffs it
  against a committed file. This is a real screenshot assertion and it is deterministic. Use it for layout, not for
  logic: a snapshot tells you *that* something changed, never *why*.
- **End-to-end** — spawn the installed console script under a pty (`pexpect` or `pyte` for screen parsing), send
  real keystrokes, assert on the parsed screen. This is the only layer that proves the entry point, argument
  parsing, terminal setup and the exit path.

## Textual specifics

- `await pilot.pause()` after anything asynchronous, before asserting. Most flaky Textual tests are an assertion
  that ran before the message queue drained; a `sleep` in its place is the same bug with a delay.
- Never do blocking work in a message handler — it freezes the UI. Use `@work(thread=True)` for blocking I/O and
  `@work` for async work, and post a message back with the result. Long work needs a visible progress state.
- Reactive attributes drive rendering: change state through them (and `watch_*` methods), not by mutating a widget
  and calling refresh by hand.
- Widget ids and CSS classes are the test API. Give every widget a test needs a stable `id`; a test that selects by
  position breaks on the next layout change.
- Snapshots are tied to the Textual version. Pin it, and treat a mass snapshot diff after an upgrade as a review
  item, not as something to re-record blind.
- `.tcss` files must be declared as package data, or the installed app starts unstyled while the dev run looks fine.
  The e2e layer, running the installed script, is what catches this.

## End-to-end notes

- Fix the terminal size explicitly (for example 80×24) and set `TERM` to a known value; a suite that inherits the
  developer's terminal is not reproducible.
- Assert on the rendered *text* of the screen, not on raw escape sequences. Strip ANSI (or parse with `pyte`), then
  match.
- Wait for a screen to contain an expected string with a timeout. Never sleep a fixed interval.
- Always test the exit path: the terminal must be left out of raw mode with the alternate screen restored, even
  after an exception. A TUI that corrupts the user's shell on crash is a `high` case.
- Cover: startup with no config file, a resize mid-flow, Ctrl-C and the app's own quit binding, a very narrow
  terminal, a non-UTF-8 filename, piped stdin/stdout (is the app supposed to work non-interactively?), and
  `--help` / `--version`.

## Documentation

`docs/user/` for a TUI is mostly the key map: every binding, every mode, and every destructive action with its
confirmation. Also state where config and data files live, what happens when they are missing, and which
environment variables (`NO_COLOR`, `TERM`, `TEXTUAL_*`) change behaviour.
`docs/dev/`: the screen and message flow, where the domain boundary runs, and how to add a screen or a widget —
including the snapshot workflow (`pytest --snapshot-update` and why a diff is reviewed, not accepted).

## Pitfalls

- An `async def` handler that awaits a slow call blocks the event loop just as a sync one does; only a worker gets
  the work off it.
- `App.exit()` inside a handler does not stop the rest of that handler from running — return straight after it.
- Colour and unicode are not universal: check with a 16-colour terminal, with `NO_COLOR` set, and over SSH.
- A modal screen that never dismisses on error leaves the app stuck with no way back; every `push_screen` needs its
  matching dismiss path tested.

## Screenshots

- `App.save_screenshot("<name>.svg")` from a Pilot script is the capture to use: it renders the real widget tree, the
  text stays selectable and the diff between phases stays readable.
- Fix the size in the Pilot run (`app.run_test(size=(100, 30))`) and keep it for the whole run.
- `await pilot.pause()` before saving — the same race that breaks Pilot assertions produces a half-drawn frame.
- The snapshots in `tests/__snapshots__/` are assertions, not the gallery; capture the phase's frames separately
  so a snapshot update never rewrites what the developer is looking at.
