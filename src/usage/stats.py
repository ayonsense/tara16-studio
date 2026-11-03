# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Local, aggregate Studio usage counts, with no source or document metadata.

SQLite transactions keep totals and daily figures consistent across multiple
Studio windows. This module has no Qt or network dependency. Storage failures
disable recording for that instance rather than interrupting teaching work.
"""

from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import uuid

from src.paths import CONFIG_DIR


EVENTS = frozenset({
    "app_launches", "program_run", "example_loaded",
    "compile_started", "compile_succeeded", "compile_failed",
    "assembly_started", "assembly_succeeded", "assembly_failed",
    "tab_compiler", "tab_assembly", "tab_fpga",
    "fpga_connect", "simulator_connect",
    "fpga_program_started", "fpga_program_succeeded", "fpga_program_failed",
    "fpga_detect", "fpga_run", "simulator_run",
})
FEATURES = ("compiler", "assembly", "fpga")
SCHEMA_VERSION = 1
_TOTAL = "*"


class UsageStats:
    """Persist only allowlisted event totals and active seconds per workspace.

    ``TARA_USAGE_DB`` selects an alternate database for tests or managed labs.
    Invalid events/durations and unavailable storage return False. Exported JSON
    contains aggregate numbers and dates, never the database's filesystem path.
    """

    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("TARA_USAGE_DB")
                         or os.path.join(CONFIG_DIR, "usage.sqlite3"))
        self._lock = threading.RLock()
        self._connection = None
        self._enabled = True
        self._session_started = False
        self.available = False
        self.error = ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                str(self.path), timeout=0.25, check_same_thread=False)
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise sqlite3.DatabaseError("Unsupported usage schema")
            self._connection.execute("PRAGMA journal_mode=WAL")
            with self._connection:
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS metadata "
                    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS metrics "
                    "(day TEXT NOT NULL, key TEXT NOT NULL, value REAL NOT NULL "
                    "CHECK(value >= 0), PRIMARY KEY(day, key))")
                self._connection.execute(
                    "INSERT OR IGNORE INTO metadata(key,value) VALUES('enabled','1')")
                self._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._enabled = self._read_enabled()
            self.available = True
        except (OSError, sqlite3.Error, ValueError, TypeError):
            self._storage_failed()

    @staticmethod
    def _now():
        now = datetime.now().astimezone()
        return now.date().isoformat(), now.isoformat(timespec="seconds")

    def _read_enabled(self):
        row = self._connection.execute(
            "SELECT value FROM metadata WHERE key='enabled'").fetchone()
        return bool(row and row[0] == "1")

    def _storage_failed(self):
        # Leave damaged/unavailable files untouched so they can be recovered.
        self.available = False
        self.error = "Usage statistics could not be saved on this computer."
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
            self._connection = None

    def _increment(self, key, amount):
        with self._lock:
            if not self.available:
                return False
            try:
                with self._connection:
                    self._connection.execute("BEGIN IMMEDIATE")
                    self._enabled = self._read_enabled()
                    if not self._enabled:
                        return False
                    day, timestamp = self._now()
                    for period in (_TOTAL, day):
                        self._connection.execute(
                            "INSERT INTO metrics(day,key,value) VALUES(?,?,?) "
                            "ON CONFLICT(day,key) DO UPDATE SET value=value+excluded.value",
                            (period, key, amount))
                    self._connection.execute(
                        "INSERT OR IGNORE INTO metadata(key,value) VALUES('first_used',?)",
                        (timestamp,))
                    self._connection.execute(
                        "INSERT INTO metadata(key,value) VALUES('last_used',?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (timestamp,))
                return True
            except (sqlite3.Error, OSError):
                self._storage_failed()
                return False

    def start_session(self):
        with self._lock:
            if self._session_started:
                return False
            self._session_started = True
            return self.record("app_launches")

    def record(self, event):
        if not isinstance(event, str) or event not in EVENTS:
            return False
        return self._increment(event, 1)

    def add_active_time(self, feature, seconds):
        if feature not in FEATURES or isinstance(seconds, bool):
            return False
        try:
            seconds = float(seconds)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(seconds) or seconds <= 0:
            return False
        return self._increment("active." + feature, seconds)

    @staticmethod
    def _empty_counts():
        return {event: 0 for event in sorted(EVENTS)}

    @staticmethod
    def _empty_time():
        return {feature: 0.0 for feature in FEATURES}

    def _empty_snapshot(self):
        return {"available": self.available, "enabled": self._enabled,
                "first_used": None, "last_used": None,
                "counters": self._empty_counts(), "active_seconds": self._empty_time(),
                "daily": []}

    def snapshot(self):
        with self._lock:
            result = self._empty_snapshot()
            if not self.available:
                return result
            try:
                with self._connection:
                    self._connection.execute("BEGIN")
                    metadata = dict(self._connection.execute("SELECT key,value FROM metadata"))
                    rows = self._connection.execute("SELECT day,key,value FROM metrics").fetchall()
                self._enabled = metadata.get("enabled") == "1"
                result.update(enabled=self._enabled, first_used=metadata.get("first_used"),
                              last_used=metadata.get("last_used"))
                daily = {}
                for day, key, amount in rows:
                    amount = float(amount)
                    if not math.isfinite(amount) or amount < 0:
                        raise ValueError("Invalid aggregate metric")
                    if day == _TOTAL:
                        target = result
                    else:
                        target = daily.setdefault(day, {
                            "date": day, "counters": self._empty_counts(),
                            "active_seconds": self._empty_time()})
                    if key in EVENTS:
                        target["counters"][key] = int(amount)
                    elif key.startswith("active.") and key[7:] in FEATURES:
                        target["active_seconds"][key[7:]] = amount
                result["daily"] = [daily[day] for day in sorted(daily, reverse=True)]
                return result
            except (sqlite3.Error, ValueError, TypeError, OverflowError):
                self._storage_failed()
                return self._empty_snapshot()

    def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            return False
        with self._lock:
            if not self.available:
                return False
            try:
                with self._connection:
                    self._connection.execute(
                        "UPDATE metadata SET value=? WHERE key='enabled'", ("1" if enabled else "0",))
                self._enabled = enabled
                return True
            except sqlite3.Error:
                self._storage_failed()
                return False

    def get_preference(self, name, default=None):
        """Read an anonymous-ID or legacy cloud-sharing preference.

        These settings are not part of aggregate exports. The background
        coordinator uses deployment configuration instead of the legacy opt-in.
        """
        if name not in ("installation_id", "cloud_enabled"):
            return default
        if name == "cloud_enabled" and default is None:
            default = False
        with self._lock:
            if not self.available:
                return default
            try:
                row = self._connection.execute(
                    "SELECT value FROM metadata WHERE key=?", ("pref." + name,)).fetchone()
                if row is None:
                    return default
                if name == "cloud_enabled":
                    return row[0] == "1"
                return uuid.UUID(row[0]).hex
            except (sqlite3.Error, ValueError, AttributeError):
                self._storage_failed()
                return default

    def set_preference(self, name, value):
        """Persist a valid installation UUID or legacy cloud-sharing preference."""
        if name == "cloud_enabled":
            if not isinstance(value, bool):
                return False
            value = "1" if value else "0"
        elif name == "installation_id":
            if not isinstance(value, str) or not value or len(value) > 64:
                return False
            try:
                value = uuid.UUID(value).hex
            except (ValueError, AttributeError):
                return False
        else:
            return False
        with self._lock:
            if not self.available:
                return False
            try:
                with self._connection:
                    self._connection.execute(
                        "INSERT INTO metadata(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        ("pref." + name, value))
                return True
            except sqlite3.Error:
                self._storage_failed()
                return False

    def reset(self):
        with self._lock:
            if not self.available:
                return False
            try:
                with self._connection:
                    self._connection.execute("BEGIN IMMEDIATE")
                    self._connection.execute("DELETE FROM metrics")
                    self._connection.execute(
                        "DELETE FROM metadata WHERE key IN ('first_used','last_used')")
                return True
            except sqlite3.Error:
                self._storage_failed()
                return False

    def export(self, path):
        result = self.snapshot()
        if not result["available"]:
            return False
        result.update(schema_version=SCHEMA_VERSION, exported_at=self._now()[1])
        temporary = None
        try:
            destination = Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                                             prefix=".tara-usage-", suffix=".json", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            return True
        except (OSError, TypeError, ValueError):
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def flush(self):
        """Writes are committed immediately; provided for lifecycle callers."""
        return self.available

    def close(self):
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None
            self.available = False
