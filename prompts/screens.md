Step: SCREENSHOTS — phase {{n}}/{{total}}: "{{title}}"

The phase is green and reviewed. Nobody has seen it. Your job is a small set of pictures of the product as it
stands after this phase, so the developer can tell in ten seconds what was built without running anything.

This is documentation, not testing. Do not fix bugs, do not change product code, do not touch the suites. If a
state you wanted to capture is broken, photograph it as it is and say so in the caption — that is the most
useful frame of the night.

Read first: `{{phase_dir}}/PLAN.md` (its deliverables are the shot list), `.autodev/PROFILE.md` (the
**Screenshots** section names this stack's capture command), and `{{phase_dir}}/SCREENS.md` from earlier phases
if one exists — the same view captured the same way twice tells a story; a different crop does not.

Guide for this step: `.autodev/guides/screenshot-capture.md`.

Phase goal: {{goal}}

Deliverables:
{{deliverables}}

The surfaces are already running — the orchestrator started them with `{{e2e_up_command}}`. Do not start or stop
them yourself.

## What to do

1. **Pick the shot list before capturing**: 3–6 frames, one per user-visible deliverable of this phase. A frame
   earns its place by showing a state a user reaches, not a screen that exists (empty state, the main flow's
   result, one error or edge state, anything this phase changed in an earlier screen). Prefer the states the
   acceptance criteria talk about.
2. **Set the stage**: seed the data the guide asks for (readable, boring, no real names or tokens), fix the
   window or terminal size, and prefer the same dimensions as previous phases.
3. **Capture** with the command from `.autodev/PROFILE.md` into `{{phase_dir}}/screenshots/`, named
   `NN-<slug>.<ext>` (`01-empty-state.png`). PNG for a GUI or a browser, SVG for a TUI, `.txt` for a CLI whose
   output is text. Nothing above 1 MB per file; scale down rather than crop information away.
4. **Verify every file**: it exists, it is non-empty, and it shows what you say it shows. A frame captured before
   the view finished rendering is worse than no frame — check the file, then keep or retake it.
5. **Write `{{phase_dir}}/SCREENS.md`**: one `##` per frame, in the order a user meets them, each with the
   embedded image (`![caption](screenshots/01-empty-state.png)`), one line of caption saying what is on screen,
   and one line saying which deliverable or acceptance criterion it evidences. End with a `## Not captured`
   section for anything on the shot list you could not photograph, and why.

If this phase has no user-visible surface at all (a migration, a build change), capture nothing, write a
one-line `SCREENS.md` saying so, and return `skipped` — do not pad the gallery with a terminal running tests.

If the capture tool is missing or the surface cannot be reached, return `blocked` with the exact command and its
error in the summary. Do not install anything to get around it.

Do not commit.

Structured output: status done|partial|skipped|blocked, summary (what the frames show, anything missed),
screenshots = one entry per captured file with its path relative to the repository root and its caption.
