"""Acting as one explicit gh account: commits, pushes and the draft pull request."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from .util import AD, atomic_write, git, one_line

# git credential helper that answers only for this push, from env vars (token never hits argv or disk)
PUSH_HELPER = ('!f() { test "$1" = get || exit 0; echo "username=${AUTODEV_GH_LOGIN}"; '
               'echo "password=${AUTODEV_GH_TOKEN}"; }; f')

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

    def remote_url(self) -> str:
        return f"https://{self.host}/{self.repo}.git"

    def push_command(self, branch: str) -> list:
        """The push argv. The token lives in this process's environment, so nothing else may run here.

        A pre-push hook would run with that environment, and a hook is a file in the repository that
        a session can write. It is turned off for this one command, in two ways, rather than trusted:
        autodev has already run the suite before committing, so there is nothing for it to add."""
        return ["git", "-c", "credential.helper=", "-c", f"credential.https://{self.host}.helper=",
                "-c", f"credential.helper={PUSH_HELPER}", "-c", "core.hooksPath=/dev/null",
                "push", "--no-verify", self.remote_url(), f"HEAD:refs/heads/{branch}"]

    def push(self, branch: str) -> None:
        env = {**os.environ, "AUTODEV_GH_LOGIN": self.login, "AUTODEV_GH_TOKEN": self.token,
               "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(self.push_command(branch), capture_output=True, text=True, env=env, timeout=900)
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


