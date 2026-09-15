# Using autodev — a guide for the developer whose project this is

autodev builds software from a specification while you sleep. You write the spec, answer a few questions, and go to
bed; in the morning there is a branch with commits, tests, documentation, and a briefing that says what was actually
verified and what was only claimed.

This guide is about *using* it: what it does overnight, what kind of project it suits, how to write a spec it can
work from, and — the part that matters most — how to check in the morning whether the result is real.

`README.md` is the reference (every flag, every safety rule). This page is the mental model.

---

## 1. The five ideas

**The spec is the contract.** Everything the run builds comes from one markdown file you write. The run never asks
you anything after it starts, so whatever the spec leaves open becomes a decision some session made at 3am — logged,
but made without you.

**The work is cut into phases.** A planning step turns the spec into a roadmap: typically 3–10 phases, each with a goal,
deliverables and acceptance criteria. A phase is a night's worth of work that ends in one commit, one tag and (if you
asked for pull requests) one reviewable PR.

**Every step is a separate session with an empty head.** Planning, implementing, reviewing, documenting — each is its
own headless Claude Code session that starts knowing nothing except the files. Nothing is remembered between steps;
everything that matters is written down. That is why the run leaves so many documents behind: they *are* its memory.

**Files are the memory, and they are yours to read.** `.autodev/ROADMAP.md`, `PLAN.md` per phase, `REVIEW-r*.md`,
`DECISIONS.md`, `PROGRESS.md`. Nothing about the run is hidden in a conversation you cannot see.

**The script does everything irreversible, not the agents.** Running the test suite, committing, tagging, pushing,
opening pull requests: all done by the orchestrator, from commands you or the architect step agreed on. Sessions are
told never to commit. A session that proposes a command the orchestrator does not recognise as a toolchain command is
refused and told why.

---

## 2. What you can build with it

It works best on **greenfield work with a machine-checkable definition of done**. The gate is the test suite: if
"correct" can be expressed as a test that fails when the product is wrong, the loop has something to push against.

Good fits, with the shape that makes them work:

| Project | Why it fits |
|---|---|
| CLI tools, parsers, data pipelines | Behaviour is input → output; tests are cheap and total |
| Terminal apps (TUI) | Renderable to a buffer and asserted headlessly; no human eye needed |
| HTTP APIs (FastAPI, Django) | Contracts, status codes, fixtures — all assertable |
| Web apps with an e2e layer | Playwright/Cypress drives the real product; autodev fixes the product, not the test |
| Native apps with a test target (Swift/macOS, iOS) | Model and view-model logic tested; UI tested where the toolchain allows |
| A well-bounded library or service | Public contract first, tests second, docs third — exactly the loop's order |

Poor fits, and what happens if you try anyway:

- **Work whose acceptance is taste.** Visual design, copy, "make it feel nice". It will produce something defensible
  and the review step will approve it, because no test can disagree. Specify pixels and rules, or do this part
  yourself.
- **Anything needing credentials, hardware or a paid third party you cannot hand it.** A session that cannot reach a
  service is told to return `blocked`, and the phase stops. Give it a fake, a local double, or keep it out of scope.
- **Large changes inside an existing codebase with no test suite.** The suite is the only thing preventing confident
  nonsense. A repository without one gets a run that stops at the architect step, by design.
- **Anything where being wrong is expensive and unnoticeable.** Money movement, migrations that drop data, security
  boundaries. Not because it cannot write them, but because you will be reviewing them at 9am with coffee, and the
  branch will look equally tidy either way.

A run is a **first version**, not a finished product: it is what a competent developer produces alone, overnight,
with no one to ask.

---

## 3. Writing a spec it can work from

This is the highest-leverage thing you do. A vague sentence in the spec becomes a phase that builds the wrong thing,
passes its own tests, and is reviewed as correct.

What a spec needs:

1. **One sentence of what it is** — then the reader (and the architect step) knows what shape to expect.
2. **Numbered sections with content, not adjectives.** "9 rooms in a 3×3 grid, three enemy kinds, one save slot" is
   buildable. "A rich world with interesting enemies" is not.
3. **Acceptance criteria you could test yourself.** Each one should suggest its own test. The review step checks every
   criterion against a named test, and flags any criterion no test proves.
4. **The stack, pinned.** Language, framework, versions, and what may *not* be added. Left open, the architect step
   picks — well, but it picks.
5. **Non-goals.** What is deliberately not being built, so a session does not invent it at 3am and charge you for it.
6. **Data and fixtures.** Where test data comes from; what a fake external service should return.
7. **What "done" looks like for the whole thing**, not just per feature: what a person can do, start to finish, when
   it works.

A useful test before launching: *could a competent stranger build this without asking me anything?* If no, the run
will guess — and log the guess in `DECISIONS.md`, where you will read it tomorrow.

