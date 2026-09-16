"""Everything `autodev dash` draws, derived from `state.json` and nothing else.

Kept apart from the widgets on purpose: the dashboard needs `textual`, which is optional, but the
arithmetic behind it — how far a phase has come, where the night went, what the tokens cost — is
stdlib and testable, and the same numbers answer `status` and the spreadsheet. Nothing here writes
to the run; a dashboard that could corrupt the state it watches would not be worth having.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from autodev_lib import report
from autodev_lib.util import AD, PID_FILE, STATE_FILE, STOP_FILE

# The spine of a phase: the steps every phase passes through, in order. The fix steps are not on it
# — `test_fix` is the phase going round the test step again, not progress past it — so a phase that
# fails its suite three times keeps reading as "at the tests" instead of marching on to `commit`.
SPINE = ("plan", "implement", "test", "review", "e2e", "docs", "commit")
STEP_SPINE = {"plan": "plan", "implement": "implement",
              "test": "test", "test_fix": "test",
              "review": "review", "review_fix": "review", "review_audit": "review",
              "e2e": "e2e", "e2e_fix": "e2e",
              "docs": "docs", "commit": "commit"}
RUN_STEPS = ("architect", "roadmap", "finalize", "done")
TOKEN_FIELDS = ("in", "cache_w", "cache_r", "out", "think")


def load(path: Path = STATE_FILE) -> "dict | None":
    """The run state, or None when there is no run here (or it is mid-write).

    `state.json` is replaced atomically, so a half-file should never be read; the parse is guarded
    anyway, because a dashboard that dies on one unlucky read is worse than one that skips a frame.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_ts(value) -> float:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").timestamp()
    except (TypeError, ValueError):
        return 0.0


