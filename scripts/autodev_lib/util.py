"""Paths, logging, git, and the small helpers every other part uses."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent   # the installed skill directory
PROMPTS_DIR = SKILL_DIR / "prompts"
GUIDES_DIR = SKILL_DIR / "guides"
PROFILES_DIR = SKILL_DIR / "profiles"
AD = Path(".autodev")
STATE_FILE = AD / "state.json"
STOP_FILE = AD / "STOP"
PID_FILE = AD / "run.pid"
SURFACE_LOG = AD / "logs" / "e2e-surfaces.log"


class StepFailed(Exception):
    pass


class StopRequested(Exception):
    pass


_log_path: Path | None = None


def set_log_path(path: "Path | None") -> None:
    """Also append everything log() prints to this file."""
    global _log_path
    _log_path = path


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


def render(name: str, **kw) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    for k, v in kw.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def child_env() -> dict:
    """Environment for the processes the orchestrator starts.

    Two things go: the markers of an enclosing Claude Code session, otherwise a nested `claude`
    may refuse to start; and every AUTODEV_* variable, so neither a session nor a test command
    inherits the orchestrator's own credentials — AUTODEV_OAUTH_TOKEN above all."""
    env = dict(os.environ)
    for k in list(env):
        if k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT") or k.startswith("AUTODEV_"):
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


def claude_flags(binary: str) -> set:
    """The long options this build of Claude Code accepts, read once from --help.

    Used to fence a session in only with options it actually has, rather than guessing from the
    version number and failing the first session of the night."""
    try:
        out = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=60,
                             env=child_env()).stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return set(re.findall(r"--[a-z][a-z0-9-]+", out))


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


# A test run's last line is not its result: `cargo test` ends with a doc-test block that always
# reads `0 passed; 0 failed`, so a summary taken from the tail reported every suite in the run as
# having run nothing. Each family is recognised by the shape of its own summary line instead.
TEST_FAMILIES = (
    ("cargo", re.compile(r"^\s*test result:", re.I), "sum"),
    ("pytest", re.compile(r"^=+.*\b\d+\s+(?:passed|failed|error|skipped)", re.I), "last"),
    ("jest", re.compile(r"^\s*Tests:\s+\d", re.I), "last"),
    ("xcode", re.compile(r"\bExecuted \d+ tests?,", re.I), "last"),
    ("go", re.compile(r"^(?:ok\s|FAIL\b|---\s+FAIL)"), "go"),
)
_COUNT = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped)\b", re.I)
_XCODE = re.compile(r"Executed (\d+) tests?, with (\d+) failures?", re.I)


def _counts(line: str) -> dict:
    """passed / failed / skipped read out of one summary line, whatever the runner calls them."""
    m = _XCODE.search(line)
    if m:
        total, failed = int(m.group(1)), int(m.group(2))
        return {"passed": max(total - failed, 0), "failed": failed, "skipped": 0}
    out = {"passed": 0, "failed": 0, "skipped": 0}
    for n, word in _COUNT.findall(line):
        word = word.lower()
        key = "failed" if word.startswith("error") else word
        out[key] = out.get(key, 0) + int(n)
    return out


def test_summary(output: str) -> tuple[str, int | None]:
    """(one-line summary of a test run, number of tests that actually ran).

    The count is `None` when no family is recognised — the caller then falls back to the tail of
    the output, which is all an unknown runner offers. A recognised run of zero tests says so:
    a suite that certifies nothing must not read as a green suite."""
    lines = (output or "").splitlines()
    for name, matcher, how in TEST_FAMILIES:
        hits = [ln for ln in lines if matcher.search(ln)]
        if not hits:
            continue
        if how == "go":
            # `go test` names each failing test and then fails its package, so counting both
            # reports one broken test twice: prefer the named tests when there are any.
            named = [ln for ln in hits if ln.startswith("---")]
            failed = len(named) or sum(1 for ln in hits if ln.startswith("FAIL"))
            ok = sum(1 for ln in hits if ln.startswith("ok"))
            return f"{ok} package(s) ok, {failed} failing", None
        totals = {"passed": 0, "failed": 0, "skipped": 0}
        for c in ([_counts(hits[-1])] if how == "last" else [_counts(ln) for ln in hits]):
            for k, v in c.items():
                totals[k] = totals.get(k, 0) + v
        ran = totals["passed"] + totals["failed"]
        if not ran and not totals["skipped"]:
            return "no tests ran", 0
        text = f"{totals['passed']} passed, {totals['failed']} failed"
        if totals["skipped"]:
            text += f", {totals['skipped']} skipped"
        return (text if ran else f"no tests ran ({text})"), ran
    return "", None


def turn_context(usage: dict) -> int:
    """How much conversation one assistant turn was billed to read.

    Cached or not, every token of it is re-read on the next turn too, which is why a long session
    costs so much more than the same work split across fresh ones."""
    return sum(int((usage or {}).get(k) or 0) for k in
               ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def dropped_tasks(plan: Path) -> list[str]:
    """The `- [~]` lines of a plan: tasks a session decided not to do, with its reason."""
    if not plan.exists():
        return []
    return re.findall(r"^\s*[-*]\s+\[~\].*$", plan.read_text(encoding="utf-8"), re.M)


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
    py = py.lower()
    if "fastapi" in py:
        return "fastapi-react"
    if "textual" in py:
        return "python-textual"
    return "generic"


def available_profiles() -> list[str]:
    return sorted(f.stem for f in PROFILES_DIR.glob("*.md") if f.stem != "README")


