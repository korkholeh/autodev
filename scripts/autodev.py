#!/usr/bin/env python3
"""
autodev.py — unattended, phase-by-phase development orchestrator for Claude Code.

Every LLM step (roadmap, phase plan, implement, test-fix, review, review-fix) is a
separate headless `claude -p` session with a fresh context. Tests, git commits and
progress tracking are done deterministically by this script. The run pauses when the
5-hour usage window crosses a threshold and resumes after the reset.

  autodev.py doctor --spec SPEC        pre-flight checks
  autodev.py run    --spec SPEC [...]  start (or resume) a run in the current repo
  autodev.py status                    short status of the run in the current repo

GitHub: `--gh-user LOGIN` commits and pushes as that gh account (token via `gh auth token --user`,
never switching gh's active account); `--pr` keeps a draft PR with PROGRESS.md as its body.

Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:              # so autodev_lib imports whether run or imported
    sys.path.insert(0, str(_HERE))

from autodev_lib.commands import CMD_CORRECTION, CMD_FIELDS, command_allowed  # noqa: E402
from autodev_lib.github import GitHub  # noqa: E402
from autodev_lib.staging import COMMAND_FILES, why_not_committable  # noqa: E402
from autodev_lib.usage import RESET_BUFFER_S, UsageGuard  # noqa: E402
from autodev_lib.util import (AD, GUIDES_DIR, PID_FILE, PROFILES_DIR, STATE_FILE,  # noqa: E402
                              STOP_FILE, SURFACE_LOG, StepFailed, StopRequested, atomic_write,
                              available_profiles, bullets, child_env, claude_flags, claude_version,
                              detect_profile, extract_json, git, hm, log, one_line, render,
                              set_log_path, slugify, ts, unchecked_tasks)

PERMISSION_PROMPTS_MIN = (2, 1, 259)  # first version with --permission-prompts none
BLOCKING = {"blocker", "major"}

DEFAULTS = {
    "test_cmd": "",
    "threshold": 85.0,
    "weekly_threshold": 97.0,
    "model_plan": "opus",
    "model_impl": "sonnet",
    "model_review": "opus",
    "model_qa": "sonnet",
    "permission_mode": "auto",
    "max_test_fix": 3,
    "max_review_rounds": 2,
    "max_impl_runs": 3,
    "max_e2e_fix": 3,
    "max_hours": 0.0,        # stop the run after this much wall clock (0 = no ceiling)
    "max_sessions": 0,       # stop after this many sessions started in this run (0 = no ceiling)
    # stack profile + end-to-end + documentation
    "profile": "",           # name of a file in profiles/ (architect corrects it into .autodev/PROFILE.md)
    "e2e": "auto",           # auto = run the e2e step on user-facing phases; off = never
    "e2e_cmd": "",           # the end-to-end suite (the e2e step fills it in when empty)
    "e2e_up_cmd": "",        # starts the surfaces the suite attaches to ('-' = nothing to start)
    "e2e_down_cmd": "",      # stops them again
    "e2e_ready_url": "",     # polled until it answers before the suite runs
    "e2e_timeout": 45,       # minutes
    "docs": True,            # per-phase documentation step
    "finalize": True,        # closing documentation + handoff session
    "session_timeout": 180,  # minutes
    "test_timeout": 30,      # minutes
    "poll_interval": 300,    # seconds between usage API polls during a session
    "notify_cmd": "",
    "lang": "English",
    "branch": True,
    "caffeinate": True,
    "claude_bin": "claude",
    "allow_cmd": [],        # extra head binaries a session may propose in a command
    "web": "off",           # on = sessions may use WebFetch/WebSearch
    "mcp_config": [],       # MCP server definitions to give the sessions (files or JSON strings)
    "inherit_mcp": False,   # True = let the sessions see the user's own MCP servers too
    "allow_no_verify": False,   # True = commit past a failing git hook instead of stopping
    "max_file_mb": 5,       # a staged file larger than this is held back (0 = no limit)
    # git / GitHub
    "gh_user": "",        # gh account login to commit & push as
    "gh_host": "github.com",
    "gh_repo": "",        # owner/name override (default: parsed from the remote URL)
    "remote": "origin",
    "git_name": "",       # override commit author name (default: GitHub profile name)
    "git_email": "",      # override commit email (default: <id>+<login>@users.noreply.github.com)
    "push": "auto",       # phase | end | never; auto = phase when gh_user is set, else never
    "pr": False,          # create/update a draft PR (requires gh_user)
}

ARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "partial", "blocked"]},
        "summary": {"type": "string"},
        "stack": {"type": "string"},
        "test_command": {"type": "string"},
        "lint_command": {"type": "string"},
        "e2e_command": {"type": "string"},
        "e2e_up_command": {"type": "string"},
        "e2e_down_command": {"type": "string"},
        "adrs": {"type": "array", "items": {"type": "string"}},
        "top_risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "stack"],
}
E2E_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "partial", "blocked"]},
        "summary": {"type": "string"},
        "e2e_command": {"type": "string"},
        "e2e_up_command": {"type": "string"},
        "e2e_down_command": {"type": "string"},
    },
    "required": ["status", "summary"],
}
STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "partial", "blocked"]},
        "summary": {"type": "string"},
        "remaining_tasks": {"type": "integer"},
        "test_command": {"type": "string"},
    },
    "required": ["status", "summary"],
}
ROADMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "project_name": {"type": "string"},
        "summary": {"type": "string"},
        "test_command": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "phases": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "slug": {"type": "string"},
                    "goal": {"type": "string"},
                    "deliverables": {"type": "array", "items": {"type": "string"}},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "user_facing": {"type": "boolean"},
                },
                "required": ["title", "slug", "goal", "deliverables", "acceptance_criteria"],
            },
        },
    },
    "required": ["summary", "test_command", "phases"],
}
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "changes_requested"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["blocker", "major", "minor", "nit"]},
                    "file": {"type": "string"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                },
                "required": ["severity", "title", "detail"],
            },
        },
    },
    "required": ["verdict", "summary", "findings"],
}

RESUME_AFTER_LIMIT = ("The usage-limit window has reset. Continue exactly where you left off in the same step. "
                      "When the step is complete, return the required structured output.")
RESUME_AFTER_RESTART = ("The orchestrator was restarted while you were working on this step. Check the current "
                        "state of the files (git status, PLAN.md checkboxes) and continue the step to completion. "
                        "Then return the required structured output.")
NUDGE = ("Autonomous mode: no human is available. If you asked a question or offered options, choose the "
         "recommended option (or the first one), append the decision to .autodev/DECISIONS.md and continue the "
         "step to completion. Then return the required structured output.")


# ------------------------------------------------------------------- whose run is this anyway
# The state file names the commands the orchestrator runs and the branch it pushes. A repository
# can carry a `.autodev/` of its own, so a run is claimed by a marker kept outside the repository,
# where nothing that arrives with a clone can write it.
def run_marker() -> Path:
    home = Path(os.environ.get("AUTODEV_HOME") or Path.home() / ".autodev")
    key = hashlib.sha256(str(Path.cwd().resolve()).encode()).hexdigest()[:16]
    return home / "runs" / f"{key}.json"


def current_branch_or_fail() -> str:
    """The branch the run starts from, refusing a detached HEAD.

    On a detached HEAD `rev-parse --abbrev-ref` answers "HEAD", which would become the run's base
    branch: nothing to return to, and a pull request opened against it fails hours into the run."""
    cur = git("rev-parse", "--abbrev-ref", "HEAD")
    if cur == "HEAD":
        raise StepFailed("this repository is on a detached HEAD, so the run has no base branch to come back "
                         "to, and a pull request opened against 'HEAD' would only fail hours from now. "
                         "Check out a branch first: git switch -c <name>")
    return cur


def kill_group(proc: subprocess.Popen, sig=signal.SIGKILL) -> None:
    """Signal a child's whole process group, falling back to the child alone.

    Sessions and shell commands are started with `start_new_session=True`, so the child leads its own
    group and everything it spawned is in it."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def claim_run(run_id: str) -> None:
    """Record on this machine that the run in this directory is ours."""
    atomic_write(run_marker(), json.dumps(
        {"run_id": run_id, "path": str(Path.cwd().resolve()), "claimed": ts()}, indent=2))


def owns_run(run_id: str) -> bool:
    try:
        return bool(run_id) and json.loads(run_marker().read_text()).get("run_id") == run_id
    except (OSError, ValueError):
        return False


def ensure_run_is_ours(state: dict, adopt: bool) -> None:
    """Refuse to resume a run this machine did not start, unless told to adopt it."""
    if owns_run(state.get("run_id") or ""):
        return
    if adopt:
        claim_run(state.setdefault("run_id", secrets.token_hex(16)))
        log("adopted the run state already in .autodev/ (--adopt)")
        return
    raise StepFailed(
        "the run state in .autodev/ was not started on this machine — it may have arrived with the "
        "repository. It names the commands the orchestrator runs and the branch it pushes, so it is "
        "not resumed on trust.\n"
        "  start over:            run --spec <spec> --fresh\n"
        "  adopt it deliberately: run --adopt (after reading .autodev/state.json)")


# ----------------------------------------------------------------------------- orchestrator
PHASE_STEPS = {         # phase step -> the Orchestrator method that runs it and names the next step
    "plan": "_plan", "implement": "_implement", "test": "_test", "test_fix": "_test_fix",
    "review": "_review", "review_fix": "_review_fix", "e2e": "_e2e", "e2e_fix": "_e2e_fix",
    "docs": "_docs", "commit": "_commit",
}


class PhaseRun:
    """Everything a phase step works with, assembled once per step."""

    def __init__(self, orch: "Orchestrator", i: int):
        st, proj = orch.state, orch.state["project"]
        self.i, self.n, self.total = i, i + 1, len(st["phases"])
        self.ph = st["phases"][i]
        self.ctx = st.setdefault("phase_ctx", {})
        self.step = st["step"]
        self.label = f"p{self.n:02d}-{self.step}"
        self.dir = orch.phase_dir(i)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.common = dict(
            n=self.n, total=self.total, title=self.ph["title"], goal=self.ph["goal"],
            deliverables=bullets(self.ph["deliverables"]), acceptance=bullets(self.ph["acceptance_criteria"]),
            spec=st["spec"], phase_dir=self.dir.as_posix(), lang=orch.cfg["lang"],
            test_command=proj.get("test_command") or "(none configured)",
            e2e_command=orch.e2e_command() or "(not created yet — build the harness)",
            e2e_up_command=proj.get("e2e_up_command") or "(nothing to start)",
            base_sha=self.ctx.get("base_sha", ""),
            user_facing="yes" if self.ph.get("user_facing", True) else "no")


