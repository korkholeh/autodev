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
import json
import os
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

SKILL_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = SKILL_DIR / "prompts"
GUIDES_DIR = SKILL_DIR / "guides"
PROFILES_DIR = SKILL_DIR / "profiles"
AD = Path(".autodev")
STATE_FILE = AD / "state.json"
STOP_FILE = AD / "STOP"
PID_FILE = AD / "run.pid"
SURFACE_LOG = AD / "logs" / "e2e-surfaces.log"
USAGE_ENDPOINT = os.environ.get("AUTODEV_USAGE_ENDPOINT", "https://api.anthropic.com/api/oauth/usage")
RESET_BUFFER_S = int(os.environ.get("AUTODEV_RESET_BUFFER", "120"))
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
    "allow_cmd": [],     # extra head binaries a session may propose in a command
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

# git credential helper that answers only for this push, from env vars (token never hits argv or disk)
PUSH_HELPER = ('!f() { test "$1" = get || exit 0; echo "username=${AUTODEV_GH_LOGIN}"; '
               'echo "password=${AUTODEV_GH_TOKEN}"; }; f')

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


class StepFailed(Exception):
    pass


class StopRequested(Exception):
    pass


# ----------------------------------------------------------------------------- utils
_log_path: Path | None = None


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hm(epoch) -> str:
    return datetime.fromtimestamp(epoch).strftime("%d.%m %H:%M") if epoch else "?"


