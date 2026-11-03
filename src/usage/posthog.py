# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Background PostHog product events, with a bounded background outbox.

The GUI only puts validated envelopes in memory. A daemon worker persists and
uploads batches, so network timeouts cannot interrupt compilation or teaching.
The public project token is used only in the HTTPS request, never in the outbox
or status snapshot. Failed requests retain events for a later retry/session.
"""

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
import re
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid

from src.usage import config as analytics_config
from src.paths import CONFIG_DIR
from src.usage.stats import EVENTS, FEATURES
from src.usage.examples import validate_example


MAX_PENDING = 1000
MAX_BATCH = 50
MAX_OUTBOX_BYTES = 2 * 1024 * 1024
HTTP_TIMEOUT = 2.0
BATCH_DELAY = 0.15
MAX_BACKOFF = 60.0
_HOST_REGIONS = {"us.i.posthog.com": "US", "eu.i.posthog.com": "EU"}
_BASE_PROPERTIES = frozenset({
    "app_version", "platform", "session_id", "$session_id", "$process_person_profile", "$geoip_disable",
})
_DESKTOP_PROPERTIES = frozenset({"app_name", "$os", "$device_type"})
_OS_NAMES = {"Windows": "Windows", "Darwin": "Mac OS X", "Linux": "Linux", "unknown": "Unknown"}
_EXAMPLE_EVENTS = frozenset({
    "example_loaded", "program_run", "compile_started", "compile_succeeded", "compile_failed",
    "assembly_started", "assembly_succeeded", "assembly_failed", "fpga_run", "simulator_run",
})
SESSION_IDLE_SECONDS = 30 * 60
SESSION_MAX_SECONDS = 24 * 60 * 60
_EVENT_FIELDS = frozenset({"event", "distinct_id", "timestamp", "uuid", "properties"})
_VERSION_PATTERN = re.compile(r"[A-Za-z0-9.+!_-]{1,64}\Z")


def _public_token(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    # phx_/phs_/pha_ are personal/secret credentials, not capture tokens.
    return value if len(value) <= 256 and re.fullmatch(r"phc_[A-Za-z0-9_-]+", value) else ""


def _capture_host(value):
    if not isinstance(value, str):
        return "", "Unknown"
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        if (parsed.scheme != "https" or hostname not in _HOST_REGIONS
                or parsed.username or parsed.password or parsed.port is not None
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            return "", "Unknown"
        return "https://" + hostname, _HOST_REGIONS[hostname]
    except ValueError:
        return "", "Unknown"


def _uuid(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None


def _app_version():
    try:
        value = version("taracpu")
        return value if _VERSION_PATTERN.fullmatch(value) else "unknown"
    except (PackageNotFoundError, OSError, ValueError, TypeError):
        return "unknown"


def _session_uuid(now):
    """UUIDv7 for Python 3.9+, with a millisecond timestamp and random suffix."""
    milliseconds = int(now * 1000)
    random = uuid.uuid4().int
    value = ((milliseconds & ((1 << 48) - 1)) << 80
             | 7 << 76 | ((random >> 64) & 0xfff) << 64
             | 2 << 62 | (random & ((1 << 62) - 1)))
    return str(uuid.UUID(int=value))


def _desktop_properties(system):
    return {"app_name": "TARA Studio", "$os": _OS_NAMES[system], "$device_type": "Desktop"}


def _extra_properties(event, properties):
    if not isinstance(event, str):
        return None
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        return None
    if event in _EXAMPLE_EVENTS:
        if not properties:
            return None if event == "example_loaded" else {}
        return validate_example(properties)
    if event != "active_time":
        return {} if not properties else None
    if set(properties) != {"feature", "seconds"}:
        return None
    feature, seconds = properties["feature"], properties["seconds"]
    if (not isinstance(feature, str) or feature not in FEATURES
            or isinstance(seconds, bool) or not isinstance(seconds, (int, float))):
        return None
    try:
        seconds = float(seconds)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return {"feature": feature, "seconds": seconds}


def _timeout(value, default=1.0):
    try:
        value = float(value)
        return max(0.0, min(value, 10.0)) if math.isfinite(value) else default
    except (ValueError, TypeError):
        return default


class PostHogReporter:
    """Capture allowlisted event counts and bundled-example identifiers.

    ``distinct_id`` is an installation UUID; identifying strings are replaced
    with a fresh anonymous UUID. ``path`` is the local JSON outbox location.
    Public configuration can be supplied explicitly, through the documented
    environment variables, or through ``analytics_config``.
    """

    def __init__(self, distinct_id, *, path=None, project_token=None, host=None, enabled=False):
        token = project_token if project_token is not None else os.environ.get(
            "TARA_POSTHOG_PROJECT_TOKEN", analytics_config.POSTHOG_PROJECT_TOKEN)
        capture_host = host if host is not None else os.environ.get(
            "TARA_POSTHOG_HOST", analytics_config.POSTHOG_HOST)
        self._token = _public_token(token)
        self._host, self._region = _capture_host(capture_host)
        self._configured = bool(self._token and self._host)
        self._distinct_id = _uuid(distinct_id) or str(uuid.uuid4())
        self._session_started = time.time()
        self._last_event = time.monotonic()
        self._session_id = _session_uuid(self._session_started)
        self._path = Path(path or os.path.join(CONFIG_DIR, "posthog_queue.json"))
        system = platform.system()
        self._properties = {
            "app_version": _app_version(),
            "platform": system if system in ("Windows", "Darwin", "Linux") else "unknown",
            "session_id": self._session_id,
            "$session_id": self._session_id,
            "$process_person_profile": False,
            # Events go directly from the desktop to PostHog. The request IP
            # therefore represents the installation's network, not our server.
            "$geoip_disable": False,
        }
        self._properties.update(_desktop_properties(self._properties["platform"]))
        self._condition = threading.Condition()
        self._enabled = bool(enabled)
        self._queue = self._read_outbox() if self._enabled else []
        self._generation = 0
        self._dirty = True  # Rewrite sanitized input, or clear an opted-out outbox.
        self._sending = False
        self._storage_error = False
        self._next_retry = 0.0
        self._batch_ready = 0.0
        self._closing = False
        self._closed = False
        self._force_flush = False
        self._thread = threading.Thread(target=self._work, name="TARA-usage-reporting", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._thread = None

    @property
    def configured(self):
        return self._configured

    @property
    def enabled(self):
        with self._condition:
            return self._enabled

    @property
    def region(self):
        return self._region

    def set_enabled(self, enabled):
        with self._condition:
            if self._closed:
                return False
            if self._enabled == bool(enabled):
                return True
            self._enabled = bool(enabled)
            if not self._enabled:
                self._queue.clear()
                self._generation += 1
                self._dirty = True
            self._next_retry = 0.0
            self._condition.notify_all()
        return True

    def capture(self, event, properties=None):
        if not isinstance(event, str) or event not in EVENTS | {"active_time"}:
            return False
        extra = _extra_properties(event, properties)
        if extra is None:
            return False
        with self._condition:
            if self._closed or not self._enabled or not self._configured or self._thread is None:
                return False
            now, monotonic = time.time(), time.monotonic()
            if (monotonic - self._last_event >= SESSION_IDLE_SECONDS
                    or now - self._session_started >= SESSION_MAX_SECONDS):
                self._session_started = now
                self._session_id = _session_uuid(now)
                self._properties.update(session_id=self._session_id)
                self._properties["$session_id"] = self._session_id
            self._last_event = monotonic
            envelope = {
                "event": event, "distinct_id": self._distinct_id,
                "timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(
                    timespec="milliseconds").replace("+00:00", "Z"),
                "uuid": str(uuid.uuid4()), "properties": dict(self._properties, **extra),
            }
            if not self._queue:
                self._batch_ready = time.monotonic() + BATCH_DELAY
            self._queue.append(envelope)
            if len(self._queue) > MAX_PENDING:
                del self._queue[:len(self._queue) - MAX_PENDING]
            self._generation += 1
            self._dirty = True
            self._condition.notify_all()
        return True

    def flush(self, timeout=1.0):
        deadline = time.monotonic() + _timeout(timeout)
        with self._condition:
            self._force_flush = True
            self._next_retry = 0.0
            self._condition.notify_all()
            while self._queue or self._sending or self._dirty:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._thread is None or not self._thread.is_alive():
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, timeout=1.0):
        with self._condition:
            self._closed = True
            self._closing = True
            self._force_flush = True
            self._condition.notify_all()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(_timeout(timeout))
            return not self._thread.is_alive()
        return True

    def status_snapshot(self):
        with self._condition:
            if self._closed:
                state = "closed"
            elif not self._configured:
                state = "not_configured"
            elif not self._enabled:
                state = "disabled"
            elif self._thread is None:
                state = "unavailable"
            elif self._storage_error:
                state = "storage_unavailable"
            elif self._sending:
                state = "sending"
            elif self._next_retry > time.monotonic():
                state = "offline"
            elif self._queue:
                state = "queued"
            else:
                state = "ready"
            return {"configured": self._configured, "enabled": self._enabled,
                    "region": self._region, "state": state, "count_pending": len(self._queue)}

    def _validated_envelope(self, value):
        if not isinstance(value, dict) or set(value) != _EVENT_FIELDS:
            return None
        event = value["event"]
        if not isinstance(event, str) or event not in EVENTS | {"active_time"}:
            return None
        if _uuid(value["distinct_id"]) != self._distinct_id or not _uuid(value["uuid"]):
            return None
        timestamp = value["timestamp"]
        if not isinstance(timestamp, str) or len(timestamp) > 64:
            return None
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
        except ValueError:
            return None
        properties = value["properties"]
        if not isinstance(properties, dict):
            return None
        # Retain valid queued events from releases before native session IDs.
        base = _BASE_PROPERTIES if "$session_id" in properties else _BASE_PROPERTIES - {"$session_id"}
        desktop = set(properties) & _DESKTOP_PROPERTIES
        if desktop:
            if desktop != _DESKTOP_PROPERTIES:
                return None
            base = base | desktop
        extras = set(properties) - base
        if not base <= properties.keys():
            return None
        if (properties["$process_person_profile"] is not False or not isinstance(properties["$geoip_disable"], bool)
                or not _uuid(properties["session_id"])
                or not isinstance(properties["app_version"], str)
                or not _VERSION_PATTERN.fullmatch(properties["app_version"])
                or properties["platform"] not in ("Windows", "Darwin", "Linux", "unknown")):
            return None
        expected_desktop = _desktop_properties(properties["platform"])
        if desktop and any(properties[key] != expected_desktop[key] for key in desktop):
            return None
        if "$session_id" in properties:
            try:
                session = uuid.UUID(properties["$session_id"])
                session_ms = session.int >> 80
                event_ms = int(parsed.timestamp() * 1000)
                if (session.version != 7 or str(session) != properties["session_id"]
                        or not session_ms <= event_ms < session_ms + 86400000):
                    return None
            except (ValueError, TypeError, AttributeError, OverflowError):
                return None
        extra = _extra_properties(event, {key: properties[key] for key in extras})
        if extra is None:
            return None
        return {
            "event": event, "distinct_id": self._distinct_id, "timestamp": timestamp,
            "uuid": _uuid(value["uuid"]),
            # Derive standard OS fields for valid events queued by older builds.
            # Retain their original event ID, time, platform and GeoIP setting.
            "properties": dict({key: properties[key] for key in base}, **expected_desktop, **extra),
        }

    def _read_outbox(self):
        try:
            if not self._path.exists() or self._path.stat().st_size > MAX_OUTBOX_BYTES:
                return []
            with self._path.open(encoding="utf-8") as source:
                data = json.load(source)
            if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("events"), list):
                return []
            valid = (self._validated_envelope(item) for item in data["events"][-MAX_PENDING:])
            return [item for item in valid if item is not None]
        except (OSError, ValueError, TypeError, RecursionError):
            return []

    def _persist(self, events):
        temporary = None
        try:
            if not events:
                self._path.unlink(missing_ok=True)
                return True
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=self._path.name + ".", suffix=".tmp", dir=str(self._path.parent))
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump({"schema_version": 1, "events": events}, output, allow_nan=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._path)
            return True
        except Exception:
            return False
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass

    def _send(self, batch):
        try:
            payload = json.dumps({"api_key": self._token, "batch": batch}, allow_nan=False).encode("utf-8")
            request = Request(self._host + "/batch/", data=payload, method="POST", headers={
                "Content-Type": "application/json", "User-Agent": "TARA-Studio-usage",
            })
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                return 200 <= getattr(response, "status", 200) < 300
        except Exception:
            return False

    def _work(self):
        backoff = 1.0
        while True:
            with self._condition:
                if self._dirty:
                    events = list(self._queue)
                    generation = self._generation
                    persist = True
                elif not self._enabled or not self._configured or not self._queue:
                    if self._closing:
                        return
                    self._condition.wait()
                    continue
                else:
                    now = time.monotonic()
                    if self._next_retry > now:
                        if self._closing:
                            return  # Already durable; another launch can retry.
                        self._condition.wait(self._next_retry - now)
                        continue
                    if not self._force_flush and not self._closing and self._batch_ready > now:
                        self._condition.wait(self._batch_ready - now)
                        continue
                    self._force_flush = False
                    batch = list(self._queue[:MAX_BATCH])
                    self._sending = True
                    persist = False
            if persist:
                saved = self._persist(events)
                with self._condition:
                    self._storage_error = not saved
                    if generation == self._generation:
                        self._dirty = False
                    self._condition.notify_all()
                continue
            # A pause can arrive while a batch is selected but before HTTP starts.
            with self._condition:
                send = self._enabled and self._configured
            success = self._send(batch) if send else False
            with self._condition:
                self._sending = False
                if success:
                    sent = {item["uuid"] for item in batch}
                    self._queue = [item for item in self._queue if item["uuid"] not in sent]
                    self._generation += 1
                    self._dirty = True
                    self._next_retry = 0.0
                    backoff = 1.0
                elif self._enabled:
                    self._next_retry = time.monotonic() + backoff
                    backoff = min(MAX_BACKOFF, backoff * 2.0)
                self._condition.notify_all()
