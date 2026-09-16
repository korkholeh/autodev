"""The tooling venv: how `dash` and `report` get the two packages they need, without help.

Everything a run does is stdlib, and that is deliberate — the orchestrator must start at 3am on
whatever `python3` is there. Only the two things a person looks at afterwards want a package:
`textual` for the dashboard, `openpyxl` for the workbook. Rather than send the person off to think
about where those may be installed without polluting the project's own environment, the commands
that need them offer to build one venv of their own, outside every project, and to come back in it.

Three rules keep that honest:
  * it is asked for, never assumed — a command that installs software behind your back is worse
    than one that prints an install line;
  * nothing on the run's path ever calls this: a phase that stopped to install a package at 3am,
    or waited on a network that was not there, is exactly the failure this project exists to avoid;
  * one attempt only — the re-exec carries a marker, so a broken install ends in a message and not
    in a process that starts itself forever.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REEXEC_MARK = "AUTODEV_TOOLING_REEXEC"      # stripped from every session's environment by child_env()
NEEDS = {"textual": "textual", "openpyxl": "openpyxl"}


def tool_venv() -> Path:
    """One venv for the autodev tooling, shared by every project and part of none of them."""
    if os.environ.get("AUTODEV_VENV"):
        return Path(os.environ["AUTODEV_VENV"]).expanduser()
    data = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return data / "autodev" / "venv"


def venv_python(root: "Path | None" = None) -> Path:
    root = root or tool_venv()
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def has_module(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def module_in(python: Path, module: str) -> bool:
    """Whether another interpreter can import it — asked of it, not guessed from its path."""
    try:
        return subprocess.run([str(python), "-c", f"import {module}"], capture_output=True,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def create_venv(root: Path) -> str:
    """Build the venv. Returns "" on success, or why it could not be built."""
    r = subprocess.run([sys.executable, "-m", "venv", str(root)], capture_output=True, text=True)
    if r.returncode:
        detail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        return f"could not create {root}: {detail[0]}"
    return ""


def pip_install(python: Path, package: str) -> str:
    r = subprocess.run([str(python), "-m", "pip", "install", "--quiet", package],
                       capture_output=True, text=True)
    if r.returncode:
        detail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        return f"could not install {package}: {detail[0]}"
    return ""


def reexec(python: Path) -> None:
    """Start this same command again in the tooling venv. Does not return if it works."""
    os.environ[REEXEC_MARK] = "1"
    for stream in (sys.stdout, sys.stderr):
        stream.flush()          # execv does not flush: anything still buffered would be lost
    try:
        os.execv(str(python), [str(python), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
    except OSError:
        pass


def ensure(module: str, why: str, mode: str = "ask", ask=None) -> str:
    """Make `module` importable, by moving into the tooling venv if that is what it takes.

    Returns "present", "declined", "unavailable" (no venv, and not allowed to make one) or the
    reason it failed. "present" is the only answer the caller may act on.

    `mode`: "ask" (the default — a yes/no question, once), "yes" (install without asking) or "no".
    """
    if has_module(module):
        return "present"
    package = NEEDS.get(module, module)
    if os.environ.get(REEXEC_MARK):
        return f"{package} is still not importable after installing it"
    python = venv_python()
    if python.exists() and module_in(python, module):
        reexec(python)                              # already installed from an earlier command
        return f"could not start {python}"
    if mode == "no" or os.environ.get("AUTODEV_NO_BOOTSTRAP"):
        return "unavailable"
    ask = ask or _confirm
    if mode != "yes" and not ask(f"{package} is needed {why}.\n"
                                 f"Install it into {tool_venv()} (nothing is added to this project)? [Y/n] "):
        return "declined"
    root = tool_venv()
    root.parent.mkdir(parents=True, exist_ok=True)
    if not python.exists():
        problem = create_venv(root)
        if problem:
            return problem
    problem = pip_install(python, package)
    if problem:
        return problem
    reexec(python)
    return f"could not start {python}"


def _confirm(question: str) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False                                 # a pipe never gets to say yes on your behalf
    try:
        return (input(question).strip().lower() or "y") in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def advice(module: str, outcome: str) -> str:
    """What to print when `ensure` did not end in "present"."""
    package = NEEDS.get(module, module)
    if outcome == "declined":
        return f"not installed — `{sys.executable} -m pip install {package}` installs it yourself"
    if outcome == "unavailable":
        return (f"{package} is not installed: {venv_python()} -m pip install {package}\n"
                f"  or drop AUTODEV_NO_BOOTSTRAP and run the command again to have it set up for you")
    return f"{outcome}\n  install it yourself: {sys.executable} -m pip install {package}"
