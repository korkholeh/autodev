# autodev — autonomous development from a spec

A technology-neutral pipeline: architecture → phases → for each phase plan → implementation → tests → review →
end-to-end (e2e) QA → documentation → commit. Every step is a separate headless Claude Code session with a clean
context. Works for native Swift apps (macOS, iOS), Rust TUIs, Django+React, FastAPI+React, Django+htmx, and any
other stack (the `generic` profile).

## Installation

```bash
unzip autodev.zip -d ~/.claude/skills/      # → ~/.claude/skills/autodev/SKILL.md
brew install tmux                            # so the process survives closing the terminal
```

Requirements: Claude Code ≥ 2.1.259 (for `--permission-prompts none`), Python 3.9+, git with `user.email`
configured, and your stack's toolchain (Xcode, cargo, uv/npm, etc. — `doctor` will check).

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
                                                            │          └─► review_fix ─► tests ─► review (round 2)
                                                            └─► test_fix (≤3) ─► tests
                                                                                        ─► finalize (docs + HANDOFF)
```

- **architect** — before any code: `ARCHITECTURE.md`, ADRs in `docs/dev/adr/`, a risk register `RISKS.md`,
  the exact stack commands in `.autodev/PROFILE.md`.
- **e2e** — only for phases marked `user_facing` in the roadmap. The up command must return once the surfaces
  are up (a command that stays in the foreground needs `--e2e-ready-url`). First a plan with an oracle
  (`e2e/plans/<feature>.plan.yaml`), then the specs, then a run that fixes **the product**, not the tests.
  Services are brought up by the script (`--e2e-up-cmd`), not by the agent.
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
| `.autodev/PROGRESS.md` | control document: status, phases, timeline, usage-limit consumption |
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

## Flags

| Flag | What it does |
|---|---|
| `--profile NAME` | stack profile (auto-detection by default) |
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
| `--model-plan\|impl\|review\|qa` | models per step (opus / sonnet / opus / sonnet) |
| `--max-test-fix`, `--max-e2e-fix`, `--max-review-rounds`, `--max-impl-runs` | loop limits |
| `--gh-user LOGIN` | token via `gh auth token --user LOGIN`; the active gh account is **not switched** |
| `--push phase\|end\|never` | when to push the `autodev/…` branch (with `--gh-user`, after every phase by default) |
| `--pr` | draft PR into the base branch, body = the current `PROGRESS.md` (handy to watch from a phone) |
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

## Control

- status: `autodev.py status` · log: `tail -f .autodev/autodev.log` · e2e services: `.autodev/logs/e2e-surfaces.log`
- stop after the current session: `touch .autodev/STOP` · immediately: Ctrl-C (the session will be resumed on the
  next `run`; a second Ctrl-C kills the session's whole process group, so the tests and dev servers it started go
  with it). The resume handle is written to `state.json` as soon as a session names itself, so even a power cut
  costs the current session, not the step.
- continue: the same `run` · start over: `run --fresh` (the previous `.autodev/` is archived next to it, and
  `INTAKE.md` — the answers from the pre-flight interview — is carried over into the new run)
- the spec belongs to the run: a `--spec` that differs from the one being resumed is reported and ignored;
  `--fresh` is how you change it
- the run needs a branch to start from, so a detached HEAD stops it before the first session (`doctor` says so too)

## Usage limits

Before every session, and every 5 minutes during one, the script reads the 5h/7d utilization. At ≥85% it sends
SIGINT to the current session, sleeps until the reset (+2 min), then `--resume`s the same session. Sources: the
undocumented `api/oauth/usage` (token from `~/.claude/.credentials.json` or the macOS Keychain) +
`rate_limit_event` in stream-json + the text of the limit error. For a non-standard `CLAUDE_CONFIG_DIR` on macOS:
`AUTODEV_KEYCHAIN_SERVICE="<the Keychain entry name>"`.

## Security

**Commands proposed by a session are vetted.** The orchestrator runs the test and e2e commands itself, with a
shell, so they never pass the permission classifier that guards a session's own Bash calls — and a session reads
the spec, the repository and (unless you disable them) web pages, any of which can try to talk it into proposing
something else. A proposed command is accepted only when every segment starts with a known toolchain binary
(`make`, `uv`, `pytest`, `npm`, `cargo`, `swift`, `xcodebuild`, `go`, `cmake`, `gradle`, `docker`, …) and nothing
in it fetches or evaluates code, escalates privileges, or redirects outside the repository. Commands **you** pass
(`--test-cmd`, `--e2e-cmd`, `--e2e-up-cmd`, `--e2e-down-cmd`) are used as typed and never checked.

A command that does not pass costs nothing in the normal case: the session is told which command was refused and
why, and given one chance to correct it — usually by adding a `make` target or an npm script and returning that
instead. Only if it insists is the command dropped, which is logged, recorded in `DECISIONS.md`, and leaves the
previous command in place. To let a project's own script through from the start, pass `--allow-cmd <binary>`.

**A run with no test command stops.** With none configured every phase would report a passing suite without running
anything, so the branch would be committed, reviewed and documented unverified. If the architect and roadmap steps
both end without a usable test command, the run fails there — minutes after launch — and tells you to pass
`--test-cmd`. Resume with the same `run` command once you have.

**What a session can reach.** Sessions run with `--permission-mode auto` (a classifier checks each action) and
`--permission-prompts none`. On top of that, a session gets no `AUTODEV_*` variable from the environment (the
usage token above all), no MCP server beyond the ones you name with `--mcp-config`, and no web access: `WebFetch`
and `WebSearch` are blocked unless you pass `--web on`. Web access is the one channel that reaches outside the
repository, which is why an unattended run does without it by default — turn it on when the work needs to look
something up. `--inherit-mcp` hands the sessions your own MCP servers instead. Hooks from `~/.claude` still run
in the sessions: check that they do not block large changes (e.g. PR size limits). `--permission-mode bypass` —
only inside Docker or a VM. Never run e2e against production: `--e2e-up-cmd` must bring up local services with
test data.

**The review step is checked for read-only behaviour.** The reviewer session runs without `Edit`, `Write` and
`NotebookEdit`, but it keeps `Bash`, and `sed -i` writes files all the same. So the working tree is fingerprinted
(`git status --porcelain`, `.autodev/` aside) before and after the review: anything it changed is named in the log
and in the phase's warnings, because those edits ride along in the phase commit without having been reviewed. The
changes are not undone — a reviewer that fixed a real bug should not have the fix thrown away — only reported.

**The working guides are restored if a session rewrites them.** `.autodev/guides/` is the instruction set every
session reads, it is gitignored, so the tree check above cannot see it. Its files are hashed around every session;
one that wrote to them gets them replaced from the skill before the next session starts, and the phase carries a
warning naming the files.

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
  `commands.py` (which commands the orchestrator will run), `usage.py` (the limit guard), `github.py`.

## Tests

```bash
python3 -m unittest discover -s tests        # from the repository root
```

Stdlib only, a few seconds, no Claude session and no network: the phase machine runs against stubs, so a change
to where a phase goes after a step fails a test here instead of surfacing at 3am. The suite also checks that every
prompt and guide a step reads is shipped, and that no command a profile suggests would be refused.
