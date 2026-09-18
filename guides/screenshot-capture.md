# Capturing screenshots of the product

A phase gallery has one reader: the developer who was asleep. Four frames they can scan in ten seconds beat
twenty they scroll past. Every frame answers "what can a user do now that they could not before".

## Choosing the frames

- One frame per user-visible deliverable, 3–6 per phase. If the phase added one screen, one or two frames.
- Photograph **states**, not screens: the empty state before any data, the main flow's result, one error or
  limit state, and anything this phase changed in a view an earlier phase already captured.
- Re-capture a view from an earlier phase when it changed — same size, same data, same crop. Two comparable
  frames show progress; two different crops show nothing.
- Skip what a picture cannot carry: performance, background jobs, migrations, refactors. `skipped` is a valid
  outcome and costs the reader nothing.

## Staging

- **Seed readable, boring data.** "Invoice 1042 — Acme Ltd — €120.00" reads instantly; `test_user_8f3a` does
  not. Never capture real names, real email addresses, tokens, keys, or anything from a developer's own
  account.
- **Fix the size** and keep it for the whole run: 1280×800 for a desktop browser, 390×844 for a mobile
  viewport, 100×30 for a terminal. A gallery of different sizes cannot be compared.
- **Hide the noise**: no dev toolbars, no debug banner, no notification popups, no clock in the frame when you
  can help it — a moving pixel makes every future diff noisy.
- **Wait for the view, not for the clock.** Capture after the state you want is on screen (an element is
  present, a request settled), never after a fixed sleep. Half a spinner is a wasted frame.
- Light theme unless the product's default is dark; capture both only when the phase is about theming.

## Capturing

The command is in `.autodev/PROFILE.md` under **Screenshots** — it is the one this stack can actually run
headlessly. Write into `<phase_dir>/screenshots/`, named `NN-<slug>.<ext>` in the order a user meets them.

| Surface | Format | Notes |
|---|---|---|
| Browser | PNG | Full page only when the page is short; otherwise the viewport |
| Native GUI | PNG | The app window, not the whole desktop |
| TUI | SVG | Text stays selectable and the diff stays readable |
| CLI | `.txt` | The session transcript, ANSI stripped |

Keep each file under 1 MB — these are committed with the phase. Scale a retina capture down (2× is twice the
bytes for nothing); never crop information out to save size. No video, no multi-megabyte GIFs.

## Verifying

A capture command that exits 0 proves a file was written, not that it shows anything. For each file: check it
exists and is non-empty, then look at it. A blank white PNG, a login screen where the dashboard should be, or a
terminal caught mid-redraw all exit 0.

## Writing `SCREENS.md`

```markdown
# Phase 03 — Editor · screenshots

## 01 · Empty state
![The editor with no file open](screenshots/01-empty-state.png)
No document open: the sidebar is empty and the editor shows the "Open a file" hint.
Evidences: deliverable "editor shell with an empty state".

## 02 · A file open with unsaved changes
![…](screenshots/02-unsaved.png)
…

## Not captured
- Autosave conflict dialog — needs two windows against one file; deferred to phase 5.
```

Caption what is **on screen**, in the present tense, one line. The second line names the deliverable or
acceptance criterion the frame evidences. A frame nobody can tie to the plan does not belong in the gallery.

If the state you captured is wrong (a layout bug, a truncated label), keep the frame and say so in the caption.
Fixing it is the next phase's work, or a review finding — it is not this step's.
