# Stack profiles

A profile is a starting sheet for one kind of project: the layout, the exact commands, the e2e driver, and the
traps that stack has. The orchestrator copies the selected one to `.autodev/PROFILE.md` at the start of a run;
the architect step then corrects it against the real repository and fills in every command it left open.

`.autodev/PROFILE.md` is what every later session reads. If a command in it is wrong, fix the file — it is the
project's record, not a template.

| Profile | For |
|---|---|
| `generic.md` | Anything not listed below, or a stack chosen at the architect step |
| `swift-macos.md` | Native macOS app in Swift (SwiftUI or AppKit) |
| `swift-ios.md` | Native iOS/iPadOS app in Swift |
| `rust-tui.md` | Terminal application in Rust (ratatui/crossterm) |
| `django-htmx.md` | Django with server-rendered templates and htmx |
| `django-react.md` | Django/DRF backend with a separate React frontend |
| `fastapi-react.md` | FastAPI backend with a separate React frontend |
| `python-textual.md` | Terminal application in Python (Textual) |

Choosing: pick by what the spec asks for. If the spec does not say, the developer answers it at intake; if that
question was never asked, the architect step decides and writes an ADR.

## The shape every profile fills in

| Key | Meaning |
|---|---|
| `install` | Bring a clean checkout to buildable |
| `build` | Compile / bundle |
| `run` | Start the product for a human |
| `test` | The whole unit+integration suite, non-interactive, from the repo root — this is autodev's `--test-cmd` |
| `lint` / `format` | Static checks and the formatter |
| `e2e up` / `e2e` / `e2e down` | Start the surfaces, run the end-to-end suite, stop them — autodev's `--e2e-up-cmd`, `--e2e-cmd`, `--e2e-down-cmd` |

Every command must be non-interactive and must work from the repository root on a clean machine.
