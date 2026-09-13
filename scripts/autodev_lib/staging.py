"""What must never reach a commit.

The orchestrator stages with `git add -A`, because it cannot know which files a phase was supposed
to produce. That takes everything a session left behind too: a `.env` it wrote to run the suite, a
dependency directory installed without a matching gitignore, a build artefact, a browser trace. With
`--pr` those reach GitHub the same night, long before a human reads anything.

So the index is filtered before the commit rather than after. A held-back file stays in the working
tree and is reported; nothing is deleted. The escape is ordinary git: commit the file yourself, and
it stops showing up as a staged change.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# directories that are installed or generated, never authored
JUNK_PATHS = re.compile(
    r"(^|/)(node_modules|\.venv|venv|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.tox|"
    r"\.gradle|\.next|\.nuxt|\.svelte-kit|\.parcel-cache|\.turbo|\.terraform|DerivedData|\.build|"
    r"target/(debug|release)|dist-newstyle|playwright-report|test-results|\.DS_Store|"
    r"e2e/(artifacts|screenshots|traces))(/|$)")

# files that decide what `make test` (or `npm test`, or `just e2e`) actually runs. A session writes
# them as part of its work, and the command vetting only checks the shape of the command it is given,
# so a change here is named in the timeline rather than forbidden.
COMMAND_FILES = re.compile(
    r"(^|/)(GNUmakefile|[Mm]akefile|[Jj]ustfile|Taskfile\.ya?ml|package\.json|pyproject\.toml|"
    r"noxfile\.py|tox\.ini|Rakefile|[Mm]ake\.bat|docker-compose\.ya?ml|compose\.ya?ml)$")

# A manifest is mostly dependencies, and a dependency is not a command: in an npm or uv project the
# manifest changes almost every phase, so naming the file every time would bury the one change worth
# seeing. These two are read more closely (see command_change); the rest of COMMAND_FILES is nothing
# but commands, so any change to them counts.
PYPROJECT_COMMAND_LINE = re.compile(
    r"^[+-](?![+-])\s*(?:\[[^\]]*(?:scripts|entry[-_]points|pytest|ruff|nox|tox)[^\]]*\]|"
    r"(?:addopts|commands|scripts|entry[-_]points|testpaths|session)\s*=)", re.I)


def scripts_of(text: str) -> dict:
    """The `scripts` table of a package.json, or {} when there is none to read."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {"__unreadable__": text or ""}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return scripts if isinstance(scripts, dict) else {}


def command_change(path: str, before: str, after: str, diff: str) -> bool:
    """Whether this staged file changed what the project's commands run.

    `before`/`after` are the file as HEAD has it and as the index has it; `diff` is the staged diff
    for that one path. A file that holds nothing but commands needs neither."""
    name = path.rsplit("/", 1)[-1]
    if name == "package.json":
        return scripts_of(before) != scripts_of(after)
    if name == "pyproject.toml":
        return any(PYPROJECT_COMMAND_LINE.search(line) for line in (diff or "").splitlines())
    return True


# names that normally hold credentials (a .env.example and friends are fine)
SECRET_NAMES = re.compile(
    r"(^|/)(\.env(\.(?!example|sample|template|dist)[\w-]+)?|\.netrc|\.npmrc|\.pypirc|"
    r"id_rsa|id_dsa|id_ecdsa|id_ed25519|credentials|credentials\.json|"
    r"[\w.-]*service[-_]account[\w.-]*\.json|[\w.-]+\.(pem|p12|pfx|jks|keystore))$", re.I)

# what a credential looks like inside a file
SECRET_CONTENT = (
    (re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(rb"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key id"),
    (re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36}\b"), "a GitHub token"),
    (re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{24,}"), "an Anthropic API key"),
    (re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{12,}"), "a Slack token"),
    (re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"), "a Google API key"),
    (re.compile(rb'"private_key"\s*:\s*"-----BEGIN'), "a service account key"),
    (re.compile(rb"\bey[A-Za-z0-9_-]{10,}\.ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "a signed token"),
)
SCAN_LIMIT = 2 * 1024 * 1024      # do not read more than this looking for a secret


def why_not_committable(path: Path, size_limit: int = 0):
    """Why this file must stay out of an automated commit, in a phrase, or None if it may go in."""
    name = path.as_posix()
    if JUNK_PATHS.search(name):
        return "an installed or generated directory"
    if SECRET_NAMES.search(name):
        return "a file that normally holds credentials"
    try:
        size = path.stat().st_size
    except OSError:                      # deleted or renamed since it was staged
        return None
    if size_limit and size > size_limit:
        return f"{size / 1048576:.1f} MB, over the {size_limit // 1048576} MB limit"
    if size > SCAN_LIMIT:
        return None
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    if b"\0" in blob[:8192]:             # binary: nothing here to read as a credential
        return None
    for pattern, what in SECRET_CONTENT:
        if pattern.search(blob):
            return f"it contains what looks like {what}"
    return None