def process_alive() -> bool:
    try:
        os.kill(int(PID_FILE.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def stop_requested() -> bool:
    """A STOP file is waiting to be noticed — the run is stopping but has not stopped yet."""
    return STOP_FILE.exists()


# ---------------------------------------------------------------------------- phases
@dataclass
class Phase:
    n: int
    title: str
    slug: str
    status: str
    step: str           # the step it is on, for the phase that is running
    progress: float     # 0.0 – 1.0
    commit: str
    user_facing: bool
    warnings: list = field(default_factory=list)
    cost: float = 0.0
    seconds: int = 0
    sessions: int = 0


def phases(state: dict) -> list:
    st = state or {}
    idx, step = st.get("phase_index", 0), st.get("step", "")
    by_phase = report.group(st.get("sessions") or [], lambda s: report.phase_of(s.get("label", "")))
    out = []
    for i, ph in enumerate(st.get("phases") or []):
        spent = by_phase.get(f"phase {i + 1}", {})
        out.append(Phase(
            n=i + 1, title=ph.get("title", ""), slug=ph.get("slug", ""),
            status=ph.get("status", "pending"),
            step=step if i == idx and step not in RUN_STEPS else "",
            progress=phase_progress(ph, i == idx, step),
            commit=(ph.get("commit") or "")[:8],
            user_facing=bool(ph.get("user_facing", True)),
            warnings=list(ph.get("warnings") or []),
            cost=round(spent.get("cost", 0.0), 2), seconds=spent.get("sec", 0), sessions=spent.get("n", 0)))
    return out


def phase_progress(ph: dict, current: bool, step: str) -> float:
    if ph.get("status") == "done":
        return 1.0
    if not current or step in RUN_STEPS:
        return 0.0
    key = STEP_SPINE.get(report.step_of(step or ""))
    return SPINE.index(key) / len(SPINE) if key else 0.0


def overall_progress(state: dict) -> float:
    """One number for the whole run: the phases, averaged.

    Before the roadmap exists there are no phases to average, and the architect step is most of an
    hour — so it reads as the sliver of the run it is rather than as a stalled zero."""
    st = state or {}
    rows = st.get("phases") or []
    if not rows:
        return 0.02 if st.get("step") == "roadmap" else 0.0
    done = sum(p.progress for p in phases(st))
    return min(done / len(rows), 1.0)


def eta_seconds(state: dict) -> "float | None":
    """A guess at the time left, from what the finished phases actually took.

    Only the phases that completed are evidence, and only their own sessions count, so a run that
    spent the night paused on a usage limit is not credited with the waiting."""
    st = state or {}
    rows = phases(st)
    done = [p for p in rows if p.status == "done" and p.seconds]
    if not done or len(done) == len(rows):
        return None
    per = sum(p.seconds for p in done) / len(done)
    left = 0.0
    for p in rows:
        if p.status != "done":
            left += per * max(1.0 - p.progress, 0.0)
    return left or None


# ---------------------------------------------------------------------------- agents
@dataclass
class Agent:
    n: int
    label: str
    phase: str
    step: str
    model: str
    seconds: float
    turns: int
    cost: float
    tokens: int
    error: str
    state: str          # running | done | error


def agents(state: dict, now: "float | None" = None) -> list:
    """One row per headless session the run has started, newest first, the live one on top.

    autodev runs one session at a time, so this is the run's own history of who did what: which
    step, in which model, for how long, at what price."""
    st = state or {}
    now = time.time() if now is None else now
    rows = []
    act = st.get("active_session") or {}
    if act.get("label"):
        started = parse_ts(act.get("started"))
        rows.append(Agent(n=st.get("session_counter", 0), label=act["label"],
                          phase=report.phase_of(act["label"]), step=report.step_of(act["label"]),
                          model=act.get("model", ""), seconds=max(now - started, 0.0) if started else 0.0,
                          turns=0, cost=0.0, tokens=0, error="", state="running"))
    for s in reversed(st.get("sessions") or []):
        label = s.get("label", "")
        rows.append(Agent(n=s.get("n", 0), label=label, phase=report.phase_of(label),
                          step=report.step_of(label), model=s.get("model", ""),
                          seconds=s.get("sec", 0), turns=s.get("turns", 0), cost=s.get("cost", 0.0),
                          tokens=sum(int(s.get(k) or 0) for k in TOKEN_FIELDS),
                          error=s.get("error", ""), state="error" if s.get("error") else "done"))
    return rows


# ---------------------------------------------------------------------------- models and tokens
@dataclass
class Model:
    name: str
    sessions: int
    cost: float
    tokens: dict
    total: int


def models(state: dict) -> list:
    """Per-model totals, dearest first — where the money went, not just how much of it."""
    st = state or {}
    per = (st.get("totals") or {}).get("models") or {}
    if not per:                     # a run from before the orchestrator kept these: rebuild by model
        per = {}
        for s in st.get("sessions") or []:
            row = per.setdefault(s.get("model") or "?", {"sessions": 0, "cost": 0.0})
            row["sessions"] += 1
            row["cost"] = round(row["cost"] + (s.get("cost") or 0), 4)
            for k in TOKEN_FIELDS:
                row[k] = row.get(k, 0) + int(s.get(k) or 0)
    out = [Model(name=name, sessions=v.get("sessions", 0), cost=round(v.get("cost", 0.0), 2),
                 tokens={k: int(v.get(k) or 0) for k in TOKEN_FIELDS},
                 total=sum(int(v.get(k) or 0) for k in TOKEN_FIELDS))
           for name, v in per.items()]
    return sorted(out, key=lambda m: (-m.cost, m.name))


def tokens(state: dict) -> dict:
    """Every token the run has been billed for, by kind, summed over its sessions."""
    out = {k: 0 for k in TOKEN_FIELDS}
    for s in (state or {}).get("sessions") or []:
        for k in TOKEN_FIELDS:
            out[k] += int(s.get(k) or 0)
    out["total"] = sum(out[k] for k in TOKEN_FIELDS)
    return out


# ---------------------------------------------------------------------------- clock
@dataclass
class Clock:
    wall: float
    working: float
    paused: float
    idle: float


def clock(state: dict, now: "float | None" = None) -> Clock:
    """Working, paused on the usage limit, and nobody running it — the three parts of a night.

    The difference matters: a run that took seventeen hours to do nine hours of work was not slow,
    it was waiting, and only this split says which kind of waiting it was."""
    st = state or {}
    now = time.time() if now is None else now
    created = parse_ts(st.get("created"))
    tot = st.get("totals") or {}
    working = float(tot.get("seconds") or 0)
    paused = float(tot.get("paused") or 0)
    wall = max(now - created, 0.0) if created else working + paused
    return Clock(wall=wall, working=working, paused=paused,
                 idle=max(wall - working - paused, 0.0))


# ---------------------------------------------------------------------------- headline
@dataclass
class Head:
    project: str
    status: str
    step: str
    phase_no: int
    phase_total: int
    branch: str
    spec: str
    profile: str
    pr_url: str
    test_command: str
    resume_at: str
    error: str
    stop_reason: str
    alive: bool
    stopping: bool
    sessions: int
    cost: float
    warnings: list


def head(state: dict) -> Head:
    st = state or {}
    rows = st.get("phases") or []
    proj = st.get("project") or {}
    tot = st.get("totals") or {}
    alive = process_alive()
    return Head(
        project=proj.get("name") or Path.cwd().name,
        status=st.get("status", "?"), step=st.get("step", "?"),
        phase_no=min(st.get("phase_index", 0) + 1, len(rows)) if rows else 0, phase_total=len(rows),
        branch=st.get("branch") or "—", spec=st.get("spec") or "—", profile=st.get("profile") or "—",
        pr_url=st.get("pr_url") or "", test_command=proj.get("test_command") or "—",
        resume_at=st.get("resume_at") or "", error=st.get("error") or "",
        stop_reason=st.get("stop_reason") or "",
        alive=alive, stopping=alive and stop_requested(),
        sessions=int(tot.get("sessions") or 0), cost=float(tot.get("cost_usd") or 0.0),
        warnings=list(st.get("run_warnings") or [])[-20:])


def events(state: dict, limit: int = 200) -> list:
    return list((state or {}).get("events") or [])[-limit:]


def log_tail(lines: int = 2000, path: Path = AD / "autodev.log") -> list:
    """The last lines of `autodev.log`, read from the end so a night's log stays cheap to show."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:            # 400 bytes a line is generous for this log
            f.seek(max(size - lines * 400, 0))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = data.splitlines()
    if len(out) > 1 and size > lines * 400:
        out = out[1:]                          # the first line was cut in half by the seek
    return out[-lines:]


# ---------------------------------------------------------------------------- formatting
def hms(seconds: float) -> str:
    s = int(max(seconds, 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def compact(n: float) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}"
    return str(int(n))


def bar(fraction: float, width: int = 20) -> str:
    """A histogram bar in eighths of a cell, so short bars still differ from each other."""
    cells = max(0.0, min(fraction, 1.0)) * width
    full, rest = int(cells), cells - int(cells)
    return "█" * full + (" ▏▎▍▌▋▊▉"[int(rest * 8)] if int(rest * 8) else "")
