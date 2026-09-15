"""What has to be installed before a run starts, and what to type to install it.

A missing toolchain is the cheapest failure there is and the most expensive one to find late. A
session handed a repository it cannot build does not stop: it works around the gap, writes the
workaround into PLAN.md as a `[~]`, and the morning handoff reads as if the phase was built. So the
compilers and interpreters the chosen profile needs are checked here, once, before the first
session starts — with the command to install what is missing, rather than the name of the binary
that was not found.

Two levels. A **required** tool is one without which the run cannot build or test anything for this
profile, and its absence stops the run. A **recommended** tool only costs a phase some time (a
linter a session installs itself, a browser driver phase 1 has to fetch), and its absence is a
warning.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

XCODE_HINT = ("install Xcode from the App Store, then point the command line at it: "
              "`sudo xcode-select -s /Applications/Xcode.app`")
RUSTUP_HINT = "`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`"
UV_HINT = "`curl -LsSf https://astral.sh/uv/install.sh | sh`"


class Tool:
    """One binary the run needs, and how a person on this machine installs it.

    `binaries` is a list of alternatives — any one of them found on PATH satisfies the tool, which
    is how `uv or pip` and `npx or playwright` are expressed. `probe` is for the binaries that
    exist on PATH without working: `/usr/bin/xcodebuild` ships with the command line tools and
    exits with an error until a full Xcode is selected."""

    def __init__(self, name, why, binaries=(), level="required", hints=None, probe=()):
        self.name = name
        self.why = why
        self.binaries = tuple(binaries) or (name,)
        self.level = level
        self.hints = hints or {}
        self.probe = tuple(probe)

    def install_hint(self, platform=None) -> str:
        p = platform or sys.platform
        key = "darwin" if p == "darwin" else ("linux" if p.startswith("linux") else "other")
        return self.hints.get(key) or self.hints.get("other") or ""

    def check(self) -> "Found":
        path = next((shutil.which(b) for b in self.binaries if shutil.which(b)), "")
        if not path:
            return Found(self, "", f"not found (looked for {', '.join(self.binaries)})")
        if self.probe:
            try:
                r = subprocess.run(self.probe, capture_output=True, text=True, timeout=120,
                                   env={**os.environ, "NO_COLOR": "1"})
            except (OSError, subprocess.SubprocessError) as e:
                return Found(self, "", f"{path} could not be run: {e}")
            if r.returncode != 0:
                detail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[0][:160]
                return Found(self, "", f"`{' '.join(self.probe)}` failed: {detail}")
        return Found(self, path, path)


class Found:
    def __init__(self, tool, path, detail):
        self.tool = tool
        self.path = path
        self.detail = detail

    @property
    def ok(self) -> bool:
        return bool(self.path)

    @property
    def required(self) -> bool:
        return self.tool.level == "required"

    def line(self) -> str:
        """One line for the doctor: what was looked for, what was found, what to type."""
        if self.ok:
            return f"{self.tool.name}: {self.path}"
        hint = self.tool.install_hint()
        return (f"{self.tool.name}: {self.detail} — {self.tool.why}"
                + (f"; install: {hint}" if hint else ""))


def _t(name, why, **kw) -> Tool:
    return Tool(name, why, **kw)


# Needed whatever is being built: the orchestrator commits with git itself, and the skill starts the
# run under tmux so it survives the terminal that launched it.
CORE = [
    _t("git", "every phase is committed, and the run branches and tags",
       hints={"darwin": "`xcode-select --install` (or `brew install git`)",
              "linux": "`sudo apt install git`"}),
    _t("tmux", "keeps an overnight run alive after the terminal that started it closes",
       level="recommended",
       hints={"darwin": "`brew install tmux`", "linux": "`sudo apt install tmux`"}),
]

PYTHON = _t("python3", "runs the backend, its tests and its migrations",
            binaries=("python3", "python"),
            hints={"darwin": "`brew install python`", "linux": "`sudo apt install python3`"})
UV_OR_PIP = _t("uv or pip", "installs the backend's dependencies from the lockfile",
               binaries=("uv", "pip3", "pip"), level="recommended",
               hints={"darwin": UV_HINT + " (or `brew install uv`)", "linux": UV_HINT})
NODE = _t("node", "builds and serves the frontend",
          hints={"darwin": "`brew install node`", "linux": "`sudo apt install nodejs npm`"})
NPM = _t("npm", "installs the frontend's dependencies from the lockfile",
         binaries=("npm", "pnpm", "yarn", "bun"),
         hints={"darwin": "`brew install node`", "linux": "`sudo apt install nodejs npm`"})
BROWSER_E2E = _t("browser e2e driver", "drives the end-to-end specs; phase 1 has to install it otherwise",
                 binaries=("npx", "playwright"), level="recommended",
                 hints={"darwin": "`brew install node`, then `npx playwright install`",
                        "linux": "`sudo apt install nodejs npm`, then `npx playwright install`"})
RUFF = _t("ruff", "the lint and format step of this profile", level="recommended",
          hints={"darwin": "`uv tool install ruff` (or `brew install ruff`)", "linux": "`uv tool install ruff`"})
SWIFT = _t("swift", "compiles and tests the SwiftPM core the app is built on",
           hints={"darwin": XCODE_HINT, "linux": "https://www.swift.org/install/"})
XCODEBUILD = _t("xcodebuild", "builds and tests the app target and the XCUITest e2e layer",
                probe=("xcodebuild", "-version"),
                hints={"darwin": XCODE_HINT,
                       "other": "this profile needs macOS with Xcode"})
SIMCTL = _t("simctl", "boots the simulator the iOS suite and the e2e layer run on",
            binaries=("xcrun",), probe=("xcrun", "simctl", "help"),
            hints={"darwin": "install a simulator runtime in Xcode › Settings › Platforms "
                             "(it comes with Xcode itself — see above if that is missing too)",
                   "other": "this profile needs macOS with Xcode"})
CARGO = _t("cargo", "builds and tests the crate",
           hints={"darwin": RUSTUP_HINT + " (or `brew install rust`)", "linux": RUSTUP_HINT})
RUSTC = _t("rustc", "the compiler cargo drives", hints={"darwin": RUSTUP_HINT, "linux": RUSTUP_HINT})
RUSTFMT = _t("rustfmt", "the format step of this profile", level="recommended",
             hints={"darwin": "`rustup component add rustfmt`", "linux": "`rustup component add rustfmt`"})
CLIPPY = _t("clippy", "the lint step of this profile", binaries=("cargo-clippy",), level="recommended",
            hints={"darwin": "`rustup component add clippy`", "linux": "`rustup component add clippy`"})

PROFILE_TOOLS = {
    "swift-macos": [SWIFT, XCODEBUILD],
    "swift-ios": [SWIFT, XCODEBUILD, SIMCTL],
    "rust-tui": [CARGO, RUSTC, RUSTFMT, CLIPPY],
    "django-htmx": [PYTHON, UV_OR_PIP, RUFF, BROWSER_E2E],
    "django-react": [PYTHON, UV_OR_PIP, RUFF, NODE, NPM, BROWSER_E2E],
    "fastapi-react": [PYTHON, UV_OR_PIP, RUFF, NODE, NPM, BROWSER_E2E],
    "generic": [],
}


def tools_for(profile: str) -> list:
    """Everything a run of this profile is checked for — the core first, then the stack's own."""
    return CORE + PROFILE_TOOLS.get(profile, [])


