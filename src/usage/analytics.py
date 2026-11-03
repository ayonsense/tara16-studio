# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Coordinate background local counters and PostHog product analytics."""

from pathlib import Path
import hashlib
import os
import uuid

from src.usage import config as analytics_config
from src.usage.posthog import PostHogReporter, _extra_properties
from src.usage.stats import FEATURES, UsageStats


def _project_outbox_path(database_path):
    """Keep queued events scoped to their configured capture destination."""
    token = os.environ.get("TARA_POSTHOG_PROJECT_TOKEN", analytics_config.POSTHOG_PROJECT_TOKEN).strip()
    host = os.environ.get("TARA_POSTHOG_HOST", analytics_config.POSTHOG_HOST).strip().rstrip("/").lower()
    scope = hashlib.sha256((host + "\n" + token).encode("utf-8")).hexdigest()[:16]
    return Path(database_path).with_suffix(".posthog-" + scope + ".json")


class UsageAnalytics:
    """Keep the app independent of transport availability and network timing."""

    def __init__(self, local=None, reporter=None):
        self.local = local if local is not None else UsageStats()
        identifier = self.local.get_preference("installation_id")
        if not identifier:
            identifier = uuid.uuid4().hex
            self.local.set_preference("installation_id", identifier)
        # Background reporting replaces the old in-app collection controls.
        # A deployment switch remains available for tests and managed labs.
        self._reporting_allowed = os.environ.get("TARA_ANALYTICS_ENABLED", "1").strip().lower() not in (
            "0", "false", "no", "off") and analytics_config.USAGE_REPORTING_ENABLED
        self.local.set_enabled(bool(self._reporting_allowed))
        initial = self.local.snapshot()
        sharing = bool(initial["available"] and initial["enabled"] and self._reporting_allowed)
        self._cloud_enabled = bool(self._reporting_allowed)
        self.reporter = reporter if reporter is not None else PostHogReporter(
            identifier, path=_project_outbox_path(self.local.path), enabled=sharing)
        self._active_pending = {feature: 0.0 for feature in FEATURES}
        self._closed = False
        self._cloud_launch_recorded = False
        self._session_started = False
        self._sync_reporting()

    def _sync_reporting(self):
        snapshot = self.local.snapshot()
        enabled = bool(snapshot["available"] and snapshot["enabled"]
                       and self._cloud_enabled and self._reporting_allowed)
        self.reporter.set_enabled(enabled)
        return enabled

    def _capture(self, event, properties=None):
        if self._sync_reporting():
            self.reporter.capture(event, properties)

    def start_session(self):
        if self._session_started:
            return False
        self._session_started = True
        accepted = self.local.start_session()
        if accepted:
            self._capture("app_launches")
            self._cloud_launch_recorded = bool(self.reporter.enabled and self.reporter.configured)
        return accepted

    def record(self, event, properties=None):
        # Validate at the boundary so invalid metadata cannot affect totals.
        extra = _extra_properties(event, properties)
        if extra is None:
            return False
        accepted = self.local.record(event)
        if accepted:
            self._capture(event, extra or None)
        return accepted

    def add_active_time(self, feature, seconds):
        accepted = self.local.add_active_time(feature, seconds)
        if accepted and self._sync_reporting():
            self._active_pending[feature] += float(seconds)
            if self._active_pending[feature] >= 60:
                self._send_active(feature)
        return accepted

    def _send_active(self, feature):
        seconds = self._active_pending[feature]
        if seconds:
            self.reporter.capture("active_time", {"feature": feature, "seconds": round(seconds, 3)})
            self._active_pending[feature] = 0.0

    def snapshot(self):
        result = self.local.snapshot()
        self._sync_reporting()
        result["cloud"] = self.reporter.status_snapshot()
        result["cloud"]["enabled"] = bool(self._cloud_enabled and self._reporting_allowed)
        return result

    def set_enabled(self, enabled):
        accepted = self.local.set_enabled(enabled)
        if accepted:
            self._active_pending = dict.fromkeys(FEATURES, 0.0)
            self._sync_reporting()
        return accepted

    def set_cloud_enabled(self, enabled):
        accepted = isinstance(enabled, bool)
        if accepted:
            self._cloud_enabled = enabled
            self._active_pending = dict.fromkeys(FEATURES, 0.0)
            self._sync_reporting()
            if (enabled and self._session_started and not self._cloud_launch_recorded
                    and self.reporter.configured and self.reporter.enabled):
                # Count this launch once if sharing is enabled mid-session;
                # do not upload any earlier local history.
                self.reporter.capture("app_launches")
                self._cloud_launch_recorded = True
        return accepted

    def reset(self):
        accepted = self.local.reset()
        if accepted:
            self._active_pending = dict.fromkeys(FEATURES, 0.0)
            self.reporter.set_enabled(False)
            self._sync_reporting()
        return accepted

    def export(self, path):
        return self.local.export(path)

    def flush(self, timeout=0.2):
        if self._sync_reporting():
            for feature in FEATURES:
                self._send_active(feature)
        self.local.flush()
        self.reporter.flush(timeout=timeout)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.flush()
        self.reporter.close(timeout=0.2)
        self.local.close()