def log(msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    if _log_path:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def git(*args, check=True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise StepFailed(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def to_epoch(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e12 else float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "phase"


def one_line(s: str, limit=300) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def bullets(items) -> str:
    return "\n".join(f"- {x}" for x in (items or [])) or "- (none)"


# --------------------------------------------------------------- commands proposed by a session
# The orchestrator runs the test and e2e commands itself, with a shell and the developer's full
# environment, outside the permission classifier that guards a session's own Bash calls. Sessions
# propose those commands, and a session's input (the spec, a README, a page it fetched) is not
# trusted. So a proposed command has to look like a toolchain invocation: every segment starts with
# a known build/test binary, and nothing in it fetches or evaluates code. A command the developer
# passed on the command line is used as typed and never checked here.
CMD_ALLOWLIST = {
    "cd", "true", "echo", "sleep", "wait-on", "wait-for-it",
    "make", "just", "task", "mise", "nox", "tox", "hatch", "invoke", "set",
    "python", "python3", "py", "pytest", "coverage", "uv", "uvx", "pip", "pip3", "poetry",
    "pipenv", "pdm", "manage.py", "django-admin", "alembic", "ruff", "mypy", "black", "flake8",
    "pylint", "isort", "bandit",
    "node", "npm", "npx", "pnpm", "yarn", "bun", "bunx", "deno", "vitest", "jest", "mocha",
    "playwright", "cypress", "eslint", "prettier", "tsc", "vite", "turbo", "nx", "lerna", "rush",
    "cargo", "rustup", "rustc",
    "go", "gotestsum", "golangci-lint",
    "swift", "xcodebuild", "xcrun", "fastlane", "swiftlint", "swiftformat", "xcpretty", "xcbeautify",
    "dotnet", "mvn", "mvnw", "gradle", "gradlew", "mix", "rake", "bundle", "rspec", "rubocop",
    "composer", "phpunit", "php", "artisan",
    "cmake", "ctest", "ninja", "meson", "bazel", "buck2", "scons", "bear",
    "sbt", "lein", "clojure", "clj", "stack", "cabal",
    "flutter", "dart", "zig", "nim", "crystal", "elm", "tee",
    "docker", "docker-compose", "podman", "podman-compose",
}
CMD_WRAPPERS = {"env", "nohup", "time", "timeout", "stdbuf", "xvfb-run", "caffeinate"}
CMD_FORBIDDEN = (
    (re.compile(r"\$\(|`"), "command substitution"),
    (re.compile(r"\b(sudo|doas)\b"), "privilege escalation"),
    (re.compile(r"\b(curl|wget|ssh|scp|rsync)\b"), "network transfer"),
    (re.compile(r"\beval\b"), "eval"),
    (re.compile(r"\brm\b\s+-\w*[rf]"), "recursive or forced delete"),
    (re.compile(r"\b(sh|bash|zsh|ksh|fish|python3?|node|deno|perl|ruby|php|Rscript)\b\s+-[ce]\b"),
     "inline script"),
    (re.compile(r"\btee\b\s+(-\S+\s+)*(~|/(?!dev/null\b))"), "writing outside the repository"),
    (re.compile(r">>?\s*(~|/(?!dev/null\b))"), "redirection outside the repository"),
    (re.compile(r"\b(chmod|chown|killall|launchctl|crontab|systemctl)\b"), "system modification"),
)
CMD_MAX_LEN = 400


def command_head(segment: str):
    """The binary a shell segment starts with, ignoring env assignments and wrappers."""
    toks = segment.strip().split()
    while toks:
        raw = toks[0].strip("\'\"")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", raw):     # CI=1 npm test
            toks.pop(0)
            continue
        name = Path(raw).name if "/" in raw else raw            # .venv/bin/pytest -> pytest
        if name in CMD_WRAPPERS or raw.startswith("-") or re.fullmatch(r"[\d.]+[smh]?", raw):
            toks.pop(0)
            continue
        return name
    return None


def command_allowed(cmd: str, extra=()) -> tuple:
    """(ok, reason) for a command a session proposed. See the note above CMD_ALLOWLIST."""
    cmd = (cmd or "").strip()
    if not cmd:
        return False, "empty"
    if len(cmd) > CMD_MAX_LEN:
        return False, f"longer than {CMD_MAX_LEN} characters"
    for pat, why in CMD_FORBIDDEN:
        if pat.search(cmd):
            return False, why
    allowed = CMD_ALLOWLIST | {str(x).strip() for x in (extra or ()) if str(x).strip()}
    for segment in re.split(r"&&|\|\||;|\||&", cmd):
        head = command_head(segment)
        if head is not None and head not in allowed:
            return False, f"`{head}` is not a known build or test command"
    return True, ""


CMD_FIELDS = {  # structured-output field -> the run flag that overrides it (empty: no flag)
    "test_command": "test_cmd", "lint_command": "", "e2e_command": "e2e_cmd",
    "e2e_up_command": "e2e_up_cmd", "e2e_down_command": "e2e_down_cmd",
}
CMD_CORRECTION = """The orchestrator will not run the command(s) you returned, so this step is not finished yet:

{{problems}}

It runs these itself, outside the permission classifier that checks your own Bash calls, so it only
accepts a plain toolchain invocation: every segment has to start with a known build or test binary
(make, uv, python, pytest, npm, npx, cargo, swift, xcodebuild, go, gradle, cmake, docker, ...),
optionally chained with &&, and nothing may fetch or evaluate code, use sudo, or redirect outside
the repository.

Give the project a command of that shape instead of working around it: add the target to the
Makefile, the script entry to package.json, or the equivalent for this stack, and commit that file
as part of your work. Run the command to be sure it works, then return the corrected commands in the
same structured output. Use `-` for a command that is genuinely not needed."""


def render(name: str, **kw) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    for k, v in kw.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def child_env() -> dict:
    """Environment for child processes: drop markers of an enclosing Claude Code session,
    otherwise nested `claude` may refuse to start when launched from inside Claude Code."""
    env = dict(os.environ)
    for k in list(env):
        if k == "CLAUDECODE" or k == "CLAUDE_CODE_ENTRYPOINT":
            env.pop(k)
    return env


def claude_version(binary: str):
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60,
                             env=child_env()).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in m.groups()) if m else None


def extract_json(result_ev: dict | None, required_key: str):
    if not result_ev:
        return None
    so = result_ev.get("structured_output")
    if isinstance(so, dict) and required_key in so:
        return so
    text = result_ev.get("result") or ""
    dec = json.JSONDecoder()
    found = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and required_key in obj:
            found = obj  # keep the last matching object
    return found


def unchecked_tasks(plan: Path) -> int:
    if not plan.exists():
        return 0
    return len(re.findall(r"^\s*[-*]\s+\[ \]", plan.read_text(encoding="utf-8"), re.M))


def detect_profile() -> str:
    """Guess a stack profile from the files in the working directory (shallow — no deep tree walks)."""
    def read(*names) -> str:
        out = []
        for n in names:
            for f in Path(".").glob(n):
                if f.is_file():
                    out.append(f.read_text(errors="ignore")[:20000])
        return " ".join(out)

    if Path("Package.swift").exists() or list(Path(".").glob("*.xcodeproj")) or list(Path(".").glob("*.xcworkspace")):
        swift = read("Package.swift", "*.xcodeproj/project.pbxproj", "*/Info.plist")
        return "swift-ios" if ("IPHONEOS_DEPLOYMENT_TARGET" in swift or "platform=iOS" in swift
                               or ".iOS(" in swift) else "swift-macos"
    if Path("Cargo.toml").exists():
        cargo = read("Cargo.toml", "*/Cargo.toml")
        return "rust-tui" if any(k in cargo for k in ("ratatui", "crossterm", "cursive", "termion")) else "generic"
    if Path("manage.py").exists() or list(Path(".").glob("*/manage.py")):
        spa = Path("frontend").exists() or Path("package.json").exists()
        return "django-react" if spa else "django-htmx"
    py = read("pyproject.toml", "requirements*.txt", "requirements*.in", "*/pyproject.toml", "*/requirements*.txt")
    if "fastapi" in py.lower():
        return "fastapi-react"
    return "generic"


def available_profiles() -> list[str]:
    return sorted(f.stem for f in PROFILES_DIR.glob("*.md") if f.stem != "README")


# ----------------------------------------------------------------------------- usage guard
class UsageGuard:
    """Tracks 5h / 7d utilization from the (undocumented) OAuth usage endpoint and from
    `rate_limit_event`s in the stream. Values are percentages 0..100."""

    def __init__(self, threshold: float, weekly_threshold: float):
        self.threshold = threshold
        self.weekly_threshold = weekly_threshold
        self.five = self.five_reset = self.week = self.week_reset = None
        self.rejected = False
        self.rejected_reset = None
        self.api_ok = None
        self._last = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def token():
        if os.environ.get("AUTODEV_OAUTH_TOKEN"):
            return os.environ["AUTODEV_OAUTH_TOKEN"]
        blobs = []
        cfg_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        cred = cfg_dir / ".credentials.json"
        if cred.exists():
            blobs.append(cred.read_text(encoding="utf-8", errors="ignore"))
        if sys.platform == "darwin" and shutil.which("security"):
            service = os.environ.get("AUTODEV_KEYCHAIN_SERVICE", "Claude Code-credentials")
            r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                blobs.append(r.stdout)
        for b in blobs:
            try:
                tok = (json.loads(b).get("claudeAiOauth") or {}).get("accessToken")
            except (ValueError, AttributeError):
                continue
            if tok:
                return tok
        return None

    def refresh(self, force=False) -> None:
        if not force and time.time() - self._last < 90:
            return
        self._last = time.time()
        tok = self.token()
        if not tok:
            if self.api_ok is None:
                log("WARN usage API: OAuth token not found (set AUTODEV_OAUTH_TOKEN). "
                    "Falling back to stream rate-limit events and limit errors.")
            self.api_ok = False
            return
        req = urllib.request.Request(USAGE_ENDPOINT, headers={
            "Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json", "User-Agent": "autodev/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
        except Exception as e:  # noqa: BLE001
            if self.api_ok is not False:
                log(f"WARN usage API unavailable ({e}); falling back to stream events / limit errors")
            self.api_ok = False
            return
        self.api_ok = True
        with self._lock:
            fh, sd = data.get("five_hour") or {}, data.get("seven_day") or {}
            self.five = float(fh.get("utilization") or 0)
            self.five_reset = to_epoch(fh.get("resets_at"))
            self.week = float(sd.get("utilization") or 0)
            self.week_reset = to_epoch(sd.get("resets_at"))
            self.rejected = False

    def observe(self, info: dict) -> None:
        with self._lock:
            kind = info.get("rateLimitType") or info.get("rate_limit_type")
            util = info.get("utilization")
            pct = None if util is None else (float(util) * 100 if float(util) <= 1.0 else float(util))
            reset = to_epoch(info.get("resetsAt") or info.get("resets_at"))
            if kind in (None, "five_hour"):
                if pct is not None:
                    self.five = pct
                if reset:
                    self.five_reset = reset
            elif str(kind).startswith("seven_day"):
                if pct is not None:
                    self.week = max(self.week or 0, pct)
                if reset:
                    self.week_reset = reset
            if info.get("status") == "rejected":
                self.rejected = True
                self.rejected_reset = reset

    def over(self):
        now = time.time()
        with self._lock:
            if self.five_reset and now > self.five_reset + RESET_BUFFER_S:
                self.five, self.five_reset = None, None
            if self.week_reset and now > self.week_reset + RESET_BUFFER_S:
                self.week, self.week_reset = None, None
            if self.rejected_reset and now > self.rejected_reset + RESET_BUFFER_S:
                self.rejected, self.rejected_reset = False, None
            if self.rejected:
                return True, "usage limit reached", self.rejected_reset or self.five_reset
            if self.week is not None and self.week >= self.weekly_threshold:
                return True, f"weekly usage {self.week:.0f}% ≥ {self.weekly_threshold:.0f}%", self.week_reset
            if self.five is not None and self.five >= self.threshold:
                return True, f"5h usage {self.five:.0f}% ≥ {self.threshold:.0f}%", self.five_reset
        return False, "", None

    def forget_event_values(self) -> None:
        with self._lock:
            if self.api_ok is not True:
                self.five = self.week = None
            self.rejected, self.rejected_reset = False, None

    def describe(self) -> str:
        f = f"{self.five:.0f}%" if self.five is not None else "?"
        w = f"{self.week:.0f}%" if self.week is not None else "?"
        return f"5h {f} (reset {hm(self.five_reset)}) · 7d {w}"


# ----------------------------------------------------------------------------- GitHub
class GitHub:
    """Acts as one explicit gh account without touching gh's active-account config:
    token from `gh auth token --user`, GH_TOKEN for gh calls, a one-shot credential helper for git push."""

    def __init__(self, user: str, host: str = "github.com", repo_override: str = "", remote: str = "origin"):
        self.user, self.host, self.repo_override, self.remote = user, host, repo_override.strip(), remote
        self.token = self.login = self.name = self.email = self.repo = None
        self.repo_from_remote = False
        self.can_push = False

    def _env(self) -> dict:
        env = dict(os.environ)
        env.pop("GITHUB_TOKEN", None)
        env["GH_PROMPT_DISABLED"] = "1"
        if self.host == "github.com":
            env["GH_TOKEN"] = self.token
        else:
            env["GH_HOST"], env["GH_ENTERPRISE_TOKEN"] = self.host, self.token
        return env

    def gh(self, *args, check=True) -> str:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, env=self._env(), timeout=180)
        if check and r.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args[:2])} failed: {one_line(r.stderr or r.stdout, 300)}")
        return r.stdout.strip()

    def connect(self) -> "GitHub":
        if not shutil.which("gh"):
            raise RuntimeError("gh CLI not found (brew install gh)")
        r = subprocess.run(["gh", "auth", "token", "--hostname", self.host, "--user", self.user],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError(f"gh has no token for account '{self.user}' on {self.host} — log in once with "
                               f"`gh auth login --hostname {self.host}` ({one_line(r.stderr, 160)})")
        self.token = r.stdout.strip()
        me = json.loads(self.gh("api", "user"))
        self.login = me["login"]
        if self.login.lower() != self.user.lower():
            raise RuntimeError(f"token for '{self.user}' belongs to '{self.login}'")
        self.name = me.get("name") or self.login
        self.email = (f"{me['id']}+{self.login}@users.noreply.github.com" if self.host == "github.com"
                      else (me.get("email") or ""))
        return self

    def resolve_repo(self):
        if self.repo_override:
            self.repo = re.sub(r"\.git$", "", self.repo_override)
        else:
            url = git("remote", "get-url", self.remote, check=False)
            m = re.search(r"(?:^https?://(?:[^@/]+@)?|^ssh://git@|^git@)" + re.escape(self.host)
                          + r"[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
            self.repo = m.group(1) if m else None
            self.repo_from_remote = bool(m)
        if self.repo:
            self.can_push = self.gh("api", f"repos/{self.repo}", "--jq", ".permissions.push", check=False) == "true"
        return self.repo

    def push(self, branch: str) -> None:
        env = {**os.environ, "AUTODEV_GH_LOGIN": self.login, "AUTODEV_GH_TOKEN": self.token,
               "GIT_TERMINAL_PROMPT": "0"}
        cmd = ["git", "-c", "credential.helper=", "-c", f"credential.https://{self.host}.helper=",
               "-c", f"credential.helper={PUSH_HELPER}",
               "push", f"https://{self.host}/{self.repo}.git", f"HEAD:refs/heads/{branch}"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=900)
        if r.returncode != 0:
            raise RuntimeError(one_line(r.stderr or r.stdout, 400))
        if self.repo_from_remote:  # keep `git status` / upstream tracking sane locally
            git("update-ref", f"refs/remotes/{self.remote}/{branch}", "HEAD", check=False)
            git("config", f"branch.{branch}.remote", self.remote, check=False)
            git("config", f"branch.{branch}.merge", f"refs/heads/{branch}", check=False)

    def sync_pr(self, branch: str, base: str, title: str, body_md: str) -> str:
        body_file = AD / "logs" / "pr_body.md"
        atomic_write(body_file, body_md[:60000])
        url = self.gh("pr", "list", "--repo", self.repo, "--head", branch, "--state", "open",
                      "--json", "url", "--jq", '.[0].url // ""')
        if url:
            self.gh("pr", "edit", url, "--repo", self.repo, "--body-file", str(body_file))
            return url
        out = self.gh("pr", "create", "--repo", self.repo, "--head", branch, "--base", base, "--draft",
                      "--title", title, "--body-file", str(body_file))
        return out.splitlines()[-1] if out else ""


# ----------------------------------------------------------------------------- orchestrator
class Orchestrator:
    def __init__(self, state: dict):
        self.state = state
        self.cfg = state["config"]
        self.guard = UsageGuard(self.cfg["threshold"], self.cfg["weekly_threshold"])
        self.child: subprocess.Popen | None = None
        self.surface_proc: subprocess.Popen | None = None
        self.stop_flag = False
        self.supports_prompts_none = False
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
        global _log_path
        (AD / "logs").mkdir(parents=True, exist_ok=True)
        _log_path = AD / "autodev.log"

        gi = AD / ".gitignore"
        if not gi.exists():
            gi.write_text("logs/\nguides/\nstate.json\nstate.json.tmp\nrun.pid\nSTOP\n"
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
            cur = git("rev-parse", "--abbrev-ref", "HEAD")
            st["base_branch"] = cur
            if self.cfg.get("branch") and not cur.startswith("autodev/"):
                cur = f"autodev/{slugify(Path(st['spec']).stem)}-{datetime.now():%Y%m%d-%H%M}"
                git("checkout", "-q", "-b", cur)
            st["branch"] = cur
            git("add", "-A")
            if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
                git("commit", "-q", "-m", "autodev: snapshot before autonomous run")
                log("committed pre-run snapshot of uncommitted changes")

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

    def _on_signal(self, signum, _frame):
        if self.stop_flag:
            if self.child and self.child.poll() is None:
                self.child.kill()
            raise SystemExit(130)
        self.stop_flag = True
        log(f"signal {signum}: stopping (interrupting the current session; send again to force)")

    def check_stop(self) -> None:
        if self.stop_flag:
            raise StopRequested("signal")
        if STOP_FILE.exists():
            STOP_FILE.unlink()
            raise StopRequested("STOP file")

    # ---- claude sessions -------------------------------------------------------
    def _interrupt(self, proc: subprocess.Popen) -> None:
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
        proc.kill()
        proc.wait()

    def run_claude(self, label, prompt, model, schema, resume=None, extra_disallowed=()):
        cfg, st = self.cfg, self.state
        st["session_counter"] = st.get("session_counter", 0) + 1
        base = AD / "logs" / f"{st['session_counter']:03d}-{label}"
        cmd = [cfg["claude_bin"], "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--model", model, "--json-schema", json.dumps(schema), "--append-system-prompt", self.autonomy,
               "--permission-mode", "bypassPermissions" if cfg["permission_mode"] == "bypass" else "auto"]
        if self.supports_prompts_none:
            cmd += ["--permission-prompts", "none"]
        cmd += ["--disallowedTools", ",".join(["AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
                                               *extra_disallowed])]
        if resume:
            cmd += ["--resume", resume]

        out = {"session_id": resume, "result": None, "interrupted": None, "rejected": False, "exit": None}
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
                        out["session_id"] = sid
                        st["active_session"] = {"label": label, "session_id": sid}
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
            while proc.poll() is None:
                time.sleep(2)
                if proc.poll() is not None:
                    break
                if self.stop_flag:
                    out["interrupted"] = "stop"
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
            os.killpg(proc.pid, signal.SIGKILL)
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
                os.killpg(proc.pid, sig)
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
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                except (ProcessLookupError, OSError):
                    pass
        self._kill_surface_proc()

    def run_e2e(self, pdir: Path):
        cmd = self.e2e_command()
        if not cmd:
            return True, "no e2e command configured — skipped"
        log(f"running e2e: {cmd}")
        return self._shell(cmd, self.cfg["e2e_timeout"], pdir / "E2E_OUTPUT.txt", "e2e suite")

    def commit(self, message: str, body: str) -> str | None:
        git("add", "-A")
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return None
        r = subprocess.run(["git", "commit", "-q", "-m", message, "-m", body], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"WARN git commit failed (hooks?): {one_line(r.stderr or r.stdout, 300)} — retrying --no-verify")
            git("commit", "-q", "--no-verify", "-m", message, "-m", body + "\n\n[autodev] commit hooks failed; "
                "committed with --no-verify")
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

    def step_phase(self) -> None:
        st, cfg = self.state, self.cfg
        i = st["phase_index"]
        ph, n, total = st["phases"][i], i + 1, len(st["phases"])
        ctx = st.setdefault("phase_ctx", {})
        pdir = self.phase_dir(i)
        pdir.mkdir(parents=True, exist_ok=True)
        proj = st["project"]
        common = dict(n=n, total=total, title=ph["title"], goal=ph["goal"], deliverables=bullets(ph["deliverables"]),
                      acceptance=bullets(ph["acceptance_criteria"]), spec=st["spec"], phase_dir=pdir.as_posix(),
                      test_command=proj.get("test_command") or "(none configured)", lang=cfg["lang"],
                      e2e_command=self.e2e_command() or "(not created yet — build the harness)",
                      e2e_up_command=proj.get("e2e_up_command") or "(nothing to start)",
                      base_sha=ctx.get("base_sha", ""), user_facing="yes" if ph.get("user_facing", True) else "no")
        step = st["step"]
        label = f"p{n:02d}-{step}"

        if step == "plan":
            if not ctx.get("base_sha"):
                ctx.update(base_sha=git("rev-parse", "HEAD"), impl_runs=0, test_fix_attempts=0,
                           review_round=0, warnings=[])
            ph["status"] = "in_progress"
            res = self.session(label, render("plan", **common), cfg["model_plan"], STEP_SCHEMA, "status",
                               recheck=lambda d: self.command_complaint(d, ("test_command",)))
            if res["status"] == "blocked":
                raise StepFailed(f"phase {n} plan blocked: {res.get('summary')}")
            if not (pdir / "PLAN.md").exists():
                raise StepFailed(f"phase {n}: PLAN.md was not created")
            if not cfg["test_cmd"]:
                st["project"]["test_command"] = self.vet_command(
                    "test_command", res.get("test_command") or "", st["project"].get("test_command", ""))
            self.set_step("implement")

        elif step == "implement":
            ctx["impl_runs"] += 1
            res = self.session(label, render("implement", run=ctx["impl_runs"], **common),
                               cfg["model_impl"], STEP_SCHEMA, "status")
            if res["status"] == "blocked":
                raise StepFailed(f"phase {n} implementation blocked: {res.get('summary')}")
            left = unchecked_tasks(pdir / "PLAN.md")
            if (res["status"] == "partial" or left) and ctx["impl_runs"] < cfg["max_impl_runs"]:
                log(f"phase {n}: {left} task(s) left — continuing in a fresh session")
                self.set_step("implement")
            else:
                if left:
                    ctx["warnings"].append(f"{left} PLAN.md task(s) left unchecked")
                self.set_step("test")

        elif step == "test":
            if not (proj.get("test_command") or "").strip():
                ctx["warnings"].append("no test command configured — the unit suite never ran")
            ok, summary = self.run_tests(pdir)
            self.event(f"p{n:02d}-tests", "pass" if ok else "fail", summary)
            if ok:
                # out of review rounds is not a reason to skip end-to-end QA and the documentation
                self.set_step("review" if ctx["review_round"] < cfg["max_review_rounds"]
                              else self.after_review(ph))
            elif ctx["test_fix_attempts"] >= cfg["max_test_fix"]:
                raise StepFailed(f"phase {n}: tests still failing after {ctx['test_fix_attempts']} fix attempts "
                                 f"(see {pdir.as_posix()}/TEST_OUTPUT.txt)")
            else:
                self.set_step("test_fix")

        elif step == "test_fix":
            ctx["test_fix_attempts"] += 1
            res = self.session(f"{label}{ctx['test_fix_attempts']}",
                               render("test_fix", attempt=ctx["test_fix_attempts"], max=cfg["max_test_fix"], **common),
                               cfg["model_impl"], STEP_SCHEMA, "status")
            if res["status"] == "blocked":
                raise StepFailed(f"phase {n} test fix blocked: {res.get('summary')}")
            self.set_step("test")

        elif step == "review":
            ctx["review_round"] += 1
            r = ctx["review_round"]
            git("add", "-A")  # so `git diff <base>` also shows new files
            prev = (f"- Previous review: `{pdir.as_posix()}/REVIEW-r{r - 1}.md` — check its blocker/major "
                    "findings were really fixed." if r > 1 else "")
            res = self.session(f"{label}{r}", render("review", round=r, previous_review=prev, **common),
                               cfg["model_review"], REVIEW_SCHEMA, "verdict",
                               extra_disallowed=("Edit", "Write", "NotebookEdit"))
            if "verdict" not in res:
                ctx["warnings"].append(f"review round {r} did not complete")
                self.set_step(self.after_review(ph))
                return
            findings = res.get("findings") or []
            md = [f"# Review — phase {n} round {r}", "", f"**Verdict:** {res['verdict']}", "", res.get("summary", ""), ""]
            for f in findings:
                md += [f"## [{f.get('severity', '?').upper()}] {f.get('title', '')}",
                       f"`{f.get('file', '')}`" if f.get("file") else "", "", f.get("detail", ""), ""]
                if f.get("suggested_fix"):
                    md += [f"**Fix:** {f['suggested_fix']}", ""]
            atomic_write(pdir / f"REVIEW-r{r}.md", "\n".join(md))
            blocking = [f for f in findings if f.get("severity") in BLOCKING]
            self.set_step("review_fix" if blocking else self.after_review(ph))

        elif step == "review_fix":
            r = ctx["review_round"]
            res = self.session(f"{label}{r}", render("review_fix", round=r, **common),
                               cfg["model_impl"], STEP_SCHEMA, "status")
            if res["status"] == "blocked":
                ctx["warnings"].append(f"review fixes round {r} blocked: {one_line(res.get('summary'), 120)}")
            if r >= cfg["max_review_rounds"]:
                ctx["warnings"].append(f"review round {r} had blocker/major findings; fixes applied, not re-reviewed")
            ctx["test_fix_attempts"] = 0
            self.set_step("test")

        elif step == "e2e":
            ctx["e2e_runs"] = ctx.get("e2e_runs", 0) + 1
            started = self.surfaces_up()
            try:
                if not started:
                    ctx["warnings"].append("e2e skipped: the surfaces could not be started")
                    log("WARN e2e surfaces did not start — skipping the e2e step for this phase")
                    self.set_step(self.after_e2e())
                    return
                res = self.session(label, render("e2e", **common), cfg["model_qa"], E2E_SCHEMA, "status",
                                   recheck=lambda d: self.command_complaint(
                                       d, ("e2e_command", "e2e_up_command", "e2e_down_command")))
                for key, cfg_key in (("e2e_command", "e2e_cmd"), ("e2e_up_command", "e2e_up_cmd"),
                                     ("e2e_down_command", "e2e_down_cmd")):
                    if not cfg.get(cfg_key):
                        st["project"][key] = self.vet_command(key, res.get(key) or "",
                                                              st["project"].get(key, ""))
                if res["status"] == "blocked":
                    ctx["warnings"].append(f"e2e blocked: {one_line(res.get('summary'), 160)}")
                    self.set_step(self.after_e2e())
                    return
                if not self.e2e_command():
                    ctx["warnings"].append("no e2e command configured — the end-to-end suite never ran")
                ok, summary = self.run_e2e(pdir)
                self.event(f"p{n:02d}-e2e", "pass" if ok else "fail", summary)
                if ok:
                    self.set_step(self.after_e2e())
                elif ctx.get("e2e_fix_attempts", 0) >= cfg["max_e2e_fix"]:
                    ctx["warnings"].append(f"e2e still failing after {cfg['max_e2e_fix']} fix attempts "
                                           f"({summary}) — see {pdir.as_posix()}/E2E_OUTPUT.txt")
                    self.set_step(self.after_e2e())
                else:
                    self.set_step("e2e_fix")
            finally:
                if started and st["step"] not in ("e2e_fix", "e2e"):
                    self.surfaces_down()

        elif step == "e2e_fix":
            ctx["e2e_fix_attempts"] = ctx.get("e2e_fix_attempts", 0) + 1
            started = self.surfaces_up()
            try:
                if not started:
                    ctx["warnings"].append("e2e fix skipped: the surfaces could not be started")
                    self.set_step(self.after_e2e())
                    return
                res = self.session(f"{label}{ctx['e2e_fix_attempts']}",
                                   render("e2e_fix", attempt=ctx["e2e_fix_attempts"], max=cfg["max_e2e_fix"],
                                          **common), cfg["model_impl"], STEP_SCHEMA, "status")
                if res["status"] == "blocked":
                    ctx["warnings"].append(f"e2e fix blocked: {one_line(res.get('summary'), 160)}")
                    self.set_step(self.after_e2e())
                    return
                ok, summary = self.run_e2e(pdir)
                self.event(f"p{n:02d}-e2e", "pass" if ok else "fail", summary)
                if ok:
                    self.set_step(self.after_e2e())
                elif ctx["e2e_fix_attempts"] >= cfg["max_e2e_fix"]:
                    ctx["warnings"].append(f"e2e still failing after {cfg['max_e2e_fix']} fix attempts ({summary})")
                    self.set_step(self.after_e2e())
                else:
                    self.set_step("e2e_fix")
            finally:
                if started and st["step"] != "e2e_fix":
                    self.surfaces_down()
            # the unit suite must still be green after e2e-driven product fixes
            if st["step"] == "docs" or st["step"] == "commit":
                ok, summary = self.run_tests(pdir)
                self.event(f"p{n:02d}-tests", "pass" if ok else "fail", summary + " (after e2e fixes)")
                if not ok:
                    ctx["test_fix_attempts"] = 0
                    self.set_step("test_fix")

        elif step == "docs":
            res = self.session(label, render("docs", **common), cfg["model_impl"], STEP_SCHEMA, "status")
            if res["status"] == "blocked":
                ctx["warnings"].append(f"docs blocked: {one_line(res.get('summary'), 160)}")
            self.set_step("commit")

        elif step == "commit":
            body = [f"Phase {n}/{total}: {ph['goal']}", "", f"Plan & reviews: {pdir.as_posix()}/"]
            if ctx.get("warnings"):
                body += ["", "Warnings:"] + [f"- {w}" for w in ctx["warnings"]]
            sha = self.commit(f"autodev: phase {n:02d} — {ph['title']}", "\n".join(body))
            if sha:
                git("tag", "-f", f"{st['branch']}/phase-{n:02d}", check=False)
            ph.update(status="done", commit=sha, warnings=ctx.get("warnings", []), finished=ts())
            self.event(f"p{n:02d}-commit", "done", sha or "no changes to commit")
            self.notify(f"autodev ✅ phase {n}/{total}: {ph['title']}")
            st["phase_index"], st["phase_ctx"] = i + 1, {}
            self.set_step("plan")
            self.publish()
        else:
            raise StepFailed(f"unknown step {step}")

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
            st["status"] = "stopped"
            self.event("run", "stopped", str(e))
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
def new_state(spec: str, cfg: dict) -> dict:
    return {"version": 1, "spec": spec, "created": ts(), "status": "running", "branch": None, "config": cfg,
            "project": {}, "phases": [], "phase_index": 0, "step": "architect", "phase_ctx": {}, "events": [],
            "session_counter": 0, "active_session": None, "totals": {"sessions": 0, "seconds": 0, "cost_usd": 0.0}}


def cli_overrides(args) -> dict:
    over = {}
    for key in DEFAULTS:
        val = getattr(args, key, None)
        if val is not None:
            over[key] = val
    return over


def cmd_run(args) -> int:
    if args.fresh and AD.exists():
        bak = Path(f".autodev.bak-{datetime.now():%Y%m%d-%H%M%S}")
        AD.rename(bak)
        print(f"moved previous run to {bak}")
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state["config"] = {**DEFAULTS, **state["config"], **cli_overrides(args)}
        print(f"resuming run: status={state['status']} step={state['step']}")
    else:
        if not args.spec or not Path(args.spec).is_file():
            sys.exit("--spec must point to an existing file for a new run")
        AD.mkdir(exist_ok=True)
        state = new_state(Path(args.spec).as_posix(), {**DEFAULTS, **cli_overrides(args)})
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
    if STATE_FILE.exists():
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        rep("INFO", f"existing run: status={st['status']} step={st['step']} phase_index={st['phase_index']} "
                    "(run resumes it; --fresh starts over)")
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
    run.add_argument("--session-timeout", dest="session_timeout", type=int, help="minutes per session")
    run.add_argument("--test-timeout", dest="test_timeout", type=int, help="minutes")
    run.add_argument("--poll-interval", dest="poll_interval", type=int, help="seconds")
    run.add_argument("--notify-cmd", dest="notify_cmd", help='shell command; message in $AUTODEV_MSG')
    run.add_argument("--lang", help="language of .autodev docs (default English)")
    run.add_argument("--no-branch", dest="branch", action="store_const", const=False)
    run.add_argument("--no-caffeinate", dest="caffeinate", action="store_const", const=False)
    run.add_argument("--claude-bin", dest="claude_bin")
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
