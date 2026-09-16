# autodev — autonomous development from a spec

**An agent harness, shipped as a Claude Code skill.** The skill is the entry point (`/autodev`); the work is done
by the orchestrator in `scripts/autodev.py`, which runs every step as a separate headless session.

A technology-neutral pipeline: architecture → phases → for each phase plan → implementation → tests → review →
end-to-end (e2e) QA → documentation → commit. Every step is a separate headless Claude Code session with a clean
context. Works for native Swift apps (macOS, iOS), Rust TUIs, Django+React, FastAPI+React, Django+htmx, and any
other stack (the `generic` profile).

**New here?** [`GUIDE.md`](GUIDE.md) explains how a run works, what kind of project it suits, how to write a spec it
can build from, and how to check the result in the morning. This page is the reference: every flag, every rule.

## Installation

```bash
unzip autodev.zip -d ~/.claude/skills/      # → ~/.claude/skills/autodev/SKILL.md
brew install tmux                            # so the process survives closing the terminal
```

`dash` and `report` want one package each — `textual` and `openpyxl`. Neither is needed to install
autodev or to run it: the first time you use one of those two commands it offers to set them up
(see [The tooling venv](#the-tooling-venv)).

Requirements: Claude Code ≥ 2.1.259 (for `--permission-prompts none`), Python 3.9+, git with `user.email`
configured, and your stack's toolchain (Xcode, cargo, uv/npm, etc.). Both `doctor` and `run` check it — see
[Toolchain](#toolchain) below.

## Running

In Claude Code, at the project root:

```
/autodev docs/spec.md
/autodev docs/spec.md --profile swift-macos
/autodev docs/spec.md --gh-user oleh-work --pr
/autodev docs/spec.md --e2e-up-cmd 'make dev-up' --e2e-ready-url http://localhost:8000/health
```

The skill runs a pre-flight check (`doctor`) — which includes one trial headless session, so an expired login, a
hook that blocks headless mode or a build without structured output is found now and not at 3am — conducts an
interview (up to 6 questions — stack, data, access, scope limit for the night), writes the answers to
`.autodev/INTAKE.md`, and starts the orchestrator in tmux. `doctor --no-smoke` skips the trial session.
Or directly from the terminal:

```bash
python3 ~/.claude/skills/autodev/scripts/autodev.py run --spec docs/spec.md
```

## The loop

```
architect ─► roadmap ─► for each phase:
   plan ─► implement (×N, while [ ] tasks remain) ─► tests ─┬─► review ─┬─► e2e ─┬─► docs ─► commit + tag
                                                            │          │        └─► e2e_fix (×≤3) ─► docs
                                                            │          └─► review_fix ─► tests ─┬─► review (round 2)
                                                            │                                   └─► audit (last round)
                                                            └─► test_fix (≤3) ─► tests
                                                                                        ─► finalize (docs + HANDOFF)
```

- **architect** — before any code: `ARCHITECTURE.md`, ADRs in `docs/dev/adr/`, a risk register `RISKS.md`,
  the exact stack commands in `.autodev/PROFILE.md`.
- **e2e** — only for phases marked `user_facing` in the roadmap. The up command must return once the surfaces
  are up (a command that stays in the foreground needs `--e2e-ready-url`). First a plan with an oracle
  (`e2e/plans/<feature>.plan.yaml`), then the specs, then a run that fixes **the product**, not the tests.
  Services are brought up by the script (`--e2e-up-cmd`), not by the agent.
- **audit** — the fixes of the *last* review round have no round left to check them, so a read-only session sees
  exactly that diff (`git diff` against the tree recorded before the fix session) with the review it answered, and
  says whether every blocker and major is really fixed. If it finds one that is not, the phase gets one more fix
  pass and then lands with a warning. `--no-audit-fixes` skips it.
- **docs** — `CLAUDE.md`, `docs/dev/` (for developers) and `docs/user/` (for users) + `CHANGELOG.md`.
- **finalize** — reconciles all documentation with what was actually built, and writes `.autodev/HANDOFF.md` —
  the morning briefing.

Each step names the step that follows it, and a phase sent through the suite remembers where it was going. So
fixing a failing end-to-end case leads on to the documentation rather than back into another review round, and a
phase that has used up its review rounds still gets its end-to-end QA and its docs.

Tests, e2e, commits, and state are handled by the script (no usage limit spent).

## What lives where

| File | Purpose |
|---|---|
| `.autodev/HANDOFF.md` | morning briefing: what was done, what was verified, what is left, what a human must decide |
| `.autodev/PROGRESS.md` | control document: status (and why it stopped), phases with their warnings, run warnings, timeline, usage |
| `.autodev/REPORT.xlsx` | the run's numbers: time, tokens per model, cost per step and per phase, every session, a budget model — refreshed after each phase (gitignored, rebuild any time with `report`) |
| `.autodev/ARCHITECTURE.md`, `RISKS.md` | design and risk register (architect step) |
| `.autodev/ROADMAP.md` | phases with goal / deliverables / acceptance criteria / user_facing |
| `.autodev/DECISIONS.md` | every decision the agents made on a human's behalf |
| `.autodev/INTAKE.md` | the developer's answers before the start |
| `.autodev/PROFILE.md` | stack: layout, exact commands, e2e driver, common pitfalls |
| `.autodev/guides/` | working rules read by the sessions (gitignored, copied from the skill) |
| `.autodev/phases/NN-*/` | `PLAN.md`, `REVIEW-rN.md`, `TEST_OUTPUT.txt`, `E2E_OUTPUT.txt` |
| `docs/dev/`, `docs/user/` | project documentation (for developers and for users) |
| `e2e/` | plans with oracles, specs, `RESULTS.md` |

## Stack profiles

`--profile <name>`, auto-detected by default:
`swift-macos`, `swift-ios`, `rust-tui`, `django-htmx`, `django-react`, `fastapi-react`, `generic`.

A profile is a starting sheet: layout, commands (install/build/run/test/lint/e2e), the e2e driver, common
pitfalls. The architect step corrects it against the real repository and writes it to `.autodev/PROFILE.md` —
from then on every session reads that file.

## Toolchain

A run is stopped by a missing compiler before it starts, not at 02:00 by a session that then works around it —
and works around it in writing, as a `[~]` task in `PLAN.md` that reads in the morning like a phase that was
built. `doctor` and the first seconds of `run` check the same list: git and tmux, plus what the chosen profile
compiles and tests with.

| Profile | Required | Recommended |
|---|---|---|
| all | `git` | `tmux` (the run survives the terminal closing) |
| `swift-macos` | `swift`, `xcodebuild` | |
| `swift-ios` | `swift`, `xcodebuild`, `xcrun simctl` | |
| `rust-tui` | `cargo`, `rustc` | `rustfmt`, `clippy` |
| `django-htmx` | `python3` | `uv`/`pip`, `ruff`, a browser e2e driver (`npx`) |
| `django-react`, `fastapi-react` | `python3`, `node`, `npm` | `uv`/`pip`, `ruff`, a browser e2e driver (`npx`) |
| `generic` | — | the architect step decides the stack; check it by hand |

Each missing tool is reported with the command that installs it on this platform (`brew install tmux`,
`curl … sh.rustup.rs | sh`, `sudo xcode-select -s /Applications/Xcode.app`, …). A **required** tool that is
missing fails `doctor` and stops `run`; a **recommended** one is a warning in both. Presence on `PATH` is not
always enough: `/usr/bin/xcodebuild` ships with the command line tools and errors until a full Xcode is
selected, so it is asked for its version rather than merely located.

`--skip-tool-check` starts the run anyway — for a toolchain that lives somewhere this check cannot see. The run
then records the gap as a run warning in `PROGRESS.md`.

## Flags

| Flag | What it does |
|---|---|
| `--profile NAME` | stack profile (auto-detection by default) |
| `--skip-tool-check` | start even when a compiler or interpreter this profile needs is not on `PATH` |
| `--test-cmd CMD` | full test-suite command (otherwise the architect picks it) |
| `--e2e auto\|off` | end-to-end QA on user-facing phases (`auto` by default) |
| `--e2e-cmd`, `--e2e-up-cmd`, `--e2e-down-cmd`, `--e2e-ready-url` | e2e suite and service lifecycle (the up command must be idempotent and must return) |
| `--allow-cmd BINARY` | also accept commands starting with `BINARY` when a session proposes one (repeatable) |
| `--web on\|off` | let the sessions use WebFetch/WebSearch (`off` by default) |
| `--mcp-config FILE` | MCP servers for the sessions, a file or a JSON string (repeatable) |
| `--inherit-mcp` | also give the sessions the MCP servers configured for you |
| `--allow-no-verify` | commit past a failing git hook instead of stopping |
| `--max-file-mb MB` | hold a staged file larger than this out of the commit (5 by default, 0 = no limit) |
| `--adopt` | resume run state in `.autodev/` that this machine did not create |
| `--no-docs`, `--no-finalize` | disable the documentation step / the final session |
| `--no-audit-fixes` | skip the read-only check of the last review round's fixes |
| `--max-context-tokens N` | hand the implementation to a fresh session once a turn reads more than N tokens of context (200000 by default, 0 = never) |
| `--model-plan\|impl\|review\|qa` | models per step (opus / sonnet / opus / sonnet) |
| `--max-test-fix`, `--max-e2e-fix`, `--max-review-rounds`, `--max-impl-runs` | loop limits |
| `--max-hours H`, `--max-sessions N` | ceiling on one run — it stops and tells you how to continue (no ceiling by default) |
| `--base-branch NAME` | the branch the run is based on: checked out if it exists, cut from the current one if it does not. Default: the branch checked out — and `main` in a repository with no commits |
| `--gh-user LOGIN` | token via `gh auth token --user LOGIN`; the active gh account is **not switched** |
| `--push phase\|end\|never` | when to push the `autodev/…` branch (with `--gh-user`, after every phase by default) |
| `--pr` | a draft PR per phase, stacked, plus one for the whole run (`--pr single` for only the run's). See [Stacked pull requests](#stacked-pull-requests) |
| `--merge-phases` | merge each phase's PR into the base as the phase lands, oldest first. Off by default — it writes to the base branch unattended |
| `--gh-repo owner/name` | repo, if the remote is not GitHub or there is none (`--remote` — a different remote name) |
| `--git-name`, `--git-email` | override the author; by default the name from the profile + `ID+login@users.noreply.github.com` |
| `--gh-host` | GitHub Enterprise (then `--git-email` is required) |
| `--lang` | language of the documents in `.autodev/` and `docs/` (code and comments are always English) |

## GitHub: committing and pushing as a specific account

```bash
gh auth login                  # once per account; gh keeps them all
autodev.py doctor --spec docs/spec.md --gh-user oleh-work    # checks the token, identity, push permission
autodev.py run    --spec docs/spec.md --gh-user oleh-work --pr
```

The author and committer are set via `GIT_AUTHOR_*`/`GIT_COMMITTER_*` for every commit of the run; the push goes
to `https://<host>/<repo>.git` with a one-shot credential helper that reads the token from the push process's
environment (not from argv, not from disk, not from the global config), so it works with SSH remotes too. The
token is never passed into Claude sessions and never written to `.autodev/`. The push runs with hooks off
(`--no-verify` and an empty `core.hooksPath`): a `pre-push` hook is a file in the repository that a session can
write, and it would run with the token in its environment. The suite has already passed before the commit, so
there is nothing such a hook could usefully add. If there is no token for the account,
or it belongs to a different login, the run fails immediately, before the first commit. If there is no push
permission, commits stay local and push/PR are disabled with a warning. A push failure does not stop the run —
the next attempt happens after the next phase.

### Stacked pull requests

A night's work in one pull request is not reviewable, so `--pr` opens one per phase instead — each based on the
phase below it, and registered with GitHub as a real [stacked pull
request](https://github.blog/changelog/2026-07-30-stacked-pull-requests-are-now-in-public-preview/):

```
main
 ← #1  autodev 01/07: Skeleton & terminal loop     phase 1 + the run's setup commits
    ← #2  autodev 02/07: Config & preflight        1 commit
       ← #3  autodev 03/07: Map rendering          1 commit
          ← #4  autodev: documentation, changelog and handoff

main
 ← #5  autodev: mosslight            the whole run, body = PROGRESS.md + the map above
```

Nothing is rebased and no branch is created locally. The run's history is already linear — one commit per phase —
so a phase branch is just that phase's commit pushed under its own name, once, when the phase finishes. Its body
is written from what the phase left behind: the last review verdict and the phase's warnings first, then its
deliverables and acceptance criteria folded away. It never needs rewriting afterwards, because the commit cannot
change.

Two ends of the run are not phases. The snapshot, architecture and roadmap commits are made before phase 1, so
they arrive inside the first phase's pull request; the documentation, changelog and handoff are committed after
the last phase, so they get one of their own on top of the stack. Merge the stack bottom-up and nothing is left
behind.

Chaining the bases is what makes the stack reviewable; registering it is what makes GitHub *show* it as one — a
stack map on every pull request, navigation between them, and an atomic merge. autodev creates the branches and
the pull requests itself and then hands the chain to `gh stack link`, the entry point GitHub documents for
branches managed outside its own extension. It is idempotent, so the whole chain is re-submitted each time it
grows. That needs the extension:

```
gh extension install github/gh-stack
```

Without it nothing breaks: the pull requests are still chained and still merge bottom-up, GitHub simply does not
know they are one stack. The run warns once and carries on, and `doctor --pr` says so before launch.

The run's own pull request stays as the umbrella: it carries the live `PROGRESS.md` and the map of the chain,
marking what has already landed, and it is the one to merge if the whole night is taken as a unit.

Read them in order and stop wherever the work stops being worth reading. A phase that changed nothing gets no
pull request, and the phase after it stacks on the last one that exists. `--pr single` opens only the run's own
pull request, as earlier versions did.

**Merging.** autodev does not merge anything by default — it pushes and opens drafts, and the decision is yours.
To merge by hand, take the bottom one out of draft and merge it; GitHub retargets the rest of the stack onto the
base as each one lands:

```
gh pr ready 1  && gh pr merge 1 --merge      # --merge, not --squash/--rebase: see below
```

`--merge-phases` hands that decision to the run instead: everything finished is merged into the base as each
phase lands, oldest first, the closing one last. It is off by default because it writes to the base branch
unattended, with nobody having read the diff.

With the stack registered, that is one `gh stack merge` — GitHub merges every member up to the newest in a single
all-or-nothing operation and keeps the bases in order itself. Without the extension autodev falls back to merging
them one at a time, naming the base explicitly each time: merging a pull request is supposed to retarget the ones
stacked on it, but that is GitHub's bookkeeping racing the next merge, and a base that has not caught up merges a
phase into the phase below it rather than failing. Either way a refusal — branch protection, a required check —
stops there rather than skipping ahead, is logged, and is retried after the next phase; the run keeps building.

Merges are always real merge commits: squash and rebase rewrite the commits that every pull request above this
one is based on, which would turn the rest of the stack into conflicts against history that no longer exists.

## Control

- status: `autodev.py status` · live dashboard: `autodev.py dash` · log: `tail -f .autodev/autodev.log` ·
  e2e services: `.autodev/logs/e2e-surfaces.log`
- stop after the current session: `touch .autodev/STOP` · immediately: Ctrl-C (the session will be resumed on the
  next `run`; a second Ctrl-C kills the session's whole process group, so the tests and dev servers it started go
  with it). The resume handle is written to `state.json` as soon as a session names itself, so even a power cut
  costs the current session, not the step.
- continue: the same `run` · start over: `run --fresh` (the previous `.autodev/` is archived next to it, and
  `INTAKE.md` — the answers from the pre-flight interview — is carried over into the new run)
- the spec belongs to the run: a `--spec` that differs from the one being resumed is reported and ignored;
  `--fresh` is how you change it
- the run needs a branch to start from, so a detached HEAD stops it before the first session (`doctor` says so too)
- **a repository with no commits is put on `main`** before the first one, whatever `git init` called it: the base
  branch is what every phase pull request opens against and what a remote adopts as its default on the first push,
  so it is not left to `init.defaultBranch`. `--base-branch NAME` picks another name.
- **in an existing project the branch checked out is the base**, and `--base-branch NAME` says otherwise: an
  existing branch is checked out (uncommitted changes that are not the run's stop it, they are not carried across),
  a name that does not exist yet is cut from the current branch. The launcher asks before it starts; the flag only
  applies to a new run, since a resumed one already has its branches.
- a resumed run puts itself back on its own branch first: if you left the repository on another branch (or on a
  detached HEAD) it checks the run's branch out again, and if there are uncommitted changes that are not the
  run's, it stops and leaves them alone

## The dashboard

```bash
python3 ~/.claude/skills/autodev/scripts/autodev.py dash          # q quits
python3 ~/.claude/skills/autodev/scripts/autodev.py dash --light  # `t` toggles the theme either way
```

A terminal window onto the run in this directory, refreshed every second, reading the same `state.json` the
spreadsheet is built from — so it costs no session and nothing it shows can be stale in a way `status` would not be.

| Where | What |
|---|---|
| top left | **Stop** writes `.autodev/STOP` (the run ends after the session it is in) · **Resume** starts the orchestrator again, in tmux when there is tmux · **Log** opens `.autodev/autodev.log`, tailed |
| top right | run status, whether a process is actually alive, the current step and phase, the branch, and `resumes ≈` while a usage limit is being waited out |
| left | every session the run has started, newest first, the live one on top with its clock running: step, model, time, cost |
| centre | the phases, each with its own progress bar — the fix steps do not advance it, so a phase that fails its suite three times keeps reading as "at the tests" — plus sessions, time, cost and commit per phase |
| bottom centre | cost and tokens per model, tokens by kind, the night split into working / paused on the limit / nobody running, the total cost and what a phase has averaged |
| bottom | overall progress across the phases, and an estimate of the time left taken from what the finished phases actually took |

Keys: `s` stop · `r` resume (it asks first — resuming spends usage and writes commits) · `l` log · `a` agents
· `t` theme · `q` quit. The sidebar hides itself below 96 columns; `a` brings it back.

It needs `textual`; the first run offers to install it. Declined, the command says what to run and exits —
`status` and `REPORT.xlsx` answer the same questions, less prettily, and a run never depends on the dashboard
being installable.

### The tooling venv

Everything a run does is stdlib, deliberately: the orchestrator has to start at 3am on whatever `python3` is
there. Only the two things you look at afterwards want a package. So the first time you run `dash` (or `report`
without `openpyxl`) it asks:

```
textual is needed to draw the dashboard.
Install it into ~/.local/share/autodev/venv (nothing is added to this project)? [Y/n]
```

Yes builds one venv of its own — outside every project, shared by all of them — installs the package there, and
starts the same command again in it. Nothing is added to your project's environment, and you do not have to
remember which interpreter has what.

- `--install` says yes without asking (for a script or a first run you already decided about); `--no-install`
  never installs and prints the command that would.
- `AUTODEV_NO_BOOTSTRAP=1` forbids it for every command; `AUTODEV_VENV=/path` puts the venv somewhere else.
- **A run never does this.** No phase, no step and no report written by the orchestrator can install anything:
  a phase that stopped at 3am to install a package, or waited on a network that was not there, is the failure
  this project exists to avoid. `.autodev/REPORT.xlsx` stays a CSV until you ask for the workbook yourself.
- One attempt only — the restart carries a marker, so a broken install ends in a message and not in a process
  that starts itself forever.

## Usage limits

**A ceiling on the run is yours to set.** The usage guard below only keeps the subscription happy: it pauses and
waits, so a long roadmap can keep starting sessions for days. `--max-hours H` and `--max-sessions N` stop the run
instead — the branch, `PROGRESS.md` and the commits are all there, the reason is written into both, and the same
`run` command continues from where it stopped (with a fresh budget, which is the point: spending more is your
decision). **The hour ceiling stops the run at a phase boundary, not wherever the clock happened to fall.** It
used to interrupt whatever was running: in one run it killed an opus review 95 seconds after that review started,
paid for it, threw the work away, and left the phase half-built for the morning. A phase already under way now
gets an hour of grace to finish, and the run stops before the next phase starts; only if the phase is still going
after that grace is the session interrupted, with its resume handle on disk so continuing picks the step up rather
than restarting it. `--max-sessions` counts steps — one step is one session, however many times it had to resume —
and stops between two of them, which is exactly where it belongs. A usage pause that would end after the deadline
does not happen at all: the run stops rather than sleeping into a morning nobody asked for.

**The resume handle survives the step being renamed.** It is stored with the step and phase it belongs to, not
only with the label of the moment: a review interrupted as `p04-review1` and restarted as `p04-review2` used to
match nothing and start from scratch.

**A session that never started is retried, not counted against the step.** Claude Code can fail before it has a
session at all — a corrupted `~/.claude.json` failed a whole overnight run at 22:44, and the error message it
printed was not even kept. There is nothing to resume and nothing was spent, so the orchestrator starts it again
up to three times (20s, then 90s apart), names the cause when it recognises it, and if it still will not start
fails the step with what the machine actually said on stderr.

**`PROGRESS.md` says where the night went.** A first full run took 17.4 hours of wall clock for 9.6 hours of agent
time and none of the difference was visible: five hours of usage pauses and two and a half waiting for a human to
restart it read exactly like time spent building. The **Clock** line now separates the four: time since the run
was created, time working, time paused on the usage limit, and time nobody was running it at all.

Before every session, and every 5 minutes during one, the script reads the 5h/7d utilization. At ≥85% it sends
SIGINT to the current session, sleeps until the reset (+2 min), then `--resume`s the same session. Sources: the
undocumented `api/oauth/usage` (token from `~/.claude/.credentials.json` or the macOS Keychain) +
`rate_limit_event` in stream-json + the text of the limit error. A utilization figure is read from the payload
that states its scale — a used/limit pair, or a field that names its unit — and only then from `utilization`,
where a value below 1 is a fraction; a bare `1` is taken as one percent, because a wrong pause costs the night
while a wrong request is caught by the limit error it comes back with. For a non-standard `CLAUDE_CONFIG_DIR` on macOS:
`AUTODEV_KEYCHAIN_SERVICE="<the Keychain entry name>"`.

## Security

**Commands proposed by a session are vetted.** The orchestrator runs the test and e2e commands itself, with a
shell, so they never pass the permission classifier that guards a session's own Bash calls — and a session reads
the spec, the repository and (unless you disable them) web pages, any of which can try to talk it into proposing
something else. A proposed command is accepted only when every segment starts with a known toolchain binary
(`make`, `uv`, `pytest`, `npm`, `cargo`, `swift`, `xcodebuild`, `go`, `cmake`, `gradle`, `docker`, …) and nothing
in it fetches or evaluates code, escalates privileges, or redirects outside the repository. Commands **you** pass
(`--test-cmd`, `--e2e-cmd`, `--e2e-up-cmd`, `--e2e-down-cmd`) are used as typed and never checked. `docker` and
`podman` stay on that list — a compose project runs its suite through them — but a container the session proposes
may only mount paths inside the repository and may not ask for privileges (`-v /:/host`, `--privileged`,
`--cap-add` and friends are refused), because that is the one way an allowed binary walks around the rest.

**What the vetting does not cover.** It checks the shape of a command, not what the command runs: `make test`
runs whatever the `Makefile` says, and the `Makefile` — like `package.json`, the test suite and the application
itself — is written by the sessions as part of their work. That is not a hole to be closed but the nature of the
tool: an autodev run executes code its sessions wrote, all night, with your environment. The vetting keeps a
proposed command in a predictable shape and catches the obvious `curl … | sh`; it is not a trust boundary. A
commit that changes a file deciding what a command runs (`Makefile`, `justfile`, `package.json`, `pyproject.toml`,
`Taskfile`, a compose file) is named in the timeline, so the morning read shows it — a manifest is read closely
enough to tell a new dependency from a changed script, since `package.json` moves almost every phase and naming it
every time would bury the one change that matters. For a spec you did not write yourself, run the whole thing in a
container or a VM.

A command that does not pass costs nothing in the normal case: the session is told which command was refused and
why, and given one chance to correct it — usually by adding a `make` target or an npm script and returning that
instead. Only if it insists is the command dropped, which is logged, recorded in `DECISIONS.md`, and leaves the
previous command in place. To let a project's own script through from the start, pass `--allow-cmd <binary>`.

**A run with no test command stops.** With none configured every phase would report a passing suite without running
anything, so the branch would be committed, reviewed and documented unverified. If the architect and roadmap steps
both end without a usable test command, the run fails there — minutes after launch — and tells you to pass
`--test-cmd`. Resume with the same `run` command once you have.

**One long session is the expensive way to do the same work.** Every turn is billed for re-reading the whole
conversation, so cost grows with the square of a session's length: the phase-5 implementation of the run this was
tuned on spent $22.57 over 280 turns, most of it re-reading a context that ended over 500k tokens. Prompts asking a
session to stop when its context fills are not enough — that one never did. So the orchestrator reads the context
size out of every turn, and when the implementation step passes `--max-context-tokens` (200k by default) it
interrupts, asks that session for one last turn to checkpoint `PLAN.md` and hand over, and starts a fresh session
on the same phase. `--max-impl-runs` (6 by default) caps how many times that can happen. Only the implementation
step is cut off this way: it is the one that keeps a checkpoint a new session can pick up from.

**The last round of fixes is audited.** A phase that has used up its review rounds used to commit whatever the last
fix session wrote, unseen — four of the seven phases of that run did, one of them carrying a blocker fix to the
input loop. Before the fix session runs, the orchestrator records the tree (`git add -A; git write-tree` — no
commit, no stash), so afterwards `git diff <tree>` is exactly the fixes and nothing else. The audit session is
read-only, sees that diff and the review it answered, and asks three questions: is every blocker and major really
fixed in the product and covered by a test, did the fixes break anything else, and was any rejected finding argued
in `DECISIONS.md`. It approves, or the phase gets one more fix pass and lands with a warning naming the audit file.

**No pull request until there is a commit in it.** `gh pr create` on a branch with nothing on it fails with "No
commits between main and …", which the architect and roadmap pushes did on every run — two failures in the timeline
that read like something was wrong with the repository. The branch is still pushed; the draft PR waits for the
first phase to land.

**The documentation step is scoped to what changed.** The implementation and the review fixes update docs as they
go, so four of the seven phases of that run spent a session to conclude "no changes needed". It still gets checked,
but the session is handed the list of files the phase changed and told to check the documents covering those and
nothing else — and a phase that changed nothing outside `.autodev/` skips the step entirely. When the session
changes no file, the timeline says so rather than leaving a summary that reads like work.

**The run keeps its own numbers.** After every phase and at the end of the run, the orchestrator writes
`.autodev/REPORT.xlsx` from `state.json`: hours (working / paused on the limit / not running), tokens and cost per
model, cost per step type and per phase, one row per session, and a budget sheet whose formulas estimate the next
run from this one's measured per-phase cost. It is written by the script, so it costs no tokens and no session; it
is gitignored, because it is derived. `python3 …/autodev.py report [--out FILE]` rebuilds it on demand — including
for a run that predates this, which is recovered from `.autodev/logs/`. Without `openpyxl` installed the same table
lands in `.autodev/REPORT.csv` instead.

**The decision log is read in slices.** `DECISIONS.md` is the one file that grows all night — 164 KB and 216
entries by the end of that run — and every plan, implementation and review was told to read it whole, which by the
last phase was tens of thousands of tokens of fixed tax per session. The sessions' own headings did not help: 23 of
them in four different shapes, one phase's section sitting above the architect's. The orchestrator now writes one
`## <step>` section per step in run order (and takes the heading back off again if the step decided nothing), so
`grep -n '^## '` is an index. Each phase prompt hands the session the exact slice it needs — `sed -n '/^## p03-/,$p'`
for phase 4 — and tells it to grep the older entries by topic instead of reading them. Only `finalize` still reads
the whole log, which is its job: the morning briefing lists the decisions a human might overrule.

**A green suite that ran nothing is a warning.** The summary in `PROGRESS.md` used to be the last line of the test
output, and the last line of `cargo test` is a doc-test block that always reads `0 passed; 0 failed` — every phase of
a run was recorded as having verified nothing. The runner's own summary lines are read instead (cargo, pytest,
jest/vitest, `go test`, `xcodebuild`), so the timeline says `303 passed, 0 failed`; when a recognised suite exits 0
having run no test at all, that goes in the phase's warnings, because a passing exit code over zero tests certifies
nothing. An unrecognised runner falls back to the last line, as before.

**A review round is spent only when its verdict lands.** The round counter used to be raised before the review
session, so a review that never finished — a crashed stream, a kill, a restart — still cost the phase a round: it
came back as round 2, was told to check findings in a `REVIEW-r<n-1>.md` nobody had written, and its one real review
was gone. Now the round counts when `REVIEW-r<n>.md` is on disk. A round that returns no verdict is run once more,
and only then given up with a warning; a session that crashes leaves the round for the next `run` to retry.

**An environment excuse is checked.** A session that cannot do something blames the environment far more readily than
itself, and the excuse travels: into `PLAN.md` as a `[~]` task, into the docs, into the morning handoff, where it
reads as a fact nobody checked. Sessions are told that a limitation needs the command that proves it and its output
in `DECISIONS.md`, and the cheap claims — no git remote, no TTY or pty, no `gh` authentication — are re-checked by
the orchestrator against `git remote`, `pty.openpty()` and `gh auth status` in every step summary, in the `[~]` lines
of a plan, and in `HANDOFF.md`. A claim the run can disprove is named in the log, the timeline, `DECISIONS.md` and
the phase's warnings, so what was skipped for that reason reads as undone rather than impossible.

**What a session can reach.** Sessions run with `--permission-mode auto` (a classifier checks each action) and
`--permission-prompts none`. On top of that, a session gets no `AUTODEV_*` variable from the environment (the
usage token above all), no MCP server beyond the ones you name with `--mcp-config`, and no web access: `WebFetch`
and `WebSearch` are blocked unless you pass `--web on`. Web access is the one channel that reaches outside the
repository, which is why an unattended run does without it by default — turn it on when the work needs to look
something up. `--inherit-mcp` hands the sessions your own MCP servers instead. Hooks from `~/.claude` still run
in the sessions: check that they do not block large changes (e.g. PR size limits). `--permission-mode bypass` —
only inside Docker or a VM. Never run e2e against production: `--e2e-up-cmd` must bring up local services with
test data.

The rest of the environment is inherited as it is: a session — and every test command the orchestrator runs —
sees whatever the terminal you launched from had, `AWS_*`, `GH_TOKEN`, `KUBECONFIG` and all. Start an unattended
run from a shell that carries only what the project needs.

**The review step is checked for read-only behaviour.** The reviewer session runs without `Edit`, `Write` and
`NotebookEdit`, but it keeps `Bash`, and `sed -i` writes files all the same. So the working tree is fingerprinted
(`git status --porcelain`, `.autodev/` aside) before and after the review: anything it changed is named in the log
and in the phase's warnings, because those edits ride along in the phase commit without having been reviewed. The
changes are not undone — a reviewer that fixed a real bug should not have the fix thrown away — only reported.

**The working guides are restored if a session rewrites them.** `.autodev/guides/` is the instruction set every
session reads, it is gitignored, so the tree check above cannot see it. Its files are hashed around every session;
one that wrote to them gets them replaced from the skill before the next session starts, and the files are named
under **Run warnings** in `PROGRESS.md` — a run warning rather than a phase warning, since the architect, roadmap
and finalize steps have no phase to belong to.

**Commit hooks are not bypassed.** A pre-commit hook is this repository's own check — usually the secret scanner
or the lint gate — so a hook that rejects a commit stops the run instead of being worked around. The one case
handled automatically is a hook that reformats files and then fails: what it wrote is restaged and committed once.
`--allow-no-verify` restores the old behaviour for a repository whose hooks are known to be broken, and every
bypass is recorded in `DECISIONS.md`.

**Not everything a session leaves behind gets committed.** `git add -A` cannot tell a phase's work from whatever
else is in the tree, so the index is filtered before every commit. Held back: files that normally hold credentials
(`.env`, `*.pem`, `id_rsa`, `.netrc`, a service-account JSON), installed or generated directories (`node_modules/`,
`.venv/`, `target/debug/`, `e2e/artifacts/`, `DerivedData/`), anything larger than `--max-file-mb` (5 MB by
default), and any file whose contents match a credential — an AWS key id, a GitHub or Slack token, a private key
block, a signed token. A held-back file stays in the working tree and is named in the log, in `DECISIONS.md` and
in the phase's warnings. Gitignore it if it does not belong in the repository, or commit it yourself if it does —
after that it is an ordinary tracked file and nothing stops it again.

**A run belongs to the machine that started it.** `.autodev/state.json` names the commands the orchestrator runs
and the branch it pushes, and a repository can carry a `.autodev/` of its own. Each run is claimed by a marker
kept outside the repository (`~/.autodev/runs/`, or `AUTODEV_HOME`), and state that did not start here is refused:
start over with `--fresh`, or read `.autodev/state.json` and accept it deliberately with `--adopt`.

## What to edit in the skill itself

- `prompts/` — one file per pipeline step (`architect`, `roadmap`, `plan`, `implement`, `test_fix`,
  `review`, `review_fix`, `e2e`, `e2e_fix`, `docs`, `finalize`) + `intake.md` for the pre-start interview.
- `guides/` — working rules shared across all stacks (oracles, case taxonomy, debugging, documentation style).
- `profiles/` — stack profiles. A new stack = one more file modeled on `profiles/generic.md`.
- `scripts/autodev.py` — the entry point: the phase state machine, the sessions, git and the CLI. A phase step is
  a method named in `PHASE_STEPS` that does the work and returns the step the phase moves to.
- `scripts/autodev_lib/` — the parts that stand on their own: `util.py` (paths, logging, git, helpers),
  `commands.py` (which commands the orchestrator will run, and how a container is fenced in), `staging.py` (what
  must never reach a commit, and which files decide what a command runs), `usage.py` (the limit guard),
  `github.py` (committing, pushing and the draft PR as one explicit account), `toolchain.py` (what has to be
  installed for each profile, and the command that installs it), `bootstrap.py` (the tooling venv `dash` and
  `report` may build for themselves — and that no run ever touches), `dashdata.py` (what the dashboard draws, derived
  from `state.json`) and `dash.py` (the dashboard itself — the only module that needs a package outside the
  stdlib, and the only one a run works without).
- `tests/test_autodev.py` — 314 tests, stdlib only, nothing leaves the process: no session is started, no network
  call is made. They cover what used to break silently — where a phase goes after each step, which commands the
  orchestrator agrees to run, how a limit is read, when a run stops, and that a resumed run is on its own branch.
  Run them with `python3 -m unittest discover -s tests` from the repository root; a change to the phase machine
  without a test for its route is how C2 and C3 happened the first time.

## Tests

```bash
python3 -m unittest discover -s tests        # from the repository root
```

Stdlib only, a few seconds, no Claude session and no network: the phase machine runs against stubs, so a change
to where a phase goes after a step fails a test here instead of surfacing at 3am. The suite also checks that every
prompt and guide a step reads is shipped, and that no command a profile suggests would be refused.