Write the spec in whatever language you think in; documents and code stay in the language you pass with `--lang`
(English by default) — the mosslight run's spec was Ukrainian, its code and docs English.

---

## 4. Launching

```bash
/autodev docs/spec.md                                   # in Claude Code, at the project root
/autodev docs/spec.md --profile rust-tui --max-hours 8
/autodev docs/spec.md --gh-user me --pr                 # a draft PR per phase, stacked
```

Three things happen before any code:

1. **`doctor`** — checks the spec, git identity, and the toolchain your stack builds with (git, tmux, the
   compilers and interpreters of the detected profile — each missing one comes with the command that installs
   it), then runs one real headless session, so an expired login or a hook that blocks headless mode is found
   now instead of at 3am. The run checks the same toolchain again in its first seconds and refuses to start
   without it: a session that cannot compile does not report a missing compiler, it reports a phase it finished
   some other way.
2. **The interview** — at most six questions, only about what the spec does not answer, each with a recommended
   default. This is the last time anyone asks you anything. Answer carefully; "whatever you think" costs more here
   than anywhere else.
3. **The run starts in tmux**, so closing the terminal does not kill it.

The flags worth deciding on the first night:

| Flag | Decide it because |
|---|---|
| `--test-cmd "<cmd>"` | The suite is the gate for every phase. If the doctor could not guess it, say it. |
| `--max-hours 8` | Without a ceiling the run continues into the next day and the next usage window. |
| `--pr` / `--gh-user` | A PR per phase is far easier to review than one branch of nine commits. |
| `--e2e-up-cmd` | Web stacks need their services up for end-to-end QA; without this the e2e step is skipped. |
| `--web on` | Off by default. Turn it on if the work needs to look up an unfamiliar or fast-moving API. |
| `--base-branch NAME` | Where the night's work is based. An empty repository gets `main`; an existing one uses the branch you are on unless you name another (or a new one to cut from here). |

---

## 5. What happens overnight

```
architect ─► roadmap ─► for each phase:
   plan ─► implement (×N) ─► tests ─┬─► review ─┬─► e2e ─┬─► docs ─► commit + tag
                                    │          │        └─► e2e_fix ─► docs
                                    │          └─► review_fix ─► tests ─┬─► review (round 2)
                                    │                                   └─► audit (last round)
                                    └─► test_fix ─► tests
                                                        ─► finalize (docs + HANDOFF)
```

- **architect** writes `ARCHITECTURE.md`, ADRs, a risk register, and the exact commands for your stack.
- **plan** turns one phase into an ordered task list with a test named for every acceptance criterion.
- **implement** works through that list, ticking tasks in `PLAN.md` as it goes. A session whose context fills up
  checkpoints and hands over to a fresh one — long sessions cost far more than the same work split.
- **tests** are run by the script, not the agent. A phase whose suite is red gets up to three fix attempts and then
  the run stops; no phase is ever committed with a failing gate.
- **review** is read-only (no `Edit`, no `Write`) and produces `REVIEW-r<n>.md` with severities. Blockers and majors
  go to a fix step, then round two. The fixes of the *last* round get a separate audit: a read-only session that sees
  only the fix diff and says whether the findings were really fixed.
- **e2e** runs on phases marked user-facing, when you configured the services. It fixes the product, not the test.
- **docs** checks the documentation against the files this phase changed.
- **commit** creates the phase commit, tags it `<branch>/phase-NN`, pushes, and (with `--pr`) opens a draft PR.
- **finalize** reconciles all documentation with what was built and writes `.autodev/HANDOFF.md`.

While it runs:

```bash
python3 ~/.claude/skills/autodev/scripts/autodev.py status   # where it is, last 8 events
python3 ~/.claude/skills/autodev/scripts/autodev.py report   # rebuild .autodev/REPORT.xlsx now
tail -f .autodev/autodev.log                                 # live
touch .autodev/STOP                                          # stop gracefully at the next safe point
```

**`.autodev/REPORT.xlsx` is written after every phase** and again when the run ends: hours split into working,
paused on the usage limit and not running at all; tokens and cost per model; cost per step type and per phase; every
session as a row; and a budget sheet that estimates your next run from this one's measured per-phase cost. Open it
in the morning before the diff — it tells you what the night cost and which phase ate it.

Restarting is the same command you launched with: the run picks up from the step it stopped at, and resumes the
interrupted session rather than redoing it.

**Pauses are normal.** Near the usage limit the run interrupts the current session, sleeps until the window resets,
and resumes the same session. `PROGRESS.md` says when it expects to continue. Its **Clock** line separates time
working, time paused and time nobody was running it — read it before concluding the night was slow.

---

## 6. Reading the result in the morning

Do this in order. It takes about twenty minutes and it is the whole point.

**1. Read `.autodev/HANDOFF.md` first.** One screen: what was built, what was verified *by a command that ran*, what
is only assumed, the decisions worth overruling, known gaps, live risks, and what to do first. Everything below is
you checking that this page is telling the truth.

