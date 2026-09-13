"""The usage guard: how close this account is to its 5-hour and 7-day limits."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .util import hm, log, to_epoch

USAGE_ENDPOINT = os.environ.get("AUTODEV_USAGE_ENDPOINT", "https://api.anthropic.com/api/oauth/usage")
RESET_BUFFER_S = int(os.environ.get("AUTODEV_RESET_BUFFER", "120"))

PCT_KEYS = ("utilization_percent", "utilizationPercent", "percent_used", "percentUsed")
USED_PAIRS = (("used", "limit"), ("used_tokens", "limit_tokens"), ("usedTokens", "limitTokens"))


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def percent_used(info: dict):
    """How much of a window is used, in percent, or None if the payload does not say.

    `utilization` has been seen on both scales and the number alone cannot settle which: a 1 is
    either one percent or a window that is full. So an unambiguous pair (used/limit) is read first,
    then a field that names its own unit, and only then `utilization` — where a value below 1 is
    taken as a fraction and anything else as a percentage already.

    That leaves exactly 1 read as 1%. Being wrong that way costs one more request, and the limit
    error it comes back with pauses the run anyway; being wrong the other way parks the night on a
    window that was barely touched."""
    if not isinstance(info, dict):
        return None
    for used_key, limit_key in USED_PAIRS:
        used, limit = _num(info.get(used_key)), _num(info.get(limit_key))
        if used is not None and limit is not None and limit > 0:
            return used / limit * 100
    for key in PCT_KEYS:
        pct = _num(info.get(key))
        if pct is not None:
            return pct
    util = _num(info.get("utilization"))
    if util is None:
        return None
    return util * 100 if util < 1.0 else util


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
            self.five = percent_used(fh) or 0.0
            self.five_reset = to_epoch(fh.get("resets_at"))
            self.week = percent_used(sd) or 0.0
            self.week_reset = to_epoch(sd.get("resets_at"))
            self.rejected = False

    def observe(self, info: dict) -> None:
        with self._lock:
            kind = info.get("rateLimitType") or info.get("rate_limit_type")
            pct = percent_used(info)
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


