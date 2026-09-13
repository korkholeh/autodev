"""Which commands the orchestrator is willing to run, and how it asks for a better one."""
from __future__ import annotations

import re
from pathlib import Path

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
    "uvicorn", "gunicorn", "hypercorn", "daphne", "granian", "celery", "flask", "honcho", "foreman",
    "pipenv", "pdm", "manage.py", "django-admin", "alembic", "ruff", "mypy", "black", "flake8",
    "pylint", "isort", "bandit",
    "node", "npm", "npx", "pnpm", "yarn", "bun", "bunx", "deno", "vitest", "jest", "mocha",
    "playwright", "cypress", "eslint", "prettier", "tsc", "vite", "turbo", "nx", "lerna", "rush",
    "cargo", "rustup", "rustc",
    "go", "gotestsum", "golangci-lint",
    "swift", "xcodebuild", "xcrun", "fastlane", "swiftlint", "swiftformat", "swift-format", "xcpretty", "xcbeautify",
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

# `docker` and friends have to stay in the allowlist — a compose project runs its suite through them —
# but `docker run -v /:/host` mounts the machine into a container that runs as root, which walks
# straight past "nothing may write outside the repository". So a container run may only mount paths
# inside the working directory, and may not ask for privileges.
CONTAINER_HEADS = {"docker", "podman", "docker-compose", "podman-compose", "nerdctl"}
VOLUME_SOURCES = re.compile(r"(?:^|\s)(?:-v|--volume)[=\s]+([^\s:]+)")
MOUNT_SOURCES = re.compile(r"(?:^|\s)--mount[=\s]+(\S+)")
MOUNT_SOURCE_FIELD = re.compile(r"(?:^|,)(?:source|src)=([^,]+)")
PRIVILEGE_FLAGS = re.compile(r"(?:^|\s)(--privileged|--cap-add(?:[=\s]|$)|--pid[=\s]*host|"
                             r"--userns[=\s]*host|--security-opt)")


def container_problem(segment: str):
    """Why this container command is refused, or None. See the note above CONTAINER_HEADS."""
    flag = PRIVILEGE_FLAGS.search(segment)
    if flag:
        return f"`{flag.group(1).strip()}` gives the container the host"
    sources = VOLUME_SOURCES.findall(segment)
    for spec in MOUNT_SOURCES.findall(segment):
        sources += MOUNT_SOURCE_FIELD.findall(spec)
    for src in sources:
        src = src.strip("\'\"")
        if src.startswith(("/", "~")) or src.startswith("..") or "/../" in src:
            return f"it mounts `{src}` from outside the repository"
    return None


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
        if head in CONTAINER_HEADS:
            why = container_problem(segment)
            if why:
                return False, why
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


