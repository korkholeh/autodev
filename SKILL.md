---
name: autodev
description: Launch a fully autonomous development run from a specification file — a technology-agnostic pipeline that designs the architecture, plans phases, then for every phase plans → implements → tests → reviews → drives end-to-end QA → writes documentation → commits, each step in a separate headless Claude session, auto-pausing near the usage limit. Only when the user explicitly runs /autodev.
argument-hint: <spec-file> [--profile <stack>] [--gh-user <login>] [--pr] [other autodev.py run flags]
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/autodev.py *) Bash(tmux *) Bash(git status *) Bash(git log *) Bash(git init *) Bash(git branch *) Read Write(.autodev/*) Edit
---

# /autodev — launcher

Arguments: `$ARGUMENTS` (first = spec file, the rest = extra flags for `autodev.py run`).

You are the **launcher**, not the developer. The orchestrator script does the work in separate sessions.
Never implement the spec yourself in this session.

## 1. Pre-flight (the only moment a human is present)

Run `python3 ${CLAUDE_SKILL_DIR}/scripts/autodev.py doctor --spec <spec-file>` and resolve issues with the user:

- **FAIL** lines must be fixed before launch (missing spec, git identity, Claude Code not found, a trial headless
  session that returned nothing usable, a missing toolchain for the detected stack profile).
- **`tool ...` lines** are the toolchain check: git and tmux, plus the compilers and interpreters the detected
  profile builds with. Each missing one prints the command that installs it on this platform — offer to run it,
  or hand the user the command. A missing **required** tool (FAIL) also stops `run` itself before the first
  session; a missing **recommended** one (WARN) only costs a phase some time. `run --skip-tool-check` starts
  anyway, for a toolchain this check cannot see on PATH.
- **Base branch.** The doctor prints what the run would use. A repository with **no commits** gets `main` before
  the first one, whatever `git init` called it — nothing to ask. In an **existing project**, ask before launching
  which branch the run is based on: the one checked out (the default), or a new one cut from it
  (`--base-branch <name>`). `git branch --list` shows what is there. Worth the question — it is the branch every
  phase pull request opens against, the branch the run comes back to, and the one `--merge-phases` would write to.
- **Existing run** in `.autodev/`: ask whether to resume (default) or start over (`--fresh`). If the doctor says
  the state was not started on this machine, it arrived with the repository — read `.autodev/state.json` with the
  user before offering `--adopt`, since it names the commands the orchestrator will run.
- **Usage API unavailable**: tell the user pauses will only trigger on limit events/errors; suggest `AUTODEV_OAUTH_TOKEN`.
- **Stack profile.** The doctor prints the detected one (`swift-macos`, `swift-ios`, `rust-tui`, `django-htmx`,
  `django-react`, `fastapi-react`, `generic`). For an empty repository, detection will say `generic` — confirm what is
  being built and pass `--profile <name>`. The profile only seeds `.autodev/PROFILE.md`; the architect step corrects
  it against the real repository.

### The intake interview

Read the spec, then follow `${CLAUDE_SKILL_DIR}/prompts/intake.md`: ask **at most 6 questions in one message**, only
about what the spec does not already answer, each with a recommended default. Write the answers to
`.autodev/INTAKE.md` and append them to the spec under `## Clarifications (pre-run)`. If the spec answers everything,
ask nothing and say so.

This is the last human input of the run. Everything unasked becomes a logged guess.

### Commands and GitHub identity

- If the doctor could not guess a test command and the stack is known, suggest `--test-cmd "<cmd>"`.
- If the end-to-end suite needs services running (a web stack usually does), pass `--e2e-up-cmd`, `--e2e-down-cmd`
  and optionally `--e2e-ready-url`. The up command runs once per e2e step and must be **idempotent** — starting an
  already-running surface has to succeed, not fail on a taken port — and it must **return** once the surfaces are up.
  A command that stays in the foreground only works together with `--e2e-ready-url`. Left empty, the architect and
  e2e steps work them out and write them down. `--e2e off` turns the end-to-end layer off entirely.
- **Commands the sessions propose are vetted** against a toolchain allowlist before the orchestrator runs them; a
  session that proposes something else is told why and corrects it once. If this project drives its suite through
  its own script, pass `--allow-cmd <binary>` (or just pass the command yourself, which is never checked).
- **A run with no test command stops at the architect step**, because otherwise every phase would report a passing
  suite without running anything. If the doctor could not guess a test command, agreeing on one here is worth a
  question.
- **Sessions have no web access and no MCP servers** unless asked for: `--web on` when the work needs to look
  things up (an unfamiliar API, a current version), `--mcp-config <file>` for a server this project needs.
- **A failing commit hook stops the run.** If the repository has hooks the user knows are broken, `--allow-no-verify`
  is the escape; otherwise fixing them before launch is the better answer.
- **A ceiling on the night** is worth offering: `--max-hours 8` (or `--max-sessions N`) stops the run
  instead of working through the next usage window. Without one the run goes until the spec is done.
- Never point the e2e commands at production or at real user data.
- **GitHub identity.** Commits/pushes use the account from `--gh-user <login>` (pass the same flag to `doctor`,
  together with `--pr` when the run will use it, so the base branch is checked too).
  If the user didn't pass it and the doctor lists several gh accounts while the repo has a GitHub remote,
  ask which account to use (or "local only"). A `FAIL` on push permission or a missing token must be fixed now
  (`gh auth login` for that account). Useful extras: `--pr` (a draft PR per phase, stacked, each based on the one below it, plus one for the
  whole run carrying the live PROGRESS.md, and one on top for the closing docs/handoff commits — `--pr single`
  opens only the run's own; the chain is registered as a GitHub stack when the `gh-stack` extension is
  installed — the doctor reports it), `--push end|never`,
  `--gh-repo owner/name` when there is no GitHub remote, `--git-email` to override the noreply address.
- **`--merge-phases` only if the user asks for it in so many words.** It merges each phase into the base branch
  overnight, with nobody having read the diff. Never offer it as a default or add it to be helpful; if the user
  does ask, say plainly which branch the run will be writing to.

## 2. Launch

Session name: `autodev-<repo-dir-name>`.

If `tmux` is available, start it detached (survives closing the terminal):

```
tmux new-session -d -s autodev-<repo> -c "$PWD" "python3 ${CLAUDE_SKILL_DIR}/scripts/autodev.py run --spec <spec-file> <flags>; exec $SHELL"
```

Then verify it started: `tmux ls` and, after ~20 s, `python3 ${CLAUDE_SKILL_DIR}/scripts/autodev.py status`.

If tmux is not available, do **not** background it from this session (it may be killed when Claude Code exits).
Print the command for the user to run in their own terminal instead:
`python3 ${CLAUDE_SKILL_DIR}/scripts/autodev.py run --spec <spec-file> <flags>`

## 3. Hand-off message (short)

- Watch: `python3 ${CLAUDE_SKILL_DIR}/scripts/autodev.py dash` (live dashboard; it offers to install what it needs) ·
  `tmux attach -t autodev-<repo>` (detach: Ctrl-b d) · `tail -f .autodev/autodev.log`
- Status: `python3 ${CLAUDE_SKILL_DIR}/scripts/autodev.py status`
- Morning, in this order: `.autodev/HANDOFF.md`, `.autodev/PROGRESS.md`, `.autodev/DECISIONS.md`,
  `docs/user/`, `git log --oneline` on the `autodev/…` branch (or, with `--pr`, the stack of draft PRs — one per phase)
- Stop gracefully after the current session: `touch .autodev/STOP` · Resume later: same `run` command
- On macOS: keep the Mac on power with the lid open (caffeinate is on automatically)

Then end your turn.
