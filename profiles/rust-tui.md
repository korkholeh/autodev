# Profile: terminal application in Rust

## Layout

```
Cargo.toml               workspace or single crate; binary + library split
src/lib.rs               state machine, domain logic, key handling — testable with no terminal
src/main.rs              terminal setup/teardown, event loop, CLI argument parsing
src/ui/                  ratatui render functions: state in, frame out, no I/O
tests/                   integration tests against the library
tests/e2e/               pty-driven specs against the built binary
docs/dev, docs/user
```

The split that makes this stack testable: **the app is a pure function from state and an input event to a new state,
plus a pure render from state to a frame.** Keep every terminal call in `main.rs` and the event loop.

## Commands

| Key | Command |
|---|---|
| install | `cargo fetch` |
| build | `cargo build --release` |
| run | `cargo run` |
| test | `cargo test` |
| lint | `cargo clippy --all-targets -- -D warnings` |
| format | `cargo fmt` (check with `cargo fmt --check`) |
| e2e up | `-` |
| e2e | `cargo test --test e2e -- --test-threads=1` |
| e2e down | `-` |
| screenshot | `vhs <tape>` (tape drives the keys, writes PNG/GIF), or dump the parsed pty screen to `.txt` |

## Testing layers

- **State tests** — feed a sequence of `KeyEvent`s into the state machine and assert the resulting state. Fast and
  where most cases belong.
- **Render tests** — render into `ratatui::backend::TestBackend` and assert the buffer: the text that appears, where
  it appears, and what is highlighted. This is the equivalent of a screenshot assertion, and it is deterministic.
- **End-to-end** — spawn the built binary under a pty (`portable-pty`, `expectrl`, or `rexpect`), send real
  keystrokes, and assert on the parsed screen. This is the only layer that proves terminal setup, raw mode, resize
  handling, and the exit path.

## End-to-end notes

- Fix the terminal size explicitly (for example 80×24) and set `TERM` to a known value; a suite that inherits the
  developer's terminal is not reproducible.
- Assert on the rendered *text* of the screen, not on raw escape sequences. Strip ANSI, then match.
- Wait for a screen to contain an expected string with a timeout. Never sleep a fixed interval.
- Always test the exit path: the terminal must be left out of raw mode and with the alternate screen restored, even
  after a panic. A TUI that corrupts the user's shell on crash is a `high` case.
- Cover: startup with no config, a resize mid-flow, Ctrl-C, a very narrow terminal, a non-UTF-8 filename, piped
  stdin/stdout (is the app supposed to work non-interactively?), and `--help` / `--version`.

## Documentation

`docs/user/` for a TUI is mostly the key map: every binding, every mode, and every destructive action with its
confirmation. Also state where config and data files live and what happens when they are missing.
`docs/dev/`: the state machine, the event loop, and how to add a screen.

## Pitfalls

- Blocking I/O in the event loop freezes the UI; long work goes on a thread or a task with a progress state.
- Panics must restore the terminal — install a panic hook that tears down before printing.
- Colour and unicode are not universal: check behaviour with a 16-colour terminal and with `NO_COLOR` set.

## Screenshots

- `vhs` is the capture worth having: the tape drives real keystrokes and writes a PNG (or a short GIF) at a size
  you fix in the tape.
- Without `vhs`, run the binary under a pty, parse the screen and write it as `.txt` with ANSI stripped — a text
  frame beats no frame, and it diffs well.
- Fix `TERM` and the terminal size, and let colours be whatever the product's defaults are.
- Wait for the expected string on screen before capturing; a fixed sleep photographs a redraw.
