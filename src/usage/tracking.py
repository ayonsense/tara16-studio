# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Count active Studio time using timestamps and event types only."""

import time

from PyQt5.QtCore import QEvent, QObject, QTimer, Qt
from PyQt5.QtWidgets import QApplication


class UsageActivityTracker(QObject):
    """Account foreground usage, excluding idle and hidden-window time.

    Input is used only as an activity timestamp. No key, mouse-position,
    document, or other event payload is inspected or retained.
    """

    FEATURES = frozenset(("compiler", "assembly", "fpga"))
    INPUT_EVENTS = frozenset((
        QEvent.KeyPress, QEvent.KeyRelease,
        QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
        QEvent.MouseButtonDblClick, QEvent.MouseMove, QEvent.Wheel,
        QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd,
    ))

    def __init__(self, stats, window, parent=None, *, clock=None, idle_timeout=60.0):
        super().__init__(parent if parent is not None else window)
        self.stats = stats
        self.window = window
        self._app = QApplication.instance()
        self._clock = clock or time.monotonic
        self._idle_timeout = max(0.0, float(idle_timeout))
        self._feature = "assembly"
        self._started = False
        self._running = False
        self._active = False
        self._last_checkpoint = None
        self._last_activity = None
        self.timer = QTimer(self)
        self.timer.setInterval(10000)
        self.timer.timeout.connect(self.checkpoint)

    def _belongs_to_window(self, target):
        if target is None:
            return False
        if target is self.window.windowHandle():
            return True
        while target is not None:
            if target is self.window:
                return True
            target = target.parent()
        return False

    def _is_active(self):
        return bool(
            self._app is not None
            and self.window.isVisible()
            and not self.window.isMinimized()
            and self._app.applicationState() == Qt.ApplicationActive
            and self._belongs_to_window(self._app.activeWindow())
        )

    def _initial_feature(self):
        tabs = getattr(self.window, "top_tabs", None)
        if tabs is None:
            return self._feature
        current = tabs.currentWidget()
        for feature, attribute in (("compiler", "compiler_panel"),
                                   ("assembly", "assembly_tab"),
                                   ("fpga", "fpga_panel")):
            if current is getattr(self.window, attribute, None):
                return feature
        return self._feature

    def start(self):
        """Start after showing the window; one tracker records one launch."""
        if self._started:
            return
        self._started = True
        self._running = True
        self._feature = self._initial_feature()
        self.reset_clock()
        self.stats.start_session()
        self.stats.record("tab_" + self._feature)
        if self._app is not None:
            self._app.installEventFilter(self)
            self._app.applicationStateChanged.connect(self._application_state_changed)
        self.timer.start()

    def _account(self, now):
        if self._last_checkpoint is not None and self._active:
            end = min(now, self._last_activity + self._idle_timeout)
            seconds = max(0.0, end - self._last_checkpoint)
            if seconds:
                self.stats.add_active_time(self._feature, seconds)
        self._last_checkpoint = now
        self._active = self._is_active()

    def checkpoint(self):
        if self._running:
            self._account(self._clock())

    def set_feature(self, feature):
        """Record actual view changes, accounting prior time to the old view."""
        if feature not in self.FEATURES or feature == self._feature:
            return
        if self._running:
            self.checkpoint()
        self._feature = feature
        if self._running:
            self.stats.record("tab_" + feature)

    def reset_clock(self):
        """Discard pending time after resetting data or changing collection."""
        now = self._clock()
        self._last_checkpoint = now
        self._last_activity = now
        self._active = self._is_active()

    def _application_state_changed(self, state):
        if not self._running:
            return
        self.checkpoint()
        if state == Qt.ApplicationActive and self._active:
            self._last_activity = self._last_checkpoint
        elif state != Qt.ApplicationActive:
            self._active = False

    def eventFilter(self, watched, event):
        if not self._running or not self._belongs_to_window(watched):
            return False
        event_type = event.type()
        if event_type in self.INPUT_EVENTS:
            now = self._clock()
            # Avoid a database write for every mouse move. Only close an idle
            # gap immediately; the timer batches ordinary active intervals.
            if not self._active or now > self._last_activity + self._idle_timeout:
                self._account(now)
            self._last_activity = now
            self._active = self._is_active()
        elif event_type in (QEvent.WindowDeactivate, QEvent.Hide):
            self.checkpoint()
            if watched is self.window or watched is self.window.windowHandle():
                self._active = False
        elif event_type == QEvent.WindowActivate:
            self.checkpoint()
            if self._active:
                self._last_activity = self._last_checkpoint
        elif event_type == QEvent.Show:
            self.checkpoint()
            if watched is self.window and self._active:
                self._last_activity = self._last_checkpoint
        elif event_type in (QEvent.FocusOut, QEvent.WindowStateChange):
            self.checkpoint()
        return False

    def stop(self):
        """Account the final interval once, then release application hooks."""
        if not self._running:
            return
        self.checkpoint()
        self._running = False
        self.timer.stop()
        if self._app is not None:
            self._app.removeEventFilter(self)
            try:
                self._app.applicationStateChanged.disconnect(self._application_state_changed)
            except (RuntimeError, TypeError):
                pass