def check(profile: str) -> list:
    return [t.check() for t in tools_for(profile)]


def missing(results, level="required") -> list:
    return [r for r in results if not r.ok and r.tool.level == level]


def doctor_lines(profile: str) -> list:
    """(level, message) pairs for `doctor` to print — FAIL for a required tool, WARN otherwise."""
    out = []
    for r in check(profile):
        out.append(("OK" if r.ok else ("FAIL" if r.required else "WARN"), "tool " + r.line()))
    if profile == "generic":
        out.append(("INFO", "toolchain: the generic profile names no compiler or interpreter — "
                            "the architect step decides the stack, so check it by hand"))
    return out


def preflight_error(results, profile: str) -> str:
    """What a run says before it stops, when a tool it cannot build without is missing.

    One install line per distinct command, not per tool: on a machine with no Xcode, `swift`,
    `xcodebuild` and `simctl` are one missing thing to fix, and printing the same line three times
    reads like three."""
    gone = missing(results, "required")
    lines = [f"missing toolchain for the `{profile}` profile: " + ", ".join(r.tool.name for r in gone)
             + ". Nothing would build or be tested, and a session handed a broken toolchain works "
               "around it rather than stopping."]
    for r in gone:
        lines.append(f"  - {r.tool.name} — {r.tool.why}"
                     + (f" ({r.detail})" if r.detail and not r.detail.startswith("not found") else ""))
    hints = []
    for r in gone:
        hint = r.tool.install_hint()
        if hint and hint not in hints:
            hints.append(hint)
    if hints:
        lines.append("Install, then run the same command again:")
        lines += [f"  - {h}" for h in hints]
    lines.append("--skip-tool-check runs anyway, on the assumption the toolchain is somewhere this "
                 "check cannot see it.")
    return "\n".join(lines)