**2. Scan the warnings.** `.autodev/PROGRESS.md` has a warning column per phase and a run-warnings section. These are
the run telling on itself, and they are the highest-value paragraphs in the repository:

| Warning | What it means for you |
|---|---|
| `review round N had blocker/major findings; fixes applied, not re-reviewed` | Only if you turned the audit off. Read that diff yourself. |
| `the audit of the round-N fixes found blocker/major findings` | The last fixes are suspect. Start here. |
| `passed without running a single test` | The gate certified nothing for that phase. |
| `N PLAN.md task(s) left unchecked` | The phase shipped incomplete. |
| `… said <claim> — but <probe>` | A session blamed the environment and the orchestrator disproved it. Whatever it skipped is undone, not impossible. |
| `review round N changed the working tree itself` | The reviewer edited code. Those edits are in the commit, unreviewed. |

**3. Run the gate yourself, from a clean checkout.**

```bash
git checkout autodev/<branch>
<the test command from PROGRESS.md>      # e.g. cargo test --locked, pytest -q, npm test
```

If it does not pass on your machine, nothing else in the briefing matters yet.

**4. Check that the tests can actually fail.** This is the one check nobody else can do for you, and it catches the
failure mode that matters: tests that assert nothing.

```bash
# pick an acceptance criterion, find the test named for it, break the product line it covers
git diff --stat autodev/<branch>~1        # or open the phase's PLAN.md verification table
# then edit the source (not the test), re-run the suite, and confirm it goes red
git checkout -- <the file you broke>
```

Do this two or three times on the parts you care about most. A suite that stays green while the product is broken is
the only really expensive outcome of a night like this.

**5. Read the diff phase by phase**, not as one branch. With `--pr` each phase is its own draft PR with a body that
names what needs a close look. Without it:

```bash
git log --oneline main..autodev/<branch>
git show <branch>/phase-03                # one phase at a time
```

**6. Read `.autodev/DECISIONS.md` for the judgement calls.** It is a log, newest last, one `## ` section per step.
Read the architect's section and anything the handoff called out; grep the rest by topic. This is where you find the
choices you would have made differently.

**7. Check what was *not* verified.** The handoff separates verified from assumed. Typical residue: CI on other
platforms, anything needing a real network, anything needing a device. Those are yours to run.

**8. Then decide.** Merge it, keep the branch and cherry-pick, or throw it away and improve the spec. A run that
produced the wrong thing is usually a spec problem, and the second attempt from a sharper spec is much better than
patching the first.

---

## 7. What it costs, on real numbers

One complete run — a 9-room terminal adventure in Rust, seven phases, spec of moderate detail:

| | |
|---|---|
| Sessions | 53 |
| Agent time | 9.6 h |
| Wall clock | 17.4 h (5 h of usage pauses, the rest waiting for a human to restart it) |
| API-equivalent cost | ≈ $215 |
| Result | 303 tests, a release binary, developer and user docs, one merged branch |

Where the money went: implementation 48%, review and its fix passes 30%, phase planning 9%, everything else
(architect, roadmap, per-phase docs, finalize) 13%. On a subscription the wall clock is dominated by usage-window
pauses, not by the work.

Scale expectations from that: a phase cost $21–41 and roughly one to two hours of agent time, and a spec that
produces seven phases is about one night. A phase with a lot of content in it (the two most expensive above) costs
about twice one that is mostly mechanics.

---

## 8. When something goes wrong

| Symptom | What happened | What to do |
|---|---|---|
| `status: failed` | A step could not produce a usable result, or the suite stayed red after three fix attempts | Read `PROGRESS.md`'s error line and the phase's `TEST_OUTPUT.txt`; fix the blocker yourself, then re-run the same command |
| `status: stopped` | Your ceiling, your `STOP` file, or a usage pause that would outlast the budget | Re-run the same command; it continues where it stopped |
| `status: paused_limit` | Waiting for the usage window | Nothing. `resume ≈` says when |
| A phase committed with warnings | The loop ran out of rounds or attempts | The warnings are in the phase row *and* the commit message; review that phase by hand |
| The run never started a session | Claude Code itself failed to launch (a corrupted config, an expired login) | The step is retried three times and then fails with what stderr said; fix that and re-run |
| It built the wrong thing | The spec allowed it | Read `DECISIONS.md` to find where it diverged, sharpen the spec, `--fresh` |

---

## 9. The short version

- Write a spec a stranger could build from, with acceptance criteria that suggest their own tests.
- Answer the six questions properly; they are the last words you get in.
- Let it run with a ceiling, and expect pauses.
- In the morning: handoff, warnings, run the gate, **break something and watch a test fail**, then read the diff per
  phase.
- Treat the result as a strong first version by a developer who could not ask you anything.

Reference for every flag and every safety rule: `README.md`.