class Orchestrator:
    def __init__(self, state: dict):
        self.state = state
        self.cfg = state["config"]
        self.guard = UsageGuard(self.cfg["threshold"], self.cfg["weekly_threshold"])
        self.child: subprocess.Popen | None = None
        self.surface_proc: subprocess.Popen | None = None
        self.stop_flag = False
        self.supports_prompts_none = False
        self.claude_flags: set = set()
        self.held_back: list = []
        self.run_started = 0.0
        self.sessions_this_run = 0
        self.autonomy = ""
        self.github: GitHub | None = None
        self.push_mode = "never"

    # ---- persistence -------------------------------------------------------
    def save(self) -> None:
        atomic_write(STATE_FILE, json.dumps(self.state, indent=2, ensure_ascii=False))
        self.render_progress()

    def set_step(self, step: str) -> None:
        self.state["step"] = step
        self.save()

    def event(self, label, status, summary="", seconds=None, cost=None) -> None:
        self.state["events"].append({"ts": ts(), "label": label, "status": status, "summary": one_line(summary),
                                     "seconds": seconds, "cost": cost})
        log(f"{label}: {status} — {one_line(summary, 200)}")
        self.save()

    def notify(self, msg: str) -> None:
        if not self.cfg.get("notify_cmd"):
            return
        try:
            subprocess.run(self.cfg["notify_cmd"], shell=True, timeout=30, capture_output=True,
                           env={**os.environ, "AUTODEV_MSG": msg})
        except Exception as e:  # noqa: BLE001
            log(f"WARN notify failed: {e}")

    def require_test_command(self, where: str) -> None:
        """Stop rather than run all night certifying nothing.

        With no test command `run_tests` reports every phase as passing without running anything,
        so the whole branch would be committed, reviewed and documented unverified. Better to fail
        here, minutes after launch, while somebody may still be awake."""
        if (self.state.get("project") or {}).get("test_command", "").strip():
            return
        raise StepFailed(
            f"{where} left no usable test command, so no phase would ever be verified. Pass "
            "--test-cmd '<command>' and run the same command again to resume — a command you pass "
            "is used as typed and never vetted. If a session proposed one and it was refused, the "
            "reason is in the log and in .autodev/DECISIONS.md, and --allow-cmd <binary> accepts "
            "that binary.")

    def warn_run(self, line: str) -> None:
        """A warning about the run itself, not about one phase.

        Phase warnings ride along in the phase row of PROGRESS.md, which is the right place for
        anything a phase did. The architect, roadmap and finalize steps have no phase to belong to,
        so their warnings would otherwise live only in the timeline — or be pinned on whichever
        phase committed next."""
        self.state.setdefault("run_warnings", []).append(f"{ts()} — {line}")

    def record_decision(self, line: str) -> None:
        """Append a line to DECISIONS.md the same way the sessions do, so a human reads one list."""
        try:
            with open(AD / "DECISIONS.md", "a", encoding="utf-8") as f:
                f.write(f"- [orchestrator/{self.state.get('step', '?')}] {line}\n")
        except OSError as e:
            log(f"WARN could not append to DECISIONS.md: {e}")

    def vet_command(self, field: str, proposed: str, current: str = "") -> str:
        """Take a command a session proposed only if it looks like a real toolchain command.

        The orchestrator shells out to these itself, so they never pass the permission classifier
        that guards a session's own Bash calls, and everything a session reads (the spec, a README,
        a fetched page) can try to talk it into proposing something else. A rejected command leaves
        the current one in place and is written to the log, the timeline and DECISIONS.md, never
        silently dropped. Commands the developer passed on the command line do not come through here.
        """
        proposed = (proposed or "").strip()
        current = (current or "").strip()
        if not proposed or proposed == current:
            return current
        if proposed == "-":                     # the sentinel for "nothing to run"
            return proposed
        ok, why = command_allowed(proposed, self.cfg.get("allow_cmd") or ())
        if not ok:
            log(f"WARN {field}: refused the command this session proposed ({why}): "
                f"{one_line(proposed, 200)}")
            log(f"     keeping `{current or '(none)'}` — set it yourself with the matching flag, or "
                f"allow its binary with --allow-cmd")
            self.event("command", "refused", f"{field} ({why}): {one_line(proposed, 160)}")
            self.record_decision(f"refused the proposed {field} `{one_line(proposed, 200)}` ({why}); "
                                 f"kept `{current or '(none)'}`")
            return current
        log(f"{field} → {proposed}")
        self.record_decision(f"{field} set to `{proposed}` by this session "
                             f"(was `{current or '(none)'}`)")
        return proposed

    def phase_dir(self, i: int) -> Path:
        ph = self.state["phases"][i]
        return AD / "phases" / f"{i + 1:02d}-{ph['slug']}"

    # ---- setup ---------------------------------------------------------------
    @staticmethod
    def acquire_lock() -> None:
        AD.mkdir(parents=True, exist_ok=True)
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                if pid != os.getpid():
                    os.kill(pid, 0)
                    sys.exit(f"autodev is already running in this repo (pid {pid})")
            except (ValueError, ProcessLookupError, PermissionError):
                pass
        PID_FILE.write_text(str(os.getpid()))

    def setup(self) -> None:
        (AD / "logs").mkdir(parents=True, exist_ok=True)
        set_log_path(AD / "autodev.log")

        (AD / ".gitignore").write_text("logs/\nguides/\nstate.json\nstate.json.tmp\nrun.pid\nSTOP\n"
                                       "autodev.log\nconsole.log\n")
        self.install_guides()
        dec = AD / "DECISIONS.md"
        if not dec.exists():
            dec.write_text("# Decisions & assumptions (autonomous run)\n\n"
                           "Appended by agents whenever they choose between options without a human.\n\n")

        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        if self.cfg.get("caffeinate") and sys.platform == "darwin" and shutil.which("caffeinate"):
            subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("caffeinate: macOS idle/system sleep prevented while running")

        ver = claude_version(self.cfg["claude_bin"])
        if ver is None:
            raise StepFailed(f"`{self.cfg['claude_bin']} --version` failed — is Claude Code installed?")
        self.supports_prompts_none = ver >= PERMISSION_PROMPTS_MIN
        self.claude_flags = claude_flags(self.cfg["claude_bin"])
        log("sessions: "
            + ("user MCP servers inherited" if self.cfg.get("inherit_mcp") else "no inherited MCP servers")
            + (", web on" if self.cfg.get("web") == "on" else ", no web access")
            + ", AUTODEV_* stripped from the environment")
        if not self.supports_prompts_none:
            log(f"WARN Claude Code {'.'.join(map(str, ver))} < 2.1.259: no --permission-prompts none; "
                "relying on --disallowedTools AskUserQuestion + prompt rules")
        self.autonomy = render("_autonomy", lang=self.cfg["lang"])

        st, cfg = self.state, self.cfg
        if cfg.get("gh_user"):
            try:
                self.github = GitHub(cfg["gh_user"], cfg["gh_host"], cfg["gh_repo"], cfg["remote"]).connect()
            except RuntimeError as e:
                raise StepFailed(f"GitHub: {e}") from None
        name = cfg.get("git_name") or (self.github.name if self.github else "")
        email = cfg.get("git_email") or (self.github.email if self.github else "")
        if self.github and not email:
            raise StepFailed(f"cannot derive a commit email for {cfg['gh_host']}; pass --git-email")
        if name:
            os.environ["GIT_AUTHOR_NAME"] = os.environ["GIT_COMMITTER_NAME"] = name
        if email:
            os.environ["GIT_AUTHOR_EMAIL"] = os.environ["GIT_COMMITTER_EMAIL"] = email
        if name or email:
            log(f"git identity: {name or '(git config)'} <{email or '(git config)'}>")

        if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode != 0:
            log("not a git repo — running git init")
            git("init", "-q")
        if subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True).returncode != 0:
            git("commit", "-q", "--allow-empty", "-m", "autodev: initial commit")
        if not st.get("branch"):
            cur = current_branch_or_fail()
            st["base_branch"] = cur
            if self.cfg.get("branch") and not cur.startswith("autodev/"):
                cur = f"autodev/{slugify(Path(st['spec']).stem)}-{datetime.now():%Y%m%d-%H%M}"
                git("checkout", "-q", "-b", cur)
            st["branch"] = cur
            git("add", "-A")
            if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
                git("commit", "-q", "-m", "autodev: snapshot before autonomous run")
                log("committed pre-run snapshot of uncommitted changes")
        else:
            self.ensure_on_branch(st["branch"])

        st.setdefault("run_base_sha", git("rev-parse", "HEAD"))
        self.push_mode = cfg.get("push") or "auto"
        if self.push_mode == "auto":
            self.push_mode = "phase" if self.github else "never"
        if self.github:
            repo = self.github.resolve_repo()
            if not repo:
                log(f"WARN GitHub: no {cfg['gh_host']} repo (remote '{cfg['remote']}' missing/not GitHub, no --gh-repo) "
                    "— push/PR disabled")
                self.push_mode = "never"
            elif not self.github.can_push:
                log(f"WARN GitHub: {self.github.login} has no push permission to {repo} — push/PR disabled")
                self.push_mode = "never"
            else:
                log(f"GitHub: acting as {self.github.login} → {repo} (push: {self.push_mode}"
                    + (", draft PR" if cfg.get("pr") else "") + ")")
        st["status"] = "running"
        st.pop("error", None)
        self.save()

    def ensure_on_branch(self, branch: str) -> None:
        """Put a resumed run back on its own branch before it commits anything.

        A run that paused overnight is continued by the same command in the morning, in a repository
        the developer may have used in between. Nothing else looks: `git add -A` and the phase commit
        would land wherever HEAD happens to be, the phase tag would point there, and the push would
        send that to the run's branch."""
        cur = git("rev-parse", "--abbrev-ref", "HEAD", check=False)
        if cur == branch:
            return
        where = f"branch {cur}" if cur and cur != "HEAD" else "a detached HEAD"
        if not git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False):
            raise StepFailed(f"the branch this run works on (`{branch}`) no longer exists in this "
                             f"repository, and HEAD is on {where}. Restore the branch, or start over "
                             "with --fresh.")
        dirty = [ln for ln in git("status", "--porcelain", check=False).splitlines()
                 if ln.strip() and not ln[3:].lstrip('"').startswith(".autodev/")]
        if dirty:
            raise StepFailed(
                f"this run works on `{branch}`, but HEAD is on {where} with {len(dirty)} uncommitted "
                "change(s). Those are not the run's, so autodev does not move or commit them: deal "
                f"with them, check out `{branch}` yourself, and run the same command again.")
        git("checkout", "-q", branch)
        log(f"switched back to the run's branch {branch} (HEAD was on {where})")
        self.record_decision(f"resumed on {where}; checked out the run's branch `{branch}` again "
                             "before committing anything")

    def install_guides(self) -> None:
        """Copy the working guides and the chosen stack profile into .autodev/ for the sessions to read.

        Guides are refreshed every run (they belong to the tool). PROFILE.md is written once: the architect
        step corrects it against the real repository, and that version is the project's record."""
        dest = AD / "guides"
        dest.mkdir(parents=True, exist_ok=True)
        for f in sorted(GUIDES_DIR.glob("*.md")):
            shutil.copyfile(f, dest / f.name)
        prof_file = AD / "PROFILE.md"
        if not prof_file.exists():
            name = self.cfg.get("profile") or detect_profile()
            src = PROFILES_DIR / f"{name}.md"
            if not src.exists():
                log(f"WARN unknown profile '{name}' — falling back to generic "
                    f"(available: {', '.join(available_profiles())})")
                name, src = "generic", PROFILES_DIR / "generic.md"
            self.state["profile"] = name
            shutil.copyfile(src, prof_file)
            log(f"stack profile: {name} → {prof_file.as_posix()}")

    @staticmethod
    def guides_digest() -> dict:
        """Fingerprint of the tool-owned guides in `.autodev/guides/`.

        They are the instructions every session is handed, and nothing in a run is supposed to write
        them. They are gitignored, so the working-tree check below cannot see them."""
        out = {}
        for f in sorted((AD / "guides").glob("*.md")):
            try:
                out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                pass
        return out

    def check_guides(self, label: str, before: dict) -> None:
        """Put the guides back if the session rewrote them, and say so where a human will read it."""
        after = self.guides_digest()
        touched = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
        if not touched:
            return
        self.install_guides()
        self.warn_run(f"{label} changed .autodev/guides/ ({', '.join(touched)}) — restored from the skill")
        self.event(label, "guides restored", "session wrote .autodev/guides/: " + ", ".join(touched))
        self.record_decision(f"`{label}` changed the working guides ({', '.join(touched)}); they were "
                             "restored from the skill, so later sessions read the originals.")

    @staticmethod
    def worktree_marks() -> set:
        """What git sees as changed, `.autodev/` aside — the orchestrator writes there itself."""
        return {ln for ln in git("status", "--porcelain", "-uall", check=False).splitlines()
                if ln.strip() and not ln[3:].lstrip('"').startswith(".autodev/")}

    def _on_signal(self, signum, _frame):
        if self.stop_flag:
            if self.child and self.child.poll() is None:
                kill_group(self.child)
            raise SystemExit(130)
        self.stop_flag = True
        log(f"signal {signum}: stopping (interrupting the current session; send again to force)")

    def check_stop(self) -> None:
        if self.stop_flag:
            raise StopRequested("signal")
        if STOP_FILE.exists():
            STOP_FILE.unlink()
            raise StopRequested("STOP file")
        over = self.budget_exceeded()
        if over:
            raise StopRequested(over)

    def budget_deadline(self) -> float:
        """When `--max-hours` runs out, or 0 if there is no ceiling."""
        hours = float(self.cfg.get("max_hours") or 0)
        return self.run_started + hours * 3600 if hours and self.run_started else 0.0

    def budget_exceeded(self) -> str | None:
        """Why this run has to stop now, or None.

        The budget is per `run`: the usage guard only keeps the subscription happy, and without a
        ceiling a long roadmap can keep starting sessions for days. Resuming grants a new budget,
        which is the point — the developer decides to spend more."""
        deadline = self.budget_deadline()
        if deadline and time.time() >= deadline:
            return (f"--max-hours {float(self.cfg['max_hours']):g} reached "
                    f"({(time.time() - self.run_started) / 3600:.1f} h in this run)")
        cap = int(self.cfg.get("max_sessions") or 0)
        if cap and self.sessions_this_run >= cap:
            return f"--max-sessions {cap} reached"
        return None

    # ---- claude sessions -------------------------------------------------------
    def _interrupt(self, proc: subprocess.Popen) -> None:
        """Stop a session, gently first.

        The last step kills the whole process group: a session starts processes of its own — a test
        run, a dev server, a browser — and killing only `claude` leaves them holding their ports."""
        for sig, wait in ((signal.SIGINT, 90), (signal.SIGTERM, 30)):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                return
            try:
                proc.wait(timeout=wait)
                return
            except subprocess.TimeoutExpired:
                continue
        kill_group(proc)
        proc.wait()

    def session_command(self, prompt, model, schema, resume=None, extra_disallowed=()) -> list:
        """The argv for one headless session, including everything that fences it in.

        A session reads the spec, the repository and whatever those point at, so the fence matters:
        no question it could wait forever on, no MCP server the developer did not name, and by
        default no web access — that is the one channel that reaches outside the repository."""
        cfg = self.cfg
        cmd = [cfg["claude_bin"], "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--model", model, "--json-schema", json.dumps(schema), "--append-system-prompt", self.autonomy,
               "--permission-mode", "bypassPermissions" if cfg["permission_mode"] == "bypass" else "auto"]
        if self.supports_prompts_none:
            cmd += ["--permission-prompts", "none"]
        blocked = ["AskUserQuestion", "EnterPlanMode", "ExitPlanMode", *extra_disallowed]
        if cfg.get("web") != "on":
            blocked += ["WebFetch", "WebSearch"]
        cmd += ["--disallowedTools", ",".join(blocked)]
        if not cfg.get("inherit_mcp") and "--strict-mcp-config" in self.claude_flags:
            cmd += ["--strict-mcp-config"]
        for conf in cfg.get("mcp_config") or []:
            cmd += ["--mcp-config", conf]
        if resume:
            cmd += ["--resume", resume]
        return cmd

    def note_session(self, label: str, session_id: str) -> None:
        """Write the resume handle to state.json while the session is still running.

        It used to live in memory until the next save, so a SIGKILL or a power cut in the middle of a
        long session lost the handle and the step started again from nothing."""
        self.state["active_session"] = {"label": label, "session_id": session_id}
        self.save()

    def run_claude(self, label, prompt, model, schema, resume=None, extra_disallowed=()):
        cfg, st = self.cfg, self.state
        st["session_counter"] = st.get("session_counter", 0) + 1
        base = AD / "logs" / f"{st['session_counter']:03d}-{label}"
        cmd = self.session_command(prompt, model, schema, resume, extra_disallowed)

        out = {"session_id": resume, "result": None, "interrupted": None, "rejected": False,
               "exit": None, "budget": ""}
        started = time.time()
        log(f"▶ {label} [{model}]" + (f" resume {resume[:8]}" if resume else ""))
        with open(f"{base}.jsonl", "a", encoding="utf-8") as jf, open(f"{base}.stderr.log", "a") as ef:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, stdin=subprocess.DEVNULL, text=True,
                                    bufsize=1, env=child_env(), start_new_session=True)
            self.child = proc

            def reader():
                for line in proc.stdout:
                    jf.write(line)
                    jf.flush()
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    sid = ev.get("session_id")
                    if sid and out["session_id"] != sid:
                        out["session_id"] = sid      # the main loop writes it to disk (note_session)
                    t = ev.get("type")
                    if t == "rate_limit_event":
                        info = ev.get("rate_limit_info") or {}
                        self.guard.observe(info)
                        if info.get("status") == "rejected":
                            out["rejected"] = True
                    elif t == "result":
                        out["result"] = ev

            th = threading.Thread(target=reader, daemon=True)
            th.start()
            last_poll = time.time()
            noted = resume
            while proc.poll() is None:
                time.sleep(2)
                if out["session_id"] and out["session_id"] != noted:
                    noted = out["session_id"]        # saving is the main loop's job, not the reader's
                    self.note_session(label, noted)
                if proc.poll() is not None:
                    break
                if self.stop_flag:
                    out["interrupted"] = "stop"
                elif self.budget_exceeded():
                    out["budget"] = self.budget_exceeded() or "the run budget is spent"
                    out["interrupted"] = "budget"
                    log(f"{label}: {out['budget']} — interrupting the session to stop")
                elif time.time() - started > cfg["session_timeout"] * 60:
                    out["interrupted"] = "timeout"
                    log(f"{label}: session timeout ({cfg['session_timeout']} min) — interrupting")
                else:
                    if time.time() - last_poll > cfg["poll_interval"]:
                        last_poll = time.time()
                        self.guard.refresh(force=True)
                    bad, reason, _ = self.guard.over()
                    if bad:
                        out["interrupted"] = "limit"
                        log(f"{label}: {reason} — interrupting session to pause")
                if out["interrupted"]:
                    self._interrupt(proc)
            th.join(timeout=30)
            out["exit"] = proc.returncode
            self.child = None

        res = out["result"] or {}
        if res.get("is_error") and re.search(r"usage limit|rate limit|limit reached|resets? at",
                                             str(res.get("result", "")), re.I):
            out["rejected"] = True
        secs = round(time.time() - started)
        st["totals"]["sessions"] += 1
        st["totals"]["seconds"] += secs
        st["totals"]["cost_usd"] += float(res.get("total_cost_usd") or 0)
        out["seconds"] = secs
        return out

    def command_complaint(self, data: dict, fields) -> str | None:
        """The message to send back when a session proposed a command the orchestrator will not run."""
        problems = []
        for field in fields:
            flag = CMD_FIELDS.get(field, "")
            if flag and (self.cfg.get(flag) or "").strip():
                continue            # the developer set this one; whatever the session says is ignored
            val = (data.get(field) or "").strip()
            if not val or val == "-":
                continue
            ok, why = command_allowed(val, self.cfg.get("allow_cmd") or ())
            if not ok:
                problems.append(f"- `{field}`: `{one_line(val, 200)}` — {why}")
        if not problems:
            return None
        return CMD_CORRECTION.replace("{{problems}}", "\n".join(problems))

    def session(self, label, prompt, model, schema, required_key, extra_disallowed=(), recheck=None):
        """One logical step, with the guides it was handed checked afterwards (see `check_guides`)."""
        guides = self.guides_digest()
        try:
            return self._session(label, prompt, model, schema, required_key, extra_disallowed, recheck)
        finally:
            self.sessions_this_run += 1     # one step, however many resumes it took
            self.check_guides(label, guides)

    def _session(self, label, prompt, model, schema, required_key, extra_disallowed=(), recheck=None):
        """Run one logical step to completion: handles limit pauses, resumes, nudges, restarts.

        `recheck` gets the structured output and returns a complaint to send back, or None. The
        session gets one chance to correct itself; after that the step goes on with what it returned
        and the caller decides what to keep."""
        prompt = (prompt + "\n\n---\nFinish by returning structured output matching this JSON schema "
                  "(if structured output is unavailable, end your final message with one ```json block):\n"
                  f"```json\n{json.dumps(schema, indent=1)}\n```\n")
        resume, cur, nudges, total_secs, total_cost = None, prompt, 0, 0, 0.0
        rejections, corrections = 0, 0
        act = self.state.get("active_session")
        if act and act.get("label") == label and act.get("session_id"):
            resume, cur = act["session_id"], RESUME_AFTER_RESTART
        while True:
            self.check_stop()
            self.wait_for_usage()
            before_cost = self.state["totals"]["cost_usd"]
            out = self.run_claude(label, cur, model, schema, resume, extra_disallowed)
            total_secs += out["seconds"]
            total_cost += self.state["totals"]["cost_usd"] - before_cost
            if out["interrupted"] == "stop":
                self.save()
                raise StopRequested("signal")
            if out["interrupted"] == "budget":
                # the resume handle is already on disk (note_session), so the same `run` picks the
                # step up where the session was interrupted
                self.save()
                raise StopRequested(out["budget"])
            if out["interrupted"] == "limit" or out["rejected"]:
                if out["rejected"]:
                    rejections += 1
                    if rejections > 12:
                        raise StepFailed(f"{label}: usage limit keeps rejecting requests (12 retries)")
                    self.guard.rejected = True
                if not self.wait_for_usage() and out["rejected"]:
                    # API doesn't show the limit (other bucket / lag) — back off before retrying
                    self.event("usage", "backoff", "limit error without matching usage data; waiting 10 min")
                    self.sleep_with_stop(600)
                if out["session_id"]:
                    resume, cur = out["session_id"], RESUME_AFTER_LIMIT
                continue
            if out["interrupted"] == "timeout":
                self.state["active_session"] = None
                self.event(label, "timeout", "session exceeded time limit", total_secs, round(total_cost, 2))
                return {"status": "partial", "summary": "session timed out"}
            data = extract_json(out["result"], required_key)
            if data is not None:
                complaint = recheck(data) if recheck else None
                if complaint and out["session_id"] and corrections < 1:
                    corrections += 1
                    log(f"{label}: the commands it returned are not runnable — asking it to correct them")
                    resume, cur = out["session_id"], complaint
                    continue
                self.state["active_session"] = None
                status = data.get("status") or data.get("verdict") or "done"
                self.event(label, status, data.get("summary", ""), total_secs, round(total_cost, 2))
                return data
            if out["session_id"] and nudges < 2:
                nudges += 1
                log(f"{label}: no structured output (exit {out['exit']}) — nudging session ({nudges}/2)")
                resume, cur = out["session_id"], NUDGE
                continue
            self.state["active_session"] = None
            tail = one_line((out["result"] or {}).get("result", ""), 400)
            raise StepFailed(f"{label}: session ended without a usable result (exit {out['exit']}): {tail}")

    def sleep_with_stop(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.check_stop()
            time.sleep(max(1, min(60, end - time.time())))

    def wait_for_usage(self) -> bool:
        """Block while usage is over threshold. Returns True if it had to pause."""
        paused = False
        while True:
            self.guard.refresh(force=True)
            bad, reason, until = self.guard.over()
            if not bad:
                if paused:
                    self.state["status"], self.state["resume_at"] = "running", None
                    self.event("usage", "resumed", self.guard.describe())
                return paused
            unknown = until is None or until < time.time()
            wake = (time.time() + 15 * 60) if unknown else until + RESET_BUFFER_S
            deadline = self.budget_deadline()
            if deadline and wake >= deadline:
                raise StopRequested(f"{reason}, and waiting until ≈{hm(wake)} would run past "
                                    f"--max-hours {float(self.cfg['max_hours']):g} — stopping instead of sleeping")
            self.state["status"], self.state["resume_at"] = "paused_limit", hm(wake)
            if not paused:
                self.event("usage", "paused", f"{reason}; sleeping until ≈{hm(wake)}")
                self.notify(f"autodev ⏸ {reason}; resume ≈{hm(wake)}")
                paused = True
            else:
                self.save()
            self.sleep_with_stop(wake - time.time())
            self.guard.forget_event_values()

    # ---- tests & git -------------------------------------------------------------
    def run_tests(self, pdir: Path):
        cmd = self.state["project"].get("test_command")
        if not cmd:
            return True, "no test command configured — skipped"
        log(f"running tests: {cmd}")
        return self._shell(cmd, self.cfg["test_timeout"], pdir / "TEST_OUTPUT.txt", "test command")

    def _shell(self, cmd: str, minutes: int, out_file: Path | None = None, label: str = ""):
        """Run a shell command in its own process group; return (ok, tail-of-output)."""
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, env=child_env(), start_new_session=True)
        try:
            output, _ = proc.communicate(timeout=minutes * 60)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            kill_group(proc)
            output, _ = proc.communicate()
            output = (output or "") + f"\n\nTIMEOUT: {label or 'command'} exceeded {minutes} min"
            code = -1
        lines = (output or "").splitlines()
        if out_file is not None:
            atomic_write(out_file, f"$ {cmd}\n# exit code: {code}   # {ts()}\n\n" + "\n".join(lines[-400:]) + "\n")
        last = next((ln for ln in reversed(lines) if ln.strip()), "")
        return code == 0, f"exit {code}: {last}"

    def e2e_command(self) -> str:
        cmd = ((self.state.get("project") or {}).get("e2e_command") or "").strip()
        return "" if cmd == "-" else cmd

    def e2e_configured(self) -> bool:
        return self.cfg.get("e2e") != "off" and bool(self.e2e_command())

    def _spawn_logged(self, cmd: str, label: str) -> subprocess.Popen:
        """Start a lifecycle command with its output going to a file, never to a pipe.

        A command that starts a server and exits leaves that server holding the stdout it
        inherited, so reading a pipe to end-of-file would block until the server itself stops —
        the up command would look like it never returned. A file has no such reader."""
        SURFACE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SURFACE_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n$ {cmd}\n# {label} — {ts()}\n")
            f.flush()
            return subprocess.Popen(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, env=child_env(), start_new_session=True)

    @staticmethod
    def _url_ready(url: str) -> bool:
        """True when something answers — any status below 500 means the surface is listening."""
        try:
            with urllib.request.urlopen(url, timeout=5):
                return True
        except urllib.error.HTTPError as e:
            return e.code < 500
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _wait_ready(self, url: str, seconds: int) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._url_ready(url):
                return True
            time.sleep(3)
        return False

    def surfaces_up(self) -> bool:
        """Start whatever the e2e suite attaches to. The suite never starts an app itself.

        Called once per e2e step, so the command must be idempotent: starting an already-running
        surface has to succeed rather than fail on a taken port. It should also return once the
        surfaces are up. A command that stays in the foreground instead only works with
        --e2e-ready-url, which then decides when the surfaces are ready."""
        cmd = ((self.state.get("project") or {}).get("e2e_up_command") or "").strip()
        url = (self.cfg.get("e2e_ready_url") or "").strip()
        if cmd and cmd != "-":
            log(f"e2e surfaces up: {cmd}")
            proc = self._spawn_logged(cmd, "e2e up")
            self.surface_proc = proc
            deadline, probed = time.time() + 15 * 60, 0.0
            while proc.poll() is None and time.time() < deadline:
                if url and time.time() - probed > 3:
                    probed = time.time()
                    if self._url_ready(url):
                        log("e2e up is still in the foreground but the ready URL answers — continuing")
                        return True
                time.sleep(0.5)
            if proc.poll() is None:
                self._kill_surface_proc()
                self.event("e2e-up", "failed", "the up command never returned within 15 min; it must "
                           "start the surfaces and exit, or answer --e2e-ready-url while it runs")
                return False
            self.surface_proc = None
            if proc.returncode != 0:
                self.event("e2e-up", "failed", f"exit {proc.returncode} — see {SURFACE_LOG.as_posix()}")
                return False
        if url and not self._wait_ready(url, 180):
            self.event("e2e-up", "failed", f"{url} never answered")
            return False
        return True

    def _kill_surface_proc(self) -> None:
        """Stop an up command still running in the foreground, and the group it started."""
        proc = self.surface_proc
        self.surface_proc = None
        if not proc or proc.poll() is not None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                kill_group(proc, sig)
                proc.wait(timeout=20)
                return
            except subprocess.TimeoutExpired:
                continue
            except (ProcessLookupError, OSError):
                return

    def surfaces_down(self) -> None:
        cmd = ((self.state.get("project") or {}).get("e2e_down_command") or "").strip()
        if cmd and cmd != "-":
            log(f"e2e surfaces down: {cmd}")
            proc = self._spawn_logged(cmd, "e2e down")
            try:
                proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                log("WARN the e2e down command did not finish within 10 min — killing it")
                kill_group(proc)
                proc.wait()
        self._kill_surface_proc()

    def run_e2e(self, pdir: Path):
        cmd = self.e2e_command()
        if not cmd:
            return True, "no e2e command configured — skipped"
        log(f"running e2e: {cmd}")
        return self._shell(cmd, self.cfg["e2e_timeout"], pdir / "E2E_OUTPUT.txt", "e2e suite")

    def note_command_files(self, staged) -> None:
        """Say when a commit changes a file that decides what the project's commands actually run.

        The vetting checks the shape of a command, not what it executes: `make test` runs whatever
        the Makefile says, and the Makefile is written by the sessions as part of their work. The
        change cannot be forbidden — it is ordinary development — so it is named instead."""
        touched = sorted(p for p in staged if COMMAND_FILES.search(p))
        if touched:
            self.event("commit", "command files", "this commit changes what the project's own commands "
                       "run: " + ", ".join(touched[:6]))

    def guard_staged(self, staged=None) -> list:
        """Take back out of the index anything that must not be committed automatically.

        `git add -A` cannot tell a phase's work from whatever else a session left in the tree, and
        with --pr the difference reaches GitHub the same night. A held-back file stays on disk and is
        reported; committing it yourself is what tells autodev it belongs here."""
        limit = int(self.cfg.get("max_file_mb") or 0) * 1048576
        if staged is None:
            staged = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", check=False).splitlines()
        blocked = [(p, why_not_committable(Path(p), limit)) for p in staged if p]
        blocked = [(p, why) for p, why in blocked if why]
        for path, why in blocked:
            git("reset", "-q", "HEAD", "--", path, check=False)
            log(f"WARN not committing {path}: {why}")
            self.record_decision(f"kept `{path}` out of the commit — {why}. It is still in the working "
                                 "tree: gitignore it if it does not belong here, or commit it yourself "
                                 "if it does.")
        if blocked:
            self.event("commit", "held back", "; ".join(f"{p} ({w})" for p, w in blocked[:6]))
        return [f"not committed: {p} ({w})" for p, w in blocked]

    def commit(self, message: str, body: str) -> str | None:
        """Commit the work. A failing commit hook stops the run rather than being bypassed.

        The hooks are the repository's own checks — often the secret scanner or the lint gate —
        and a night of commits pushed past them is exactly what nobody reviews in the morning. The
        one thing handled automatically is the common case of a hook that reformats files and then
        fails: that is restaged and committed once."""
        def attempt():
            return subprocess.run(["git", "commit", "-q", "-m", message, "-m", body],
                                  capture_output=True, text=True)

        git("add", "-A")
        staged = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR",
                                 check=False).splitlines() if p]
        self.held_back = self.guard_staged(staged)
        self.note_command_files(staged)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return None
        before = git("status", "--porcelain", check=False)
        r = attempt()
        if r.returncode != 0 and git("status", "--porcelain", check=False) != before:
            log("WARN a commit hook changed files and failed — restaging what it did and retrying once")
            git("add", "-A")
            r = attempt()
        if r.returncode != 0:
            detail = one_line(r.stderr or r.stdout, 400)
            if not self.cfg.get("allow_no_verify"):
                raise StepFailed(
                    f"a git commit hook rejected this commit: {detail}\nThose hooks are this "
                    "repository's own checks, so autodev does not commit past them. Fix the cause and "
                    "run again to resume, or pass --allow-no-verify if they are known to be broken.")
            log(f"WARN committing past the hooks, as --allow-no-verify asked: {detail}")
            self.record_decision(f"commit hooks failed ({detail}); committed with --no-verify because "
                                 "--allow-no-verify was set")
            git("commit", "-q", "--no-verify", "-m", message,
                "-m", body + "\n\n[autodev] commit hooks failed; committed with --no-verify")
        return git("rev-parse", "--short", "HEAD")

    def publish(self, final: bool = False) -> None:
        """Push the branch (and sync the draft PR). Never raises: failures are logged and retried next time."""
        if self.push_mode == "never" or (self.push_mode == "end" and not final):
            return
        st, cfg = self.state, self.cfg
        branch = st.get("branch")
        if not branch:
            return
        try:
            if self.github:
                self.github.push(branch)
                where = f"{self.github.repo}@{branch} as {self.github.login}"
            else:
                r = subprocess.run(["git", "push", cfg["remote"], f"HEAD:refs/heads/{branch}"], capture_output=True,
                                   text=True, timeout=900, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
                if r.returncode != 0:
                    raise RuntimeError(one_line(r.stderr or r.stdout, 400))
                where = f"{cfg['remote']}/{branch}"
            self.event("push", "done", where)
            base = st.get("base_branch")
            if cfg.get("pr") and self.github and base and base != branch:
                self.render_progress()
                url = self.github.sync_pr(branch, base, f"autodev: {(st.get('project') or {}).get('name') or branch}",
                                          (AD / "PROGRESS.md").read_text(encoding="utf-8"))
                if url and st.get("pr_url") != url:
                    st["pr_url"] = url
                    self.event("pr", "draft", url)
        except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as e:
            self.event("push", "failed", str(e))

    # ---- steps ---------------------------------------------------------------------
    def step_architect(self) -> None:
        """Design of record before any roadmap: architecture, ADRs, risks, and the real commands."""
        st, cfg = self.state, self.cfg
        res = self.session("architect", render("architect", spec=st["spec"], lang=cfg["lang"]),
                           cfg["model_plan"], ARCH_SCHEMA, "summary",
                           recheck=lambda d: self.command_complaint(d, CMD_FIELDS))
        if res.get("status") == "blocked":
            raise StepFailed(f"architect step blocked: {res.get('summary')}")
        if not (AD / "ARCHITECTURE.md").exists():
            raise StepFailed("architect step did not create .autodev/ARCHITECTURE.md")

        def pick(key, cfg_key):
            """A command the developer passed on the command line wins, and is trusted as typed;
            anything this session proposed has to pass vet_command first."""
            return (cfg.get(cfg_key) or "").strip() or self.vet_command(key, res.get(key) or "")

        st["project"] = {
            **st.get("project", {}),
            "stack": res.get("stack", ""),
            "test_command": cfg["test_cmd"] or self.vet_command("test_command",
                                                               res.get("test_command") or ""),
            "lint_command": self.vet_command("lint_command", res.get("lint_command") or ""),
            "e2e_command": pick("e2e_command", "e2e_cmd"),
            "e2e_up_command": pick("e2e_up_command", "e2e_up_cmd"),
            "e2e_down_command": pick("e2e_down_command", "e2e_down_cmd"),
        }
        log(f"architecture: {one_line(res.get('stack'), 120)}")
        log(f"commands — test: {st['project']['test_command'] or '(none)'} · "
            f"e2e: {st['project']['e2e_command'] or '(none yet)'}")
        self.set_step("roadmap")
        self.commit("autodev: architecture, ADRs and risk register",
                    one_line(res.get("summary"), 400) + "\n\nFrom " + st["spec"])
        self.publish()
        self.require_test_command("the architect step")

    def step_roadmap(self) -> None:
        st, cfg = self.state, self.cfg
        res = self.session("roadmap", render("roadmap", spec=st["spec"], lang=cfg["lang"]),
                           cfg["model_plan"], ROADMAP_SCHEMA, "phases",
                           recheck=lambda d: self.command_complaint(d, ("test_command",)))
        if not res.get("phases"):
            raise StepFailed("roadmap session returned no phases")
        cur_test = (st.get("project") or {}).get("test_command", "")
        st["project"] = {**st.get("project", {}),
                         "name": res.get("project_name") or Path.cwd().name, "summary": res.get("summary", ""),
                         "test_command": cfg["test_cmd"] or self.vet_command(
                             "test_command", res.get("test_command") or "", cur_test)}
        seen = set()
        st["phases"] = []
        for k, ph in enumerate(res["phases"], 1):
            slug = slugify(ph.get("slug") or ph["title"])
            if slug in seen:
                slug = f"{slug}-{k}"
            seen.add(slug)
            st["phases"].append({**ph, "slug": slug, "status": "pending",
                                 "user_facing": bool(ph.get("user_facing", True))})
        st["phase_index"], st["phase_ctx"] = 0, {}
        md = [f"# Roadmap — {st['project']['name']}", "", f"Spec: `{st['spec']}` · generated {ts()}", "",
              res.get("summary", ""), "", f"**Test command:** `{st['project']['test_command'] or '(none)'}`", ""]
        if res.get("assumptions"):
            md += ["## Assumptions", "", bullets(res["assumptions"]), ""]
        md += ["## Phases", ""]
        for k, ph in enumerate(st["phases"], 1):
            md += [f"### {k}. {ph['title']}", "",
                   f"**Goal:** {ph['goal']}", "",
                   f"**User-facing:** {'yes — gets end-to-end cases and user docs' if ph['user_facing'] else 'no'}", "",
                   "**Deliverables:**", bullets(ph["deliverables"]), "",
                   "**Acceptance criteria:**", bullets(ph["acceptance_criteria"]), ""]
        atomic_write(AD / "ROADMAP.md", "\n".join(md))
        self.set_step("plan")
        self.commit(f"autodev: roadmap ({len(st['phases'])} phases)", "Generated from " + st["spec"])
        self.publish()
        self.require_test_command("the roadmap step")

    # ---- one phase, step by step ---------------------------------------------------
    def step_phase(self) -> None:
        """Run the current phase step and move the phase where that step says to go.

        Each handler returns the next step, so a phase's routing is one readable line per
        outcome instead of a branch that has to re-derive where the phase was headed."""
        st = self.state
        run = PhaseRun(self, st["phase_index"])
        handler = PHASE_STEPS.get(st["step"])
        if handler is None:
            raise StepFailed(f"unknown step {st['step']}")
        before = st["phase_index"]
        nxt = getattr(self, handler)(run)
        if nxt:
            self.set_step(nxt)
        if st["phase_index"] != before:         # the phase finished and the next one starts
            self.publish()

    def to_tests(self, run: "PhaseRun", after: str) -> str:
        """Send the phase through the suite, remembering where it was going.

        The test step is reached from the implementation, from review fixes and from e2e fixes.
        Without a remembered target it has to guess, and a phase coming back from end-to-end
        fixes gets sent into another review round instead of on to its documentation."""
        run.ctx["after_tests"] = after
        return "test"

    def next_review(self, run: "PhaseRun") -> str:
        """The review round this phase still owes, or where it goes now reviews are done."""
        if run.ctx.get("review_round", 0) < self.cfg["max_review_rounds"]:
            return "review"
        return self.after_review(run.ph)

    def _plan(self, run: "PhaseRun") -> str:
        cfg, st = self.cfg, self.state
        if not run.ctx.get("base_sha"):
            run.ctx.update(base_sha=git("rev-parse", "HEAD"), impl_runs=0, test_fix_attempts=0,
                           review_round=0, warnings=[])
        run.ph["status"] = "in_progress"
        res = self.session(run.label, render("plan", **run.common), cfg["model_plan"], STEP_SCHEMA, "status",
                           recheck=lambda d: self.command_complaint(d, ("test_command",)))
        if res["status"] == "blocked":
            raise StepFailed(f"phase {run.n} plan blocked: {res.get('summary')}")
        if not (run.dir / "PLAN.md").exists():
            raise StepFailed(f"phase {run.n}: PLAN.md was not created")
        if not cfg["test_cmd"]:
            st["project"]["test_command"] = self.vet_command(
                "test_command", res.get("test_command") or "", st["project"].get("test_command", ""))
        return "implement"

    def _implement(self, run: "PhaseRun") -> str:
        cfg = self.cfg
        run.ctx["impl_runs"] += 1
        res = self.session(run.label, render("implement", run=run.ctx["impl_runs"], **run.common),
                           cfg["model_impl"], STEP_SCHEMA, "status")
        if res["status"] == "blocked":
            raise StepFailed(f"phase {run.n} implementation blocked: {res.get('summary')}")
        left = unchecked_tasks(run.dir / "PLAN.md")
        if (res["status"] == "partial" or left) and run.ctx["impl_runs"] < cfg["max_impl_runs"]:
            log(f"phase {run.n}: {left} task(s) left — continuing in a fresh session")
            return "implement"
        if left:
            run.ctx["warnings"].append(f"{left} PLAN.md task(s) left unchecked")
        return self.to_tests(run, after=self.next_review(run))

    def _test(self, run: "PhaseRun") -> str:
        if not (self.state["project"].get("test_command") or "").strip():
            run.ctx["warnings"].append("no test command configured — the unit suite never ran")
        ok, summary = self.run_tests(run.dir)
        self.event(f"p{run.n:02d}-tests", "pass" if ok else "fail", summary)
        if ok:
            return run.ctx.get("after_tests") or self.next_review(run)
        if run.ctx["test_fix_attempts"] >= self.cfg["max_test_fix"]:
            raise StepFailed(f"phase {run.n}: tests still failing after {run.ctx['test_fix_attempts']} fix "
                             f"attempts (see {run.dir.as_posix()}/TEST_OUTPUT.txt)")
        return "test_fix"

    def _test_fix(self, run: "PhaseRun") -> str:
        cfg = self.cfg
        run.ctx["test_fix_attempts"] += 1
        res = self.session(f"{run.label}{run.ctx['test_fix_attempts']}",
                           render("test_fix", attempt=run.ctx["test_fix_attempts"], max=cfg["max_test_fix"],
                                  **run.common), cfg["model_impl"], STEP_SCHEMA, "status")
        if res["status"] == "blocked":
            raise StepFailed(f"phase {run.n} test fix blocked: {res.get('summary')}")
        return "test"                           # after_tests still points where the phase was going

    def _review(self, run: "PhaseRun") -> str:
        cfg = self.cfg
        run.ctx["review_round"] += 1
        r = run.ctx["review_round"]
        git("add", "-A")  # so `git diff <base>` also shows new files
        prev = (f"- Previous review: `{run.dir.as_posix()}/REVIEW-r{r - 1}.md` — check its blocker/major "
                "findings were really fixed." if r > 1 else "")
        marks = self.worktree_marks()
        res = self.session(f"{run.label}{r}", render("review", round=r, previous_review=prev, **run.common),
                           cfg["model_review"], REVIEW_SCHEMA, "verdict",
                           extra_disallowed=("Edit", "Write", "NotebookEdit"))
        # Edit/Write are blocked for the reviewer, but Bash is not, and `sed -i` writes files all the
        # same. The changes stay — undoing them could throw away a real fix — but they are never silent.
        touched = sorted(p[3:] for p in self.worktree_marks() ^ marks)
        if touched:
            shown = ", ".join(touched[:5]) + (f" +{len(touched) - 5} more" if len(touched) > 5 else "")
            self.event(f"{run.label}{r}", "touched the tree", f"review round {r} changed {shown}")
            run.ctx["warnings"].append(f"review round {r} changed the working tree itself ({shown}); "
                                       "those edits are part of this phase's commit, unreviewed")
        if "verdict" not in res:
            run.ctx["warnings"].append(f"review round {r} did not complete")
            return self.after_review(run.ph)
        findings = res.get("findings") or []
        md = [f"# Review — phase {run.n} round {r}", "", f"**Verdict:** {res['verdict']}", "",
              res.get("summary", ""), ""]
        for f in findings:
            md += [f"## [{f.get('severity', '?').upper()}] {f.get('title', '')}",
                   f"`{f.get('file', '')}`" if f.get("file") else "", "", f.get("detail", ""), ""]
            if f.get("suggested_fix"):
                md += [f"**Fix:** {f['suggested_fix']}", ""]
        atomic_write(run.dir / f"REVIEW-r{r}.md", "\n".join(md))
        if any(f.get("severity") in BLOCKING for f in findings):
            return "review_fix"
        return self.after_review(run.ph)

    def _review_fix(self, run: "PhaseRun") -> str:
        cfg = self.cfg
        r = run.ctx["review_round"]
        res = self.session(f"{run.label}{r}", render("review_fix", round=r, **run.common),
                           cfg["model_impl"], STEP_SCHEMA, "status")
        if res["status"] == "blocked":
            run.ctx["warnings"].append(f"review fixes round {r} blocked: {one_line(res.get('summary'), 120)}")
        if r >= cfg["max_review_rounds"]:
            run.ctx["warnings"].append(f"review round {r} had blocker/major findings; fixes applied, "
                                       "not re-reviewed")
        run.ctx["test_fix_attempts"] = 0
        return self.to_tests(run, after=self.next_review(run))

    def _with_surfaces(self, run: "PhaseRun", body, skipped: str) -> str:
        """Run a step against started surfaces, and always stop them unless the phase stays in e2e.

        The teardown is in a `finally` so an interrupt or a failed step does not leave a dev server
        holding its port for the next run."""
        if not self.surfaces_up():
            run.ctx["warnings"].append(skipped)
            log("WARN e2e surfaces did not start — skipping this step for this phase")
            self.surfaces_down()
            return self.after_e2e()
        nxt = None
        try:
            nxt = body(run)
            return nxt
        finally:
            if nxt != "e2e_fix":
                self.surfaces_down()

    def _e2e(self, run: "PhaseRun") -> str:
        run.ctx["e2e_runs"] = run.ctx.get("e2e_runs", 0) + 1
        return self._with_surfaces(run, self._e2e_body, "e2e skipped: the surfaces could not be started")

    def _e2e_body(self, run: "PhaseRun") -> str:
        cfg, st = self.cfg, self.state
        res = self.session(run.label, render("e2e", **run.common), cfg["model_qa"], E2E_SCHEMA, "status",
                           recheck=lambda d: self.command_complaint(
                               d, ("e2e_command", "e2e_up_command", "e2e_down_command")))
        for key, cfg_key in (("e2e_command", "e2e_cmd"), ("e2e_up_command", "e2e_up_cmd"),
                             ("e2e_down_command", "e2e_down_cmd")):
            if not cfg.get(cfg_key):
                st["project"][key] = self.vet_command(key, res.get(key) or "", st["project"].get(key, ""))
        if res["status"] == "blocked":
            run.ctx["warnings"].append(f"e2e blocked: {one_line(res.get('summary'), 160)}")
            return self.after_e2e()
        return self._run_e2e_suite(run)

    def _e2e_fix(self, run: "PhaseRun") -> str:
        run.ctx["e2e_fix_attempts"] = run.ctx.get("e2e_fix_attempts", 0) + 1
        nxt = self._with_surfaces(run, self._e2e_fix_body,
                                  "e2e fix skipped: the surfaces could not be started")
        if nxt in ("docs", "commit"):
            # the unit suite has to still be green after fixing the product for end-to-end cases,
            # and afterwards the phase carries on to where it was going — not back into review
            ok, summary = self.run_tests(run.dir)
            self.event(f"p{run.n:02d}-tests", "pass" if ok else "fail", summary + " (after e2e fixes)")
            if not ok:
                run.ctx["test_fix_attempts"] = 0
                run.ctx["after_tests"] = nxt
                return "test_fix"
        return nxt

    def _e2e_fix_body(self, run: "PhaseRun") -> str:
        cfg = self.cfg
        res = self.session(f"{run.label}{run.ctx['e2e_fix_attempts']}",
                           render("e2e_fix", attempt=run.ctx["e2e_fix_attempts"], max=cfg["max_e2e_fix"],
                                  **run.common), cfg["model_impl"], STEP_SCHEMA, "status")
        if res["status"] == "blocked":
            run.ctx["warnings"].append(f"e2e fix blocked: {one_line(res.get('summary'), 160)}")
            return self.after_e2e()
        return self._run_e2e_suite(run)

    def _run_e2e_suite(self, run: "PhaseRun") -> str:
        """Run the end-to-end suite and decide whether the phase moves on or goes fixing."""
        if not self.e2e_command():
            run.ctx["warnings"].append("no e2e command configured — the end-to-end suite never ran")
        ok, summary = self.run_e2e(run.dir)
        self.event(f"p{run.n:02d}-e2e", "pass" if ok else "fail", summary)
        if ok:
            return self.after_e2e()
        if run.ctx.get("e2e_fix_attempts", 0) >= self.cfg["max_e2e_fix"]:
            run.ctx["warnings"].append(f"e2e still failing after {self.cfg['max_e2e_fix']} fix attempts "
                                       f"({summary}) — see {run.dir.as_posix()}/E2E_OUTPUT.txt")
            return self.after_e2e()
        return "e2e_fix"

    def _docs(self, run: "PhaseRun") -> str:
        res = self.session(run.label, render("docs", **run.common), self.cfg["model_impl"], STEP_SCHEMA, "status")
        if res["status"] == "blocked":
            run.ctx["warnings"].append(f"docs blocked: {one_line(res.get('summary'), 160)}")
        return "commit"

    def _commit(self, run: "PhaseRun") -> str:
        st = self.state
        body = [f"Phase {run.n}/{run.total}: {run.ph['goal']}", "", f"Plan & reviews: {run.dir.as_posix()}/"]
        if run.ctx.get("warnings"):
            body += ["", "Warnings:"] + [f"- {w}" for w in run.ctx["warnings"]]
        sha = self.commit(f"autodev: phase {run.n:02d} — {run.ph['title']}", "\n".join(body))
        if self.held_back:
            run.ctx["warnings"] = run.ctx.get("warnings", []) + self.held_back
        if sha:
            git("tag", "-f", f"{st['branch']}/phase-{run.n:02d}", check=False)
        run.ph.update(status="done", commit=sha, warnings=run.ctx.get("warnings", []), finished=ts())
        self.event(f"p{run.n:02d}-commit", "done", sha or "no changes to commit")
        self.notify(f"autodev ✅ phase {run.n}/{run.total}: {run.ph['title']}")
        st["phase_index"], st["phase_ctx"] = run.i + 1, {}
        return "plan"

    def after_review(self, ph: dict) -> str:
        """Where a phase goes once the review is clean: end-to-end QA, documentation, or straight to the commit."""
        if self.cfg.get("e2e") != "off" and ph.get("user_facing", True):
            return "e2e"
        return self.after_e2e()

    def after_e2e(self) -> str:
        return "docs" if self.cfg.get("docs") else "commit"

    def step_finalize(self) -> None:
        """One closing session: make the documentation true, and write the morning handoff."""
        st, cfg = self.state, self.cfg
        base = st.get("run_base_sha") or "HEAD~1"
        res = self.session("finalize",
                           render("finalize", total=len(st.get("phases") or []), base_sha=base,
                                  test_command=st["project"].get("test_command") or "(none configured)",
                                  lang=cfg["lang"]),
                           cfg["model_plan"], STEP_SCHEMA, "status")
        if res.get("status") == "blocked":
            log(f"WARN finalize blocked: {one_line(res.get('summary'), 200)}")
        self.commit("autodev: documentation, changelog and handoff", one_line(res.get("summary"), 400))
        st["finalized"] = True
        self.event("finalize", res.get("status", "done"), one_line(res.get("summary"), 200))

    # ---- main loop ---------------------------------------------------------------
    def run(self) -> int:
        st = self.state
        self.run_started = time.time()
        st.pop("stop_reason", None)
        self.acquire_lock()
        try:
            self.setup()
            log(f"autodev run — spec {st['spec']} · branch {st['branch']} · step {st['step']}")
            while True:
                self.check_stop()
                if st["step"] == "architect":
                    self.step_architect()
                elif st["step"] == "roadmap":
                    self.step_roadmap()
                elif st["step"] == "finalize":
                    self.step_finalize()
                    break
                elif st["phase_index"] >= len(st["phases"]):
                    self.set_step("finalize" if (self.cfg.get("finalize") and not st.get("finalized"))
                                  else "done")
                    if st["step"] == "done":
                        break
                else:
                    self.step_phase()
            st["status"] = "done"
            self.event("run", "done", f"all {len(st['phases'])} phases completed")
            self.commit("autodev: run finished", "Final PROGRESS.md / DECISIONS.md")
            self.notify("autodev 🏁 all phases completed")
            return 0
        except StopRequested as e:
            st["status"], st["stop_reason"] = "stopped", str(e)
            self.event("run", "stopped", str(e))
            self.notify(f"autodev ⏹ stopped: {one_line(e, 160)}")
            return 130
        except StepFailed as e:
            st["status"], st["error"] = "failed", str(e)
            if st.get("phases") and st["phase_index"] < len(st["phases"]):
                st["phases"][st["phase_index"]]["status"] = "failed"
            self.event("run", "failed", str(e))
            self.notify(f"autodev ❌ {one_line(e, 200)}")
            return 1
        finally:
            self.save()
            if st.get("step") != "roadmap" or st.get("status") == "done":
                self.publish(final=True)
                self.save()
            try:
                if PID_FILE.read_text().strip() == str(os.getpid()):
                    PID_FILE.unlink()
            except OSError:
                pass

    # ---- progress document ------------------------------------------------------
    def render_progress(self) -> None:
        st = self.state
        phases = st.get("phases") or []
        idx = st.get("phase_index", 0)
        tot = st["totals"]
        cur = "roadmap" if st["step"] == "roadmap" else (
            f"phase {min(idx + 1, len(phases))}/{len(phases)} · step `{st['step']}`" if idx < len(phases) else "finished")
        name = (st.get("project") or {}).get("name") or Path.cwd().name
        lines = [f"# Autodev progress — {name}", "",
                 f"- **Status:** {st['status']}" + (f" (resume ≈ {st.get('resume_at')})" if st["status"] == "paused_limit" else ""),
                 f"- **Current:** {cur}",
                 f"- **Spec:** `{st['spec']}` · **Branch:** `{st.get('branch')}`"
                 + (f" · **PR:** {st['pr_url']}" if st.get("pr_url") else ""),
                 f"- **Stack:** {(st.get('project') or {}).get('stack') or '—'}"
                 + (f" · **Profile:** `{st['profile']}`" if st.get("profile") else ""),
                 f"- **Test command:** `{(st.get('project') or {}).get('test_command') or '—'}`"
                 + f" · **E2E:** `{(st.get('project') or {}).get('e2e_command') or '—'}`",
                 f"- **Usage:** {self.guard.describe()}",
                 f"- **Totals:** {tot['sessions']} sessions · {tot['seconds'] / 3600:.1f} h agent time · "
                 f"≈${tot['cost_usd']:.2f} API-equivalent",
                 f"- **Updated:** {ts()}", ""]
        if st.get("error"):
            lines += [f"> ❌ **Failed:** {one_line(st['error'], 500)}", ""]
        if st.get("status") == "stopped" and st.get("stop_reason"):
            lines += [f"> ⏹ **Stopped:** {one_line(st['stop_reason'], 300)} — the same `run` command continues "
                      "from here.", ""]
        if st.get("run_warnings"):
            lines += ["## Run warnings", ""] + [f"- {one_line(w, 300)}" for w in st["run_warnings"][-20:]] + [""]
        if phases:
            icons = {"pending": "⏳", "in_progress": "🔨", "done": "✅", "failed": "❌"}
            lines += ["## Phases", "", "| # | Phase | User-facing | Status | Commit | Warnings |",
                      "|---|---|---|---|---|---|"]
            for k, ph in enumerate(phases, 1):
                warn = "; ".join(ph.get("warnings") or []).replace("|", "\\|")
                lines.append(f"| {k} | {ph['title'].replace('|', '/')} | {'yes' if ph.get('user_facing', True) else 'no'} "
                             f"| {icons.get(ph['status'], '')} {ph['status']} | {ph.get('commit') or ''} | {warn} |")
            lines.append("")
        lines += ["## Timeline", ""]
        for e in st["events"][-300:]:
            extra = []
            if e.get("seconds"):
                extra.append(f"{e['seconds'] // 60}m")
            if e.get("cost"):
                extra.append(f"${e['cost']}")
            lines.append(f"- `{e['ts']}` **{e['label']}** — {e['status']}"
                         + (f" ({', '.join(extra)})" if extra else "") + (f": {e['summary']}" if e["summary"] else ""))
        lines += ["", "---", "Docs: `ARCHITECTURE.md` · `RISKS.md` · `ROADMAP.md` · `DECISIONS.md` · "
                  "`phases/*/PLAN.md` · `phases/*/REVIEW-r*.md` · `HANDOFF.md` (written at the end) · "
                  "project docs in `docs/dev/` and `docs/user/` · raw session logs in `logs/`. "
                  "Stop gracefully: `touch .autodev/STOP`."]
        atomic_write(AD / "PROGRESS.md", "\n".join(lines) + "\n")


# ----------------------------------------------------------------------------- CLI
SMOKE_SCHEMA = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}


