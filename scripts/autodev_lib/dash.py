"""`autodev dash` — the run, live, in a terminal.

A read-mostly window onto `state.json`: how far the phases have come, which session is working and
for how long, what the night has cost, and where its hours actually went. The two things it does
write are the two a person watching a run wants at 3am — the STOP file, and the command that starts
the orchestrator again.

`textual` is an optional dependency; `autodev.py` catches the ImportError and says how to install
it, so a run never depends on the dashboard being installable.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, Log, ProgressBar, Static

from autodev_lib import dashdata as D
from autodev_lib.util import AD, STATE_FILE, STOP_FILE

REFRESH = 1.0                       # the clocks tick every second; the state is re-read when it changes
STATUS_STYLE = {"running": "bold green", "done": "bold green", "paused_limit": "bold yellow",
                "stopped": "bold yellow", "failed": "bold red"}
PHASE_ICON = {"pending": "⏳", "in_progress": "🔨", "done": "✅", "failed": "❌"}
AGENT_ICON = {"running": ("▶", "bold green"), "done": ("✓", "dim"), "error": ("✗", "bold red")}


def short_label(label: str) -> str:
    """`p02-review1` → `p2-review1`: the phase number is an index, not a serial number."""
    return re.sub(r"^p0*(\d+)-", r"p\1-", label or "")


def orchestrator() -> Path:
    return Path(__file__).resolve().parent.parent / "autodev.py"


def resume_run() -> str:
    """Start the orchestrator again on the run in this directory. Returns what it did.

    A STOP file left over from the last stop is cleared first: it is consumed by whichever run
    notices it, and an uncleared one would stop the new run within seconds of it starting."""
    if D.process_alive():
        return "already running"
    if STOP_FILE.exists():
        STOP_FILE.unlink()
    cmd = [sys.executable, str(orchestrator()), "run"]
    session = f"autodev-{Path.cwd().name}"
    if shutil.which("tmux"):
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-c", str(Path.cwd()),
                        " ".join(f"'{c}'" for c in cmd) + f"; exec {os.environ.get('SHELL', 'sh')}"],
                       capture_output=True, text=True)
        return f"started in tmux session {session}"
    with open(AD / "autodev.log", "a", encoding="utf-8") as log:
        subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    return "started in the background (no tmux — it ends with this terminal)"


class ConfirmScreen(ModalScreen):
    """Resume spends money and writes commits, so it is asked for rather than assumed."""

    BINDINGS = [Binding("escape", "dismiss(False)", "cancel")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Label(self.question, id="confirm-q")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", variant="primary", id="yes")
                yield Button("Cancel", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()        # otherwise it bubbles on to the app's own button handler
        self.dismiss(event.button.id == "yes")


class LogScreen(ModalScreen):
    """`.autodev/autodev.log`, tailed — the one thing the panels cannot summarise."""

    BINDINGS = [Binding("escape,q,l", "dismiss", "close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="logbox"):
            yield Label("autodev.log — esc to close", id="log-title")
            yield Log(id="logview", highlight=True)

    def on_mount(self) -> None:
        self.seen = 0
        self.tail()
        self.set_interval(REFRESH, self.tail)

    def tail(self) -> None:
        lines = D.log_tail()
        if len(lines) < self.seen:      # the log was rotated or truncated under us
            self.query_one("#logview", Log).clear()
            self.seen = 0
        new = lines[self.seen:]
        if new:
            self.query_one("#logview", Log).write_lines(new)
            self.seen = len(lines)


class Dashboard(App):
    CSS = """
    Screen { layers: base; }
    #toolbar { height: 3; padding: 0 1; background: $panel; }
    #toolbar Button { min-width: 10; margin-right: 1; }
    #chips { width: 1fr; content-align: right middle; padding-right: 1; }
    #body { height: 1fr; }
    #sidebar { width: 44; border-right: solid $primary-darken-2; }
    #main { width: 1fr; }
    .panel-title { background: $boost; padding: 0 1; text-style: bold; }
    #phases { height: 1fr; }
    #agents, #phase-table { height: 1fr; }
    #stats { height: 10; border-top: solid $primary-darken-2; }
    #stats > Static { width: 1fr; padding: 0 1; }
    #global { height: 4; padding: 0 1; border-top: solid $primary-darken-2; }
    #global-caption { height: 1; }
    #confirm { align: center middle; width: 66; height: auto; border: thick $primary;
               background: $surface; padding: 1 2; }
    #confirm-q { width: 100%; height: auto; text-align: center; padding-bottom: 1; }
    #confirm-buttons { height: 3; align: center middle; }
    #confirm-buttons Button { margin: 0 1; }
    #logbox { width: 90%; height: 90%; border: thick $primary; background: $surface; }
    #log-title { background: $boost; width: 100%; padding: 0 1; text-style: bold; }
    #logview { height: 1fr; }
    """
    BINDINGS = [
        Binding("s", "stop", "Stop"),
        Binding("r", "resume", "Resume"),
        Binding("l", "log", "Log"),
        Binding("a", "agents", "Agents"),
        Binding("t", "theme", "Theme"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, light: bool = False) -> None:
        super().__init__()
        self.light = light
        self.state: dict = {}
        self.stamp = -1.0
        self.pinned_sidebar = False
        self.agent_shape: list = []

    # ---- layout ---------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="toolbar"):
            yield Button("⏹ Stop", id="stop", variant="warning")
            yield Button("▶ Resume", id="resume", variant="success")
            yield Button("≡ Log", id="log")
            yield Static("", id="chips")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("Agents", classes="panel-title")
                yield DataTable(id="agents", cursor_type="row", zebra_stripes=True)
            with Vertical(id="main"):
                with Vertical(id="phases"):
                    yield Static("Phases", id="phases-title", classes="panel-title")
                    yield DataTable(id="phase-table", cursor_type="row", zebra_stripes=True)
                with Horizontal(id="stats"):
                    yield Static(id="models")
                    yield Static(id="tokens")
                    yield Static(id="clock")
        with Vertical(id="global"):
            yield Static("", id="global-caption")
            yield ProgressBar(total=100, show_eta=False, id="global-bar")
        yield Footer()

    def on_resize(self, event) -> None:
        """A phone-width tmux pane drops the sidebar rather than squeezing both columns.

        `a` brings it back when the terminal is wide enough to be worth it."""
        try:
            if not self.pinned_sidebar:
                self.query_one("#sidebar").display = event.size.width >= 96
            self.query_one("#stats").display = event.size.height >= 20
        except NoMatches:       # a resize can arrive before the panels are mounted
            pass

    def action_agents(self) -> None:
        panel = self.query_one("#sidebar")
        panel.display = not panel.display
        self.pinned_sidebar = panel.display

    def on_mount(self) -> None:
        self.apply_theme()
        agents = self.query_one("#agents", DataTable)
        for label, key in (("", "icon"), ("#", "n"), ("step", "step"), ("model", "model"),
                           ("time", "time"), ("$", "cost")):
            agents.add_column(label, key=key)
        self.query_one("#phase-table", DataTable).add_columns(
            "#", "phase", "status", "progress", "step", "sess", "time", "$", "commit")
        self.tick()
        self.set_interval(REFRESH, self.tick)

    # ---- theme ----------------------------------------------------------------
    def apply_theme(self) -> None:
        if hasattr(self, "theme"):              # Textual ≥ 0.86 names its themes
            self.theme = "textual-light" if self.light else "textual-dark"
        else:                                   # older builds have a dark switch and nothing else
            self.dark = not self.light

    def action_theme(self) -> None:
        self.light = not self.light
        self.apply_theme()

    # ---- refresh --------------------------------------------------------------
    @contextmanager
    def keep_place(self, table: DataTable):
        """Put a rebuilt table back where the reader had it — same row, same scroll position."""
        row, offset = table.cursor_row, table.scroll_offset.y
        yield
        if table.row_count:
            # `scroll=False`: moving the cursor would otherwise drag the view back to it, which is
            # what threw a reader scrolled halfway down the sessions back to the top on every save.
            table.move_cursor(row=min(max(row, 0), table.row_count - 1), animate=False, scroll=False)
            table.scroll_to(y=offset, animate=False, force=True, immediate=True)

    def tick(self) -> None:
        """Re-read the state only when it changed; redraw the clocks every time.

        A run saves `state.json` after every step and every session — often enough to watch, rarely
        enough that re-parsing it once a second for an hour would be waste."""
        try:
            stamp = STATE_FILE.stat().st_mtime
        except OSError:
            stamp = 0.0
        if stamp != self.stamp:
            self.state = D.load() or {}
            self.stamp = stamp
            self.draw_phases()
        self.draw_head()
        self.draw_agents()
        self.draw_stats()
        self.draw_global()

    def draw_head(self) -> None:
        h = D.head(self.state)
        chips = Text()
        chips.append(f" {h.status} ", style=STATUS_STYLE.get(h.status, "bold"))
        chips.append(" · ")
        chips.append("stopping…" if h.stopping else ("running" if h.alive else "no process"),
                     style="bold yellow" if h.stopping else ("green" if h.alive else "dim"))
        chips.append(f" · step {h.step}")
        if h.phase_total:
            chips.append(f" · phase {h.phase_no}/{h.phase_total}")
        chips.append(f" · {h.branch}")
        if h.resume_at:
            chips.append(f" · resumes ≈ {h.resume_at}", style="yellow")
        if h.error:
            chips.append(f" · {h.error[:60]}", style="red")
        self.query_one("#chips", Static).update(chips)
        self.title = f"autodev — {h.project}"
        self.sub_title = f"{h.spec} · {h.profile}" + (f" · {h.pr_url}" if h.pr_url else "")
        self.query_one("#stop", Button).disabled = not h.alive or h.stopping
        self.query_one("#resume", Button).disabled = h.alive

    def draw_phases(self) -> None:
        table = self.query_one("#phase-table", DataTable)
        with self.keep_place(table):
            table.clear()
            self.fill_phases(table)
        warn = [w for p in D.phases(self.state) for w in p.warnings] + D.head(self.state).warnings
        title = Text("Phases")
        if warn:
            title.append(f"  ⚠ {len(warn)} warning(s)", style="yellow")
        self.query_one("#phases-title", Static).update(title)

    def fill_phases(self, table: DataTable) -> None:
        for p in D.phases(self.state):
            style = {"done": "green", "failed": "red", "in_progress": "bold"}.get(p.status, "dim")
            title = Text(p.title[:32], style=style)
            if not p.user_facing:
                title.append(" ·int", style="dim")
            table.add_row(
                str(p.n), title,
                Text(f"{PHASE_ICON.get(p.status, '')} {p.status}", style=style),
                Text(f"{D.bar(p.progress, 18):<18} {p.progress * 100:3.0f}%",
                     style="green" if p.status == "done" else "cyan"),
                Text(p.step or "", style="bold" if p.step else "dim"),
                str(p.sessions or ""), D.hms(p.seconds) if p.seconds else "",
                f"{p.cost:.2f}" if p.cost else "",
                Text(p.commit, style="dim"))

    def draw_agents(self) -> None:
        """Rebuilt only when the list of sessions actually changes.

        It used to be rebuilt every second, which threw whoever was reading it back to the top of
        the list once a second: on most ticks the only thing that moved was the running session's
        clock, so on most ticks that one cell is all that is written."""
        table = self.query_one("#agents", DataTable)
        rows = D.agents(self.state)[:120]
        shape = [(a.n, a.state) for a in rows]
        if shape != self.agent_shape:
            self.agent_shape = shape
            with self.keep_place(table):
                table.clear()
                for a in rows:
                    icon, style = AGENT_ICON[a.state]
                    table.add_row(Text(icon, style=style), str(a.n),
                                  Text(short_label(a.label)[:18], style="bold" if a.state == "running" else ""),
                                  Text((a.model or "—")[:8], style="dim"),
                                  Text(D.hms(a.seconds), style=style if a.state == "running" else ""),
                                  f"{a.cost:.2f}" if a.cost else "",
                                  key=f"{a.n}-{a.state}")
        elif rows and rows[0].state == "running":
            table.update_cell(f"{rows[0].n}-running", "time",
                              Text(D.hms(rows[0].seconds), style=AGENT_ICON["running"][1]))

    def draw_stats(self) -> None:
        models = D.models(self.state)
        top = max([m.cost for m in models] or [0]) or 1
        t = Table.grid(padding=(0, 1))
        for width in (9, 8, 6, 8):
            t.add_column(no_wrap=True, width=width, overflow="ellipsis")
        t.add_row(Text("Models", style="bold"), "", "", Text("tok·n", style="dim"))
        for m in models:
            t.add_row(Text(m.name[:9], style="cyan"), Text(D.bar(m.cost / top, 8), style="cyan"),
                      f"${m.cost:.2f}", Text(f"{D.compact(m.total)}·{m.sessions}", style="dim"))
        if not models:
            t.add_row(Text("no sessions yet", style="dim"), "", "", "")
        self.query_one("#models", Static).update(t)

        tok = D.tokens(self.state)
        total = tok["total"] or 1
        names = {"in": "input", "cache_w": "cache write", "cache_r": "cache read",
                 "out": "output", "think": "thinking"}
        k = Table.grid(padding=(0, 1))
        for width in (11, 10, 7):
            k.add_column(no_wrap=True, width=width, overflow="ellipsis")
        k.add_row(Text("Tokens", style="bold"), "", "")
        for key, label in names.items():
            k.add_row(Text(label, style="dim"), Text(D.bar(tok[key] / total, 10), style="cyan"),
                      D.compact(tok[key]))
        k.add_row(Text("total", style="bold"), "", Text(D.compact(tok["total"]), style="bold"))
        self.query_one("#tokens", Static).update(k)

        c, h = D.clock(self.state), D.head(self.state)
        eta = D.eta_seconds(self.state)
        done = [p for p in D.phases(self.state) if p.status == "done"]
        per = sum(p.cost for p in done) / len(done) if done else 0.0
        g = Table.grid(padding=(0, 1))
        for width in (14, 10):
            g.add_column(no_wrap=True, width=width, overflow="ellipsis")
        g.add_row(Text("Clock & cost", style="bold"), "")
        g.add_row(Text("working", style="dim"), Text(D.hms(c.working), style="green"))
        g.add_row(Text("paused (limit)", style="dim"), Text(D.hms(c.paused), style="yellow"))
        g.add_row(Text("not running", style="dim"), Text(D.hms(c.idle), style="dim"))
        g.add_row(Text("total", style="bold"), Text(D.hms(c.wall), style="bold"))
        g.add_row(Text("sessions", style="dim"), str(h.sessions))
        g.add_row(Text("cost", style="bold"), Text(f"${h.cost:.2f}", style="bold cyan"))
        g.add_row(Text("per phase", style="dim"), f"≈${per:.2f}")
        g.add_row(Text("eta", style="dim"), D.hms(eta) if eta else "—")
        self.query_one("#clock", Static).update(g)

    def draw_global(self) -> None:
        pct = D.overall_progress(self.state) * 100
        rows = D.phases(self.state)
        done = len([p for p in rows if p.status == "done"])
        eta = D.eta_seconds(self.state)
        caption = Text()
        caption.append("Overall  ", style="bold")
        caption.append(f"{done}/{len(rows) or '?'} phases done · {pct:.0f}%")
        if eta:
            caption.append(f" · ≈{D.hms(eta)} left", style="dim")
        self.query_one("#global-caption", Static).update(caption)
        self.query_one("#global-bar", ProgressBar).update(total=100, progress=pct)

    # ---- actions ---------------------------------------------------------------
    def action_stop(self) -> None:
        if not D.process_alive():
            self.notify("nothing is running", severity="warning")
            return
        AD.mkdir(parents=True, exist_ok=True)
        STOP_FILE.touch()
        self.notify("STOP written — the run stops after the session it is in", timeout=8)

    def action_resume(self) -> None:
        if D.process_alive():
            self.notify("already running", severity="warning")
            return
        if not STATE_FILE.exists():
            self.notify("no run in this directory to resume", severity="error")
            return

        def go(ok: "bool | None") -> None:
            if ok:
                self.notify(resume_run(), timeout=8)
                self.stamp = -1.0
        self.push_screen(ConfirmScreen("Resume the run? It starts sessions, spends usage and commits."), go)

    def action_log(self) -> None:
        self.push_screen(LogScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = {"stop": self.action_stop, "resume": self.action_resume, "log": self.action_log}.get(event.button.id)
        if action:          # buttons that live on a modal screen are not ours to act on
            action()


def main(light: bool = False) -> int:
    Dashboard(light=light).run()
    return 0
