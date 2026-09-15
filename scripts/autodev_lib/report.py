"""The run's own numbers, as a spreadsheet: time, tokens per model, cost per step and per phase.

Written by the orchestrator from `state.json`, so it costs nothing and needs no session. `openpyxl`
turns it into `.autodev/REPORT.xlsx` with charts; without it the same table lands in
`.autodev/REPORT.csv`, which is the raw data everything else in the workbook is derived from.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

PHASE_LABEL = re.compile(r"^p(\d\d)-")


def step_of(label: str) -> str:
    """`p04-review_fix2` → `review_fix`; `architect` → `architect`."""
    return re.sub(r"\d+$", "", PHASE_LABEL.sub("", label))


def phase_of(label: str) -> str:
    m = PHASE_LABEL.match(label)
    return f"phase {int(m.group(1))}" if m else "run-level"


def wall_clock_h(state: dict) -> float:
    try:
        started = datetime.strptime(state["created"], "%Y-%m-%d %H:%M:%S").timestamp()
    except (KeyError, TypeError, ValueError):
        return 0.0
    last = state.get("events") or [{}]
    try:
        ended = datetime.strptime(last[-1]["ts"], "%Y-%m-%d %H:%M:%S").timestamp()
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0
    return max(ended - started, 0) / 3600


def group(sessions: list, key) -> dict:
    out: dict = {}
    for s in sessions:
        row = out.setdefault(key(s), {"n": 0, "cost": 0.0, "sec": 0, "cache_r": 0, "out": 0, "turns": 0})
        row["n"] += 1
        for k in ("cost", "sec", "cache_r", "out", "turns"):
            row[k] += s.get(k, 0) or 0
    return out


def sessions_from_logs(logs: Path) -> list:
    """The same per-session rows, recovered from the raw stream logs.

    A run that started before the orchestrator kept these in `state.json` still has every number in
    `.autodev/logs/NNN-<step>.jsonl` — one `result` event at the end of each. Slower (those files are
    megabytes), which is why it is the fallback and not the source."""
    rows = []
    for f in sorted(logs.glob("*.jsonl")):
        if "-" not in f.stem:
            continue
        idx, label = f.stem.split("-", 1)
        last = None
        try:
            with open(f, errors="ignore") as fh:
                for line in fh:
                    if '"result"' not in line:      # cheap prefilter: these files are megabytes
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(ev, dict) and ev.get("type") == "result":
                        last = ev
        except OSError:
            continue
        row = {"n": int(idx) if idx.isdigit() else len(rows) + 1, "label": label, "model": "",
               "turns": 0, "sec": 0, "cost": 0.0, "error": "no result",
               "in": 0, "cache_w": 0, "cache_r": 0, "out": 0, "think": 0}
        if last:
            usage = last.get("modelUsage") or {}
            main = max(usage, key=lambda m: usage[m].get("costUSD", 0), default="")
            row.update(model=main.replace("claude-", ""), turns=last.get("num_turns") or 0,
                       sec=round((last.get("duration_ms") or 0) / 1000),
                       cost=round(float(last.get("total_cost_usd") or 0), 4),
                       error=last.get("subtype", "") if last.get("is_error") else "")
            fields = (("inputTokens", "in"), ("cacheCreationInputTokens", "cache_w"),
                      ("cacheReadInputTokens", "cache_r"), ("outputTokens", "out"),
                      ("thinkingTokens", "think"))
            for long, short in fields:
                row[short] = sum(int(u.get(long) or 0) for u in usage.values())
            # a session can bill more than one model (the small one Claude Code uses for itself),
            # and the per-model sheet should show that split rather than the session's main model
            row["by_model"] = {name.replace("claude-", ""):
                               dict({short: int(u.get(long) or 0) for long, short in fields},
                                    cost=round(float(u.get("costUSD") or 0), 4))
                               for name, u in usage.items()}
        rows.append(row)
    return rows


def models_from_sessions(sessions: list) -> dict:
    """The per-model totals, from each session's own split when it has one."""
    out: dict = {}
    for s in sessions:
        split = s.get("by_model") or {s.get("model") or "unknown":
                                      {k: s.get(k) or 0 for k in ("in", "cache_w", "cache_r", "out", "think")}
                                      | {"cost": s.get("cost") or 0}}
        for name, u in split.items():
            per = out.setdefault(name, {"sessions": 0, "cost": 0.0})
            per["sessions"] += 1
            per["cost"] = round(per["cost"] + (u.get("cost") or 0), 4)
            for k in ("in", "cache_w", "cache_r", "out", "think"):
                per[k] = per.get(k, 0) + (u.get(k) or 0)
    return out