def smoke_command(binary: str, flags: set, model: str = "haiku") -> list:
    """A session small enough to be free and complete enough to prove the real ones will work."""
    cmd = [binary, "-p", 'Reply with {"status":"ok"} and nothing else.',
           "--output-format", "stream-json", "--verbose", "--model", model,
           "--json-schema", json.dumps(SMOKE_SCHEMA), "--permission-mode", "auto",
           "--disallowedTools", "AskUserQuestion,WebFetch,WebSearch"]
    if "--permission-prompts" in flags:
        cmd += ["--permission-prompts", "none"]
    if "--strict-mcp-config" in flags:
        cmd += ["--strict-mcp-config"]
    return cmd


def read_smoke_result(stdout: str, stderr: str, code: int) -> tuple:
    """(ok, what to tell the developer) for the output of a smoke session."""
    for line in reversed((stdout or "").splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") != "result":
            continue
        if extract_json(ev, "status"):
            return True, "a headless session runs and returns structured output"
        return False, ("a session ran but returned no structured output — check --json-schema support: "
                       + one_line(ev.get("result"), 160))
    return False, f"no result from the session (exit {code}): {one_line(stderr, 200)}"


def smoke_session(binary: str, timeout: int = 180) -> tuple:
    """Everything checked before this is static — a version number, a token on a disk.

    This is what finds an expired login, a hook that blocks headless mode, or a build whose
    structured output does not work, and it finds them now instead of at 3am."""
    try:
        r = subprocess.run(smoke_command(binary, claude_flags(binary)), capture_output=True,
                           text=True, timeout=timeout, env=child_env())
    except subprocess.TimeoutExpired:
        return False, f"a session did not answer within {timeout}s"
    except OSError as e:
        return False, f"could not start a session: {e}"
    return read_smoke_result(r.stdout, r.stderr, r.returncode)


def new_state(spec: str, cfg: dict) -> dict:
    return {"version": 1, "spec": spec, "created": ts(), "status": "running", "branch": None, "config": cfg,
            "run_id": secrets.token_hex(16),
            "project": {}, "phases": [], "phase_index": 0, "step": "architect", "phase_ctx": {}, "events": [],
            "session_counter": 0, "active_session": None, "totals": {"sessions": 0, "seconds": 0, "cost_usd": 0.0}}


def cli_overrides(args) -> dict:
    over = {}
    for key in DEFAULTS:
        val = getattr(args, key, None)
        if val is not None:
            over[key] = val
    return over


def same_file(a, b) -> bool:
    """Whether two paths name the same spec — `docs/spec.md` and its absolute form are one file."""
    if not a or not b:
        return False
    if str(a) == str(b):
        return True
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def cmd_run(args) -> int:
    if args.fresh and AD.exists():
        bak = Path(f".autodev.bak-{datetime.now():%Y%m%d-%H%M%S}")
        AD.rename(bak)
        print(f"moved previous run to {bak}")
        intake = bak / "INTAKE.md"
        if intake.exists():      # written by the pre-flight interview, minutes before this command
            AD.mkdir(exist_ok=True)
            shutil.copyfile(intake, AD / "INTAKE.md")
            print("kept INTAKE.md from the pre-flight interview")
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        try:
            ensure_run_is_ours(state, args.adopt)
        except StepFailed as e:
            sys.exit(str(e))
        state["config"] = {**DEFAULTS, **state["config"], **cli_overrides(args)}
        if args.spec and not same_file(args.spec, state.get("spec")):
            print(f"WARNING --spec {args.spec} ignored: this run follows {state.get('spec')} "
                  "(--fresh starts over with a different spec)")
        print(f"resuming run: status={state['status']} step={state['step']}")
    else:
        if not args.spec or not Path(args.spec).is_file():
            sys.exit("--spec must point to an existing file for a new run")
        AD.mkdir(exist_ok=True)
        state = new_state(Path(args.spec).as_posix(), {**DEFAULTS, **cli_overrides(args)})
        claim_run(state["run_id"])
    return Orchestrator(state).run()


def cmd_status(_args) -> int:
    if not STATE_FILE.exists():
        print("no autodev run in this directory")
        return 1
    st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    phases = st.get("phases") or []
    print(f"status: {st['status']}  step: {st['step']}  phase: {min(st['phase_index'] + 1, len(phases))}/{len(phases)}"
          + (f"  resume≈{st.get('resume_at')}" if st["status"] == "paused_limit" else ""))
    if st.get("error"):
        print("error:", st["error"])
    if st.get("status") == "stopped" and st.get("stop_reason"):
        print("stopped:", st["stop_reason"], "— the same `run` continues from here")
    alive = False
    if PID_FILE.exists():
        try:
            os.kill(int(PID_FILE.read_text()), 0)
            alive = True
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    print("process:", "running" if alive else "not running")
    for e in st["events"][-8:]:
        print(f"  {e['ts']}  {e['label']}: {e['status']}  {e['summary'][:100]}")
    return 0


def cmd_doctor(args) -> int:
    fails = 0

    def rep(level, msg):
        nonlocal fails
        fails += level == "FAIL"
        print(f"[{level:4}] {msg}")

    if args.spec:
        p = Path(args.spec)
        rep("OK" if p.is_file() else "FAIL", f"spec: {p}" + ("" if p.is_file() else " not found"))
    if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode == 0:
        dirty = [ln for ln in git("status", "--porcelain").splitlines() if ".autodev" not in ln]
        rep("WARN" if dirty else "OK", f"git: {len(dirty)} uncommitted change(s) — will be snapshot-committed"
            if dirty else "git: clean working tree")
        if not (args.gh_user or args.git_email):
            rep("OK" if git("config", "user.email", check=False) else "FAIL", "git identity (user.email)")
        if not (args.gh_user or args.git_name):
            rep("OK" if git("config", "user.name", check=False) else "FAIL", "git identity (user.name)")
        born = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0
        head = git("rev-parse", "--abbrev-ref", "HEAD", check=False) if born else ""
        if not born:      # a repository with no commits reports "HEAD" too, and is perfectly fine
            rep("OK", "git: no commits yet — the run makes the first one on "
                      + (git("symbolic-ref", "--short", "HEAD", check=False) or "the current branch"))
        else:
            rep("FAIL" if head == "HEAD" else "OK",
                "git: detached HEAD — check out a branch first, the run needs a base branch to return to"
                if head == "HEAD" else f"git: on branch {head}")
        rep("OK" if Path(".gitignore").exists() else "WARN",
            "root .gitignore" + ("" if Path(".gitignore").exists() else
                                 " missing — whatever a session installs or generates lands in the index; "
                                 "the commit filter holds the usual suspects back, but a gitignore is the fix"))
    else:
        rep("WARN", "not a git repo — autodev will run `git init`")
    binary = args.claude_bin or DEFAULTS["claude_bin"]
    ver = claude_version(binary)
    if ver is None:
        rep("FAIL", f"`{binary} --version` failed")
    else:
        v = ".".join(map(str, ver))
        rep("OK" if ver >= PERMISSION_PROMPTS_MIN else "WARN",
            f"Claude Code {v}" + ("" if ver >= PERMISSION_PROMPTS_MIN else " — update recommended (≥2.1.259)"))
        if args.no_smoke:
            rep("INFO", "headless session: not tried (--no-smoke)")
        else:
            ok, detail = smoke_session(binary)
            rep("OK" if ok else "FAIL", f"headless session: {detail}")
    if args.gh_user:
        try:
            gh = GitHub(args.gh_user, args.gh_host or "github.com", args.gh_repo or "", args.remote or "origin").connect()
            rep("OK", f"gh: token for {gh.login} · commits as "
                      f"{args.git_name or gh.name} <{args.git_email or gh.email or '?'}>")
            repo = gh.resolve_repo()
            if not repo:
                rep("WARN", f"gh: no GitHub repo (remote '{gh.remote}' missing or not on {gh.host}); "
                            "add a remote or pass --gh-repo owner/name, otherwise push/PR are skipped")
            else:
                rep("OK" if gh.can_push else "FAIL", f"gh: {repo} — push permission: {'yes' if gh.can_push else 'NO'}")
        except RuntimeError as e:
            rep("FAIL", f"gh: {e}")
    elif shutil.which("gh"):
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        accounts = sorted(set(re.findall(r"account (\S+)", (r.stdout or "") + (r.stderr or ""))))
        rep("INFO", "gh accounts: " + (", ".join(accounts) or "none") + " — pass --gh-user to commit/push as one of them")
    g = UsageGuard(DEFAULTS["threshold"], DEFAULTS["weekly_threshold"])
    g.refresh(force=True)
    rep("OK" if g.api_ok else "WARN", f"usage API: {g.describe()}" if g.api_ok else
        "usage API unavailable — pauses will trigger only on limit events/errors (set AUTODEV_OAUTH_TOKEN)")
    if sys.platform == "darwin" and not os.environ.get("AUTODEV_OAUTH_TOKEN"):
        rep("INFO", "usage token: read from the login Keychain — the first read on a machine can raise a "
                    "system dialog, which an unattended run cannot answer. Run `doctor` once on the machine "
                    "that will host the run, or set AUTODEV_OAUTH_TOKEN.")
    rep("OK" if shutil.which("tmux") else "WARN", "tmux " + ("found" if shutil.which("tmux") else "not found"))
    if sys.platform == "darwin":
        rep("OK" if shutil.which("caffeinate") else "WARN", "caffeinate (prevents sleep; keep the lid open/on power)")
    guesses = []
    if Path("pyproject.toml").exists() or Path("pytest.ini").exists():
        guesses.append("uv run pytest -q" if Path("uv.lock").exists() else "python -m pytest -q")
    if Path("manage.py").exists():
        guesses.append("python manage.py test")
    if Path("package.json").exists():
        guesses.append("npm test --silent")
    if Path("Package.swift").exists():
        guesses.append("swift test")
    if Path("go.mod").exists():
        guesses.append("go test ./...")
    if Path("Cargo.toml").exists():
        guesses.append("cargo test")
    rep("INFO", "test command guess: " + (", ".join(guesses) if guesses else "none")
        + " — the architect step decides, and the run stops if it cannot name one; --test-cmd settles it")
    prof = getattr(args, "profile", None) or detect_profile()
    known = available_profiles()
    rep("OK" if prof in known else "FAIL",
        f"stack profile: {prof}" + ("" if prof in known else f" — unknown (available: {', '.join(known)})"))
    if Path(".autodev/PROFILE.md").exists():
        rep("INFO", ".autodev/PROFILE.md exists — kept as is; delete it to pick a different profile")
    if prof in ("django-react", "django-htmx", "fastapi-react"):
        have = shutil.which("npx") or shutil.which("playwright")
        rep("OK" if have else "WARN", "browser e2e driver: " + ("available" if have
            else "no npx/playwright found — phase 1 will have to install it"))
    if prof.startswith("swift"):
        rep("OK" if shutil.which("xcodebuild") else "FAIL", "xcodebuild "
            + ("found" if shutil.which("xcodebuild") else "not found — install Xcode command line tools"))
    if prof == "rust-tui":
        rep("OK" if shutil.which("cargo") else "FAIL", "cargo " + ("found" if shutil.which("cargo") else "not found"))
    if Path(".autodev").exists() and git("ls-files", ".autodev", check=False):
        rep("WARN", ".autodev/ is committed to this repository — it names the commands the orchestrator "
                    "runs; state that did not start here is refused unless you pass --adopt")
    if STATE_FILE.exists():
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        rep("INFO", f"existing run: status={st['status']} step={st['step']} phase_index={st['phase_index']} "
                    "(run resumes it; --fresh starts over)")
        rep("OK" if owns_run(st.get("run_id") or "") else "WARN",
            "run state started on this machine" if owns_run(st.get("run_id") or "") else
            "run state was not started on this machine — `run` refuses it without --adopt")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Autonomous phase-by-phase development with Claude Code")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="start or resume a run in the current directory")
    run.add_argument("--spec")
    run.add_argument("--fresh", action="store_true", help="archive existing .autodev and start over")
    run.add_argument("--test-cmd", dest="test_cmd")
    run.add_argument("--threshold", type=float, help="pause at this 5h usage %% (default 85)")
    run.add_argument("--weekly-threshold", dest="weekly_threshold", type=float, help="default 97")
    run.add_argument("--model-plan", dest="model_plan", help="roadmap + phase plans (default opus)")
    run.add_argument("--model-impl", dest="model_impl", help="implementation + fixes (default sonnet)")
    run.add_argument("--model-review", dest="model_review", help="reviews (default opus)")
    run.add_argument("--model-qa", dest="model_qa", help="end-to-end QA authoring (default sonnet)")
    run.add_argument("--profile", help="stack profile: " + ", ".join(available_profiles()) + " (default: detected)")
    run.add_argument("--e2e", choices=["auto", "off"], help="end-to-end step on user-facing phases (default auto)")
    run.add_argument("--e2e-cmd", dest="e2e_cmd", help="end-to-end suite command")
    run.add_argument("--e2e-up-cmd", dest="e2e_up_cmd", help="start the surfaces the suite attaches to")
    run.add_argument("--e2e-down-cmd", dest="e2e_down_cmd", help="stop them again")
    run.add_argument("--e2e-ready-url", dest="e2e_ready_url", help="poll this URL until it answers before the suite")
    run.add_argument("--e2e-timeout", dest="e2e_timeout", type=int, help="minutes (default 45)")
    run.add_argument("--max-e2e-fix", dest="max_e2e_fix", type=int)
    run.add_argument("--no-docs", dest="docs", action="store_const", const=False,
                     help="skip the per-phase documentation step")
    run.add_argument("--no-finalize", dest="finalize", action="store_const", const=False,
                     help="skip the closing documentation + handoff session")
    run.add_argument("--permission-mode", dest="permission_mode", choices=["auto", "bypass"])
    run.add_argument("--max-test-fix", dest="max_test_fix", type=int)
    run.add_argument("--max-review-rounds", dest="max_review_rounds", type=int)
    run.add_argument("--max-impl-runs", dest="max_impl_runs", type=int)
    run.add_argument("--max-hours", dest="max_hours", type=float, metavar="H",
                     help="stop the run after H hours of wall clock (resume with the same command)")
    run.add_argument("--max-sessions", dest="max_sessions", type=int, metavar="N",
                     help="stop the run after N steps in this run (a step is one session, however "
                          "many times it had to resume)")
    run.add_argument("--session-timeout", dest="session_timeout", type=int, help="minutes per session")
    run.add_argument("--test-timeout", dest="test_timeout", type=int, help="minutes")
    run.add_argument("--poll-interval", dest="poll_interval", type=int, help="seconds")
    run.add_argument("--notify-cmd", dest="notify_cmd", help='shell command; message in $AUTODEV_MSG')
    run.add_argument("--lang", help="language of .autodev docs (default English)")
    run.add_argument("--no-branch", dest="branch", action="store_const", const=False)
    run.add_argument("--no-caffeinate", dest="caffeinate", action="store_const", const=False)
    run.add_argument("--claude-bin", dest="claude_bin")
    run.add_argument("--adopt", action="store_true",
                     help="resume run state in .autodev/ that this machine did not create")
    run.add_argument("--web", choices=["on", "off"],
                     help="let sessions use WebFetch/WebSearch (default off)")
    run.add_argument("--mcp-config", dest="mcp_config", action="append", metavar="FILE",
                     help="MCP servers for the sessions, a file or a JSON string (repeatable)")
    run.add_argument("--inherit-mcp", dest="inherit_mcp", action="store_const", const=True,
                     help="also give the sessions the MCP servers configured for you")
    run.add_argument("--allow-no-verify", dest="allow_no_verify", action="store_const", const=True,
                     help="commit past a failing git hook instead of stopping")
    run.add_argument("--max-file-mb", dest="max_file_mb", type=int, metavar="MB",
                     help="hold back a staged file larger than this (default 5, 0 = no limit)")
    run.add_argument("--allow-cmd", dest="allow_cmd", action="append", metavar="BINARY",
                     help="also accept commands starting with BINARY when a session proposes one "
                          "(repeatable); commands you pass yourself are never checked")
    run.add_argument("--gh-user", dest="gh_user", help="gh account login to commit & push as")
    run.add_argument("--gh-host", dest="gh_host", help="default github.com")
    run.add_argument("--gh-repo", dest="gh_repo", help="owner/name (default: from the remote URL)")
    run.add_argument("--remote", help="git remote to read the repo from (default origin)")
    run.add_argument("--git-name", dest="git_name", help="commit author name override")
    run.add_argument("--git-email", dest="git_email", help="commit email override")
    run.add_argument("--push", choices=["phase", "end", "never"], help="default: phase with --gh-user, else never")
    run.add_argument("--pr", action="store_const", const=True, help="keep a draft PR updated with PROGRESS.md")
    run.set_defaults(func=cmd_run)

    doc = sub.add_parser("doctor", help="pre-flight checks")
    doc.add_argument("--spec")
    doc.add_argument("--no-smoke", action="store_true",
                     help="skip the trial headless session (it costs one small request)")
    doc.add_argument("--claude-bin", dest="claude_bin")
    doc.add_argument("--profile")
    doc.add_argument("--gh-user", dest="gh_user")
    doc.add_argument("--gh-host", dest="gh_host")
    doc.add_argument("--gh-repo", dest="gh_repo")
    doc.add_argument("--remote")
    doc.add_argument("--git-name", dest="git_name")
    doc.add_argument("--git-email", dest="git_email")
    doc.set_defaults(func=cmd_doctor)

    stat = sub.add_parser("status", help="show run status")
    stat.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