def summary_rows(state: dict) -> list:
    tot = state.get("totals") or {}
    sessions = state.get("sessions") or []
    wall = wall_clock_h(state)
    working = tot.get("seconds", 0) / 3600
    paused = float(tot.get("paused") or 0) / 3600
    phases = state.get("phases") or []
    return [("Status", state.get("status", "")),
            ("Spec", state.get("spec", "")),
            ("Branch", state.get("branch") or ""),
            ("Phases done", sum(1 for p in phases if p.get("status") == "done")),
            ("Phases total", len(phases)),
            ("Sessions", tot.get("sessions", len(sessions))),
            ("Agent time, h", round(working, 2)),
            ("Wall clock, h", round(wall, 2)),
            ("Paused on usage limit, h", round(paused, 2)),
            ("Not running, h", round(max(wall - working - paused, 0), 2)),
            ("Cost, $ (API-equivalent)", round(tot.get("cost_usd", 0), 2)),
            ("Cache-read tokens", sum(s.get("cache_r", 0) for s in sessions)),
            ("Cache-write tokens", sum(s.get("cache_w", 0) for s in sessions)),
            ("Output tokens", sum(s.get("out", 0) for s in sessions)),
            ("Warnings on phases", sum(len(p.get("warnings") or []) for p in phases)),
            ("Run warnings", len(state.get("run_warnings") or []))]


def write_csv(state: dict, path: Path) -> Path:
    sessions = state.get("sessions") or []
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for k, v in summary_rows(state):
            w.writerow([k, v])
        w.writerow([])
        cols = ["n", "label", "step", "phase", "model", "turns", "in", "cache_w", "cache_r", "out",
                 "think", "sec", "cost", "error"]
        w.writerow(cols)
        for s in sessions:
            row = dict(s, step=step_of(s.get("label", "")), phase=phase_of(s.get("label", "")))
            w.writerow([row.get(c, "") for c in cols])
    return path


def write_xlsx(state: dict, path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference, ScatterChart, Series
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F4858")
    title_font = Font(bold=True, size=13)
    sessions = state.get("sessions") or []
    tot = state.get("totals") or {}

    def head(ws, row, cells, widths=()):
        for i, v in enumerate(cells, 1):
            c = ws.cell(row=row, column=i, value=v)
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        for i, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

    def table(ws, first_row, rows):
        for r, values in enumerate(rows, first_row):
            for c, v in enumerate(values, 1):
                ws.cell(row=r, column=c, value=v)
        return first_row + len(rows) - 1

    def bar(ws, title, data_col, last, anchor, cats_col=1, kind="col", size=(9, 13), legend=True):
        ch = BarChart()
        ch.title, ch.type = title, kind
        ch.add_data(Reference(ws, min_col=data_col, min_row=data_col and 3, max_row=last), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=cats_col, min_row=4, max_row=last))
        ch.height, ch.width = size
        if not legend:
            ch.legend = None
        ws.add_chart(ch, anchor)

    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"autodev run — {(state.get('project') or {}).get('name') or state.get('branch') or ''}"
    ws["A1"].font = title_font
    head(ws, 3, ["Metric", "Value", "", "Part of the wall clock", "Hours"], (34, 46, 4, 28, 10))
    working = tot.get("seconds", 0) / 3600
    paused = float(tot.get("paused") or 0) / 3600
    clock = [["Working", round(working, 2)],
             ["Paused on the usage limit", round(paused, 2)],
             ["Not running", round(max(wall_clock_h(state) - working - paused, 0), 2)]]
    for r, (metric, value) in enumerate(summary_rows(state), 4):
        ws.cell(row=r, column=1, value=metric)
        ws.cell(row=r, column=2, value=value)
    table(ws, 4, [["", "", "", k, v] for k, v in clock])
    pie = PieChart()
    pie.title = "Where the wall clock went"
    pie.add_data(Reference(ws, min_col=5, min_row=3, max_row=6), titles_from_data=True)
    pie.set_categories(Reference(ws, min_col=4, min_row=4, max_row=6))
    pie.height, pie.width = 8, 14
    ws.add_chart(pie, "D9")

    ws = wb.create_sheet("By model")
    ws["A1"] = "Tokens and cost per model"
    ws["A1"].font = title_font
    head(ws, 3, ["Model", "Sessions", "Input", "Cache write", "Cache read", "Output", "Thinking", "Cost $"],
         (30, 10, 12, 13, 15, 12, 12, 10))
    models = sorted((tot.get("models") or models_from_sessions(sessions)).items(),
                    key=lambda kv: -kv[1].get("cost", 0))
    last = table(ws, 4, [[m, c.get("sessions", 0), c.get("in", 0), c.get("cache_w", 0), c.get("cache_r", 0),
                          c.get("out", 0), c.get("think", 0), round(c.get("cost", 0), 2)] for m, c in models])
    if models:
        bar(ws, "Cost by model, $", 8, last, "A10", size=(8, 12), legend=False)
        ch = BarChart()
        ch.title, ch.type = "Tokens by model (log scale)", "col"
        ch.add_data(Reference(ws, min_col=4, max_col=6, min_row=3, max_row=last), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=4, max_row=last))
        ch.y_axis.scaling.logBase = 10
        ch.height, ch.width = 8, 18
        ws.add_chart(ch, "J10")

    ws = wb.create_sheet("By step")
    ws["A1"] = "Cost and time per step type"
    ws["A1"].font = title_font
    head(ws, 3, ["Step", "Sessions", "Cost $", "Agent hours", "Share of cost"], (16, 10, 10, 12, 14))
    steps = sorted(group(sessions, lambda s: step_of(s.get("label", ""))).items(), key=lambda kv: -kv[1]["cost"])
    spend = sum(v["cost"] for _, v in steps) or 1
    last = table(ws, 4, [[s, c["n"], round(c["cost"], 2), round(c["sec"] / 3600, 2), c["cost"] / spend]
                         for s, c in steps])
    for r in range(4, last + 1):
        ws.cell(row=r, column=5).number_format = "0.0%"
    if steps:
        bar(ws, "Cost by step, $", 3, last, "A14", kind="bar", size=(9, 12), legend=False)
        pie = PieChart()
        pie.title = "Share of spend"
        pie.add_data(Reference(ws, min_col=3, min_row=3, max_row=last), titles_from_data=True)
        pie.set_categories(Reference(ws, min_col=1, min_row=4, max_row=last))
        pie.height, pie.width = 9, 12
        ws.add_chart(pie, "J14")

    ws = wb.create_sheet("By phase")
    ws["A1"] = "Cost, time and context re-reads per phase"
    ws["A1"].font = title_font
    head(ws, 3, ["Phase", "Sessions", "Cost $", "Agent hours", "Cache read, M tokens", "Warnings"],
         (12, 10, 10, 12, 20, 10))
    warn = {f"phase {i + 1}": len(p.get("warnings") or []) for i, p in enumerate(state.get("phases") or [])}
    phases = sorted(group(sessions, lambda s: phase_of(s.get("label", ""))).items(),
                    key=lambda kv: (kv[0] == "run-level", kv[0]))
    last = table(ws, 4, [[p, c["n"], round(c["cost"], 2), round(c["sec"] / 3600, 2),
                          round(c["cache_r"] / 1e6, 1), warn.get(p, "")] for p, c in phases])
    if phases:
        ch = BarChart()
        ch.title, ch.type = "Cost and agent hours per phase", "col"
        ch.add_data(Reference(ws, min_col=3, max_col=4, min_row=3, max_row=last), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=4, max_row=last))
        ch.height, ch.width = 9, 18
        ws.add_chart(ch, "A14")
        bar(ws, "Cache read per phase, million tokens", 5, last, "A33", size=(9, 14), legend=False)

    ws = wb.create_sheet("Sessions")
    ws["A1"] = "Every session of the run, in order"
    ws["A1"].font = title_font
    head(ws, 3, ["#", "Step", "Phase", "Model", "Turns", "Cache read", "Cache write", "Output",
                 "Minutes", "Cost $", "Note"], (5, 20, 12, 10, 8, 14, 13, 11, 10, 9, 26))
    last = table(ws, 4, [[s.get("n"), s.get("label"), phase_of(s.get("label", "")), s.get("model"),
                          s.get("turns"), s.get("cache_r"), s.get("cache_w"), s.get("out"),
                          round((s.get("sec") or 0) / 60, 1), round(s.get("cost") or 0, 2), s.get("error", "")]
                         for s in sessions])
    ws.freeze_panes = "A4"
    if sessions:
        ch = LineChart()
        ch.title, ch.legend = "Cost per session, $", None
        ch.add_data(Reference(ws, min_col=10, min_row=3, max_row=last), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=4, max_row=last))
        ch.height, ch.width = 8, 24
        ws.add_chart(ch, "M4")
        sc = ScatterChart()
        sc.title = "Turns vs cache read — why a long session costs so much"
        sc.x_axis.title, sc.y_axis.title, sc.legend = "turns", "cache read (tokens)", None
        sc.series.append(Series(Reference(ws, min_col=6, min_row=4, max_row=last),
                                Reference(ws, min_col=5, min_row=4, max_row=last)))
        sc.series[0].marker.symbol = "circle"
        sc.series[0].graphicalProperties.line.noFill = True
        sc.height, sc.width = 10, 24
        ws.add_chart(sc, "M22")

    ws = wb.create_sheet("Budget model")
    ws["A1"] = "Estimating the next run from this one"
    ws["A1"].font = title_font
    done = [p for p in (state.get("phases") or []) if p.get("status") == "done"] or (state.get("phases") or [])
    per_phase = [round(c["cost"], 2) for p, c in phases if p != "run-level"]
    lo = min(per_phase) if per_phase else 0
    hi = max(per_phase) if per_phase else 0
    run_level = next((round(c["cost"], 2) for p, c in phases if p == "run-level"), 0)
    hours = [round(c["sec"] / 3600, 2) for p, c in phases if p != "run-level"]
    wall = wall_clock_h(state)
    head(ws, 3, ["Input", "Low", "High", "Where the number comes from"], (44, 12, 12, 54))
    table(ws, 4, [
        ["Phases in the roadmap", max(len(done), 1), max(len(done), 1), "this run; change it for the next spec"],
        ["Cost per phase, $", lo, hi, "measured on this run"],
        ["Agent hours per phase", min(hours) if hours else 0, max(hours) if hours else 0, "measured on this run"],
        ["Run-level steps (architect, roadmap, finalize), $", run_level, run_level, "one of each, per run"],
        ["Wall-clock multiplier", round(wall / working, 2) if working else 1.0,
         round(wall / working, 2) if working else 1.0, "usage pauses and restarts, measured"]])
    head(ws, 10, ["Estimate", "Low", "High", "Formula"], (44, 12, 12, 54))
    table(ws, 11, [["Cost, $", "=B4*B5+B7", "=C4*C5+C7", "phases × per-phase + run-level"],
                   ["Agent time, h", "=B4*B6", "=C4*C6", "phases × per-phase hours"],
                   ["Wall clock, h", "=B11*B8", "=C11*C8", "agent time × multiplier"]])
    ws["A15"] = "Measured on this run"
    ws["A15"].font = title_font
    table(ws, 16, [["Phases", len(done)], ["Cost, $", round(tot.get("cost_usd", 0), 2)],
                   ["Agent time, h", round(working, 2)], ["Wall clock, h", round(wall, 2)]])

    wb.save(path)
    return path


def write(state: dict, path: Path, logs: Path | None = None) -> tuple[Path | None, str]:
    """Write the report next to the run. Returns (path, note) — the note is for the log."""
    if not (state.get("sessions") or []) and logs and logs.is_dir():
        state = dict(state, sessions=sessions_from_logs(logs))
        totals = dict(state.get("totals") or {})
        totals.setdefault("models", {}) or totals.update(models=models_from_sessions(state["sessions"]))
        state["totals"] = totals
    if not (state.get("sessions") or []):
        return None, "no sessions to report on yet"
    try:
        return write_xlsx(state, path), ""
    except ImportError:
        csv_path = path.with_suffix(".csv")
        return write_csv(state, csv_path), ("openpyxl is not installed, so the run report is a CSV "
                                            f"({csv_path.as_posix()}); `pip install openpyxl` for the workbook")
