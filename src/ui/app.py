# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Main application window for the TARA emulator.

Builds the simulator UI (editor + control bar on the left; register file and the
Machine-Code / Memory / Display / Execution-Log tabs on the right), wraps that
plus the compiler and FPGA tool inside three top-level tabs, owns the TaraCPU instance, and
wires every control action (load, step, back, run/stop, reset, save/boot, and
run-through-FPGA-tool)."""

import json
import os
import sys
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QKeySequence, QPalette
from PyQt5.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QSplitter,
    QMessageBox, QPushButton, QShortcut, QSizePolicy, QStatusBar, QTabBar, QTabWidget, QVBoxLayout, QWidget,
)

from src.assembler.asm import assemble
from src.paths import APP_ICON_PATH, DEFAULT_CPU_STATE_PATH, ensure_config_dirs
from src.simulation.cpu import TaraCPU
from src.ui.assets import _add_brand_logo_pair, _rounded_app_icon
from src.ui.panels import (
    ControlPanel, DisplayPanel, EditorPanel, HistoryPanel, ListingPanel,
    MemoryPanel, RegisterPanel,
)
from src.ui.theme import C, GLOBAL_STYLE
from src.ui.fpga_panel import FpgaMonitorPanel
from src.ui.compiler_panel import CompilerPanel
from src.usage.analytics import UsageAnalytics
from src.usage.tracking import UsageActivityTracker

# ─── Main window ───────────────────────────────────────────────────────────────
class TaraSimWindow(QMainWindow):
    def __init__(self, usage_stats=None):
        super().__init__()
        self.usage_stats = UsageAnalytics(local=usage_stats)
        self._usage_closed = False
        self.setWindowTitle("TARA Studio")
        if os.path.exists(APP_ICON_PATH):
            self.setWindowIcon(_rounded_app_icon(APP_ICON_PATH))
        # open no larger than the available screen so the window never overflows
        # (e.g. on a small / scaled Mac display); centred on screen.
        _av = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, int(_av.width() * 0.94)),
                    min(840,  int(_av.height() * 0.94)))
        self.move(_av.left() + (_av.width()  - self.width())  // 2,
                  _av.top()  + (_av.height() - self.height()) // 2)

        self.cpu = TaraCPU()
        self.listing = []
        self.timer = QTimer()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._clock_tick)
        self._loaded = False
        self._loaded_usage_context = None
        self._batch  = 1   # instructions per timer tick (for high freq)
        self._breakpoint_addrs = set()
        self._breakpoint_line_for_addr = {}
        self._line_for_addr = {}
        self._undo_stack = []
        self._max_undo_states = 30
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        self._defer_realtime_state_panels = False
        self._defer_realtime_memory_panels = False
        self._defer_realtime_editor_highlight = False
        self._record_realtime_trace = True
        self._runtime_tick_budget_sec = 0.0

        self.setStyleSheet(GLOBAL_STYLE)
        self._build_ui()
        self._add_studio_tabs()
        self._update_all()
        self.usage_tracker = UsageActivityTracker(self.usage_stats, self)
        self.top_tabs.currentChanged.connect(self._usage_tab_changed)
        self._fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._fullscreen_shortcut.activated.connect(self._toggle_fullscreen)
        self._exit_fullscreen_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._exit_fullscreen_shortcut.activated.connect(self._exit_fullscreen)

    def _add_studio_tabs(self):
        """Keep the workflow tabs together and open Assembly at startup.

        The existing simulator widget is retained, so its controls and the
        FPGA tool continue to share the same CPU and assembler.
        """
        sim_central = self.takeCentralWidget()
        self.assembly_tab = sim_central
        top = QTabWidget(); top.setObjectName("topTabs")
        self.compiler_panel = CompilerPanel()
        self.compiler_panel.usage_event.connect(self.usage_stats.record)
        self.compiler_panel.assembly_ready.connect(self._load_compiled_assembly)
        top.addTab(self.compiler_panel, "TARA16 Compiler")
        top.addTab(sim_central, "TARA16 Assembly")
        try:
            self.fpga_panel = FpgaMonitorPanel(
                simulator_cpu=self.cpu,
                on_simulator_memory_changed=self._fpga_simulator_memory_changed,
                on_simulator_program_loaded=self._fpga_simulator_program_loaded,
            )
            self.fpga_panel.connection_changed.connect(self._fpga_connection_changed)
            self.fpga_panel.usage_event.connect(self.usage_stats.record)
            top.addTab(self.fpga_panel, "TARA16 FPGA Tool")
        except Exception as e:                       # never let this break the simulator
            self.fpga_panel = None
            print("FPGA Memory Tool tab unavailable:", e)
        top.setStyleSheet("QTabWidget#topTabs::pane { border: none; }")
        top.tabBar().hide()

        # Give navigation and branding their own layout. Native QTabWidget
        # corner sizing can otherwise overlap the page or leave a blank strip.
        self.studio_header = QWidget()
        header_layout = QHBoxLayout(self.studio_header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(12)
        self.navigation_tabs = QTabBar()
        self.navigation_tabs.setObjectName("studioTabBar")
        tf = QFont('Helvetica Neue'); tf.setPixelSize(16); tf.setWeight(700)
        self.navigation_tabs.setFont(tf)
        self.navigation_tabs.setExpanding(False)
        self.navigation_tabs.setDrawBase(False)
        self.navigation_tabs.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        for index in range(top.count()):
            self.navigation_tabs.addTab(top.tabText(index))
        self.navigation_tabs.currentChanged.connect(top.setCurrentIndex)
        top.currentChanged.connect(self.navigation_tabs.setCurrentIndex)
        header_layout.addWidget(self.navigation_tabs, 0, Qt.AlignLeft)
        header_layout.addStretch(1)
        self.fullscreen_button = QPushButton("Full screen")
        self.fullscreen_button.setFixedHeight(32)
        self.fullscreen_button.setToolTip("Toggle full screen (F11). Esc returns to a window.")
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        header_layout.addWidget(self.fullscreen_button, 0, Qt.AlignVCenter)
        self.brand_header = QFrame()
        self.brand_header.setObjectName("studioBrand")
        self.brand_header.setToolTip("TARA Studio — Teaching Architecture for RISC Assembly")
        self.brand_header.setStyleSheet(
            f"QFrame#studioBrand {{background:white;border:1px solid {C['border']};border-radius:10px;}}"
            "QFrame#studioBrand QLabel {background:transparent;}")
        brand_layout = QHBoxLayout(self.brand_header)
        brand_layout.setContentsMargins(12, 4, 12, 4)
        brand_layout.setSpacing(9)
        _add_brand_logo_pair(brand_layout, icon_height=50, text_height=44)
        self.brand_header.setFixedSize(self.brand_header.sizeHint())
        header_layout.addWidget(self.brand_header, 0, Qt.AlignVCenter)
        self.navigation_tabs.setFixedHeight(self.brand_header.height())
        self.navigation_tabs.setStyleSheet(
            "QTabBar#studioTabBar::tab { min-width:174px;"
            f"min-height:{self.brand_header.height() - 3}px;"
            "padding:0px 18px;font-size:16px;font-weight:700; }")
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self.studio_header)
        shell_layout.addWidget(top, 1)
        self.setCentralWidget(shell)
        self.top_tabs = top
        top.setCurrentWidget(self.assembly_tab)
        self.status.showMessage("Ready. Write or load assembly, then click Load.")

    def start_usage_tracking(self):
        self.usage_tracker.start()

    def _usage_tab_changed(self, _index):
        current = self.top_tabs.currentWidget()
        feature = "compiler" if current is self.compiler_panel else (
            "assembly" if current is self.assembly_tab else "fpga")
        self.usage_tracker.set_feature(feature)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def _exit_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "fullscreen_button"):
            self.fullscreen_button.setText("Windowed" if self.isFullScreen() else "Full screen")

    def _finish_usage_tracking(self):
        if self._usage_closed:
            return
        self._usage_closed = True
        self.usage_tracker.stop()
        self.usage_stats.close()

    def _load_compiled_assembly(self, source):
        """Load the compiler's .tara export through the normal assembly path.

        Clear the previous file association so Save cannot overwrite a bundled
        example or unrelated assembly file with compiler-generated contents.
        No execution or hardware write occurs until the user chooses Run.
        """
        existing = self.editor_panel.get_source()
        if existing.strip() and existing != source:
            choice = QMessageBox.question(
                self, "Load compiled assembly",
                "Replace the current assembly editor contents with the compiled program? "
                "Save any assembly changes first if you want to keep them.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if choice != QMessageBox.Yes:
                return
        self._stop()
        self.editor_panel.editor.setPlainText(source)
        self.editor_panel.editor.clear_breakpoints()
        self.editor_panel._set_current_program("", None)
        self.editor_panel._select_program_name("")
        self.editor_panel.editor.document().setModified(True)
        self.editor_panel.set_usage_example(self.compiler_panel.compiled_example_context())
        self.hist_panel.clear()
        self._assemble()
        self.top_tabs.setCurrentWidget(self.assembly_tab)

    def closeEvent(self, event):
        """Protect unsaved C edits and keep an active compiler worker alive."""
        if not self.compiler_panel.confirm_close():
            event.ignore()
            return
        if not self.compiler_panel.shutdown():
            self.status.showMessage("Compilation is finishing. Please close Studio again when it completes.")
            event.ignore()
            return
        self.timer.stop()
        self._finish_usage_tracking()
        event.accept()

    def _run_on_fpga(self):
        """Assemble the code currently in the editor and run it through the FPGA tool."""
        panel = getattr(self, 'fpga_panel', None)
        if panel is None or not panel.link.is_open:
            QMessageBox.information(self, "Run through FPGA Tool",
                "Connect to FPGA USB or Simulator Memory in the 'TARA16 FPGA Tool' tab first.")
            return
        src = self.editor_panel.get_source()
        usage_context = self.editor_panel.usage_example_context()
        self.usage_stats.record("assembly_started", usage_context)
        words, listing, errors, labels = assemble(src)
        if errors:
            self.usage_stats.record("assembly_failed", usage_context)
            self.editor_panel.show_errors(errors)
            QMessageBox.warning(self, "Assemble error",
                                "\n".join(str(e) for e in errors[:6]))
            return
        prog = [w for _a, w in words]
        if not prog:
            self.usage_stats.record("assembly_failed", usage_context)
            QMessageBox.information(self, "Run through FPGA Tool", "Nothing to run — the program is empty.")
            return
        self.usage_stats.record("assembly_succeeded", usage_context)
        panel.load_words_and_run(prog, source="Simulator", source_text=src, listing=listing, usage_context=usage_context)
        self.top_tabs.setCurrentWidget(panel)     # show the target memory updating

    def _fpga_connection_changed(self, connected):
        """Enable the FPGA-tool run button only while a target CPU is reachable."""
        btn = self.control_panel.btn_run_fpga
        btn.setEnabled(bool(connected))
        panel = getattr(self, 'fpga_panel', None)
        virtual = bool(panel and panel.is_virtual_connection())
        if connected and virtual:
            btn.setToolTip("Assemble the current code and run it through the Simulator Memory target")
        elif connected:
            btn.setToolTip("Assemble the current code and run it on the FPGA")
        else:
            btn.setToolTip("Connect to FPGA USB or Simulator Memory in the 'TARA16 FPGA Tool' tab first")

    def _fpga_simulator_memory_changed(self, start, data):
        """Refresh simulator UI after the FPGA tool writes through the virtual link."""
        self._clear_undo_stack()
        self._update_all()
        end = min(TaraCPU.MEM_SIZE, start + len(data))
        self.status.showMessage(
            f"FPGA Tool wrote simulator memory: 0x{start:04X}-0x{end - 1:04X}"
            if end > start else "FPGA Tool wrote simulator memory."
        )

    def _fpga_simulator_program_loaded(self, words, source_text=None, listing=None, source_label="FPGA Tool", usage_context=None):
        """Load a program requested by the FPGA tool into the live simulator CPU."""
        self.timer.stop()
        self._reset_runtime_deferrals()
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        self._clear_undo_stack()

        if source_text is not None and self.editor_panel.get_source() != source_text:
            self.editor_panel.editor.setPlainText(source_text)
            self.editor_panel.show_errors([])

        self.editor_panel.set_usage_example(usage_context)
        self.listing = listing or []
        self.listing_panel.load(self.listing)
        self._rebuild_line_for_addr()
        self._rebuild_breakpoint_addrs()

        preserved_mem = bytearray(self.cpu.mem)
        self.cpu.reset()
        self.cpu.mem[:] = preserved_mem
        self.cpu.load_program(words, start=0)
        self._loaded = True
        self.hist_panel.clear()
        self.control_panel.set_running(False)
        self.control_panel.btn_step.setEnabled(True)
        self.control_panel.btn_run.setEnabled(True)
        self._set_ready_badge()
        self._update_all()
        self.status.showMessage(
            f"Loaded {len(words)} instructions from {source_label} into simulator memory."
        )
        self._loaded_usage_context = usage_context
        self._run(getattr(self.control_panel, "_clock_hz", 10.0), track_usage=False)
        return True

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8,8,8,8)
        root.setSpacing(8)

        # ── Left: editor ──
        left = QSplitter(Qt.Vertical)
        self.editor_panel = EditorPanel()
        self.editor_panel.usage_event.connect(self.usage_stats.record)
        self.editor_panel.sig_breakpoints_changed.connect(self._breakpoints_changed)
        self.editor_panel.sig_power_off.connect(self._confirm_power_off)
        left.addWidget(self.editor_panel)

        self.control_panel = ControlPanel()
        self.control_panel.sig_step.connect(self._step)
        self.control_panel.sig_step_back.connect(self._step_back)
        self.control_panel.sig_run.connect(self._run)
        self.control_panel.sig_clock_changed.connect(self._clock_frequency_changed)
        self.control_panel.sig_stop.connect(self._stop)
        self.control_panel.sig_reset.connect(self._reset)
        self.control_panel.sig_assemble.connect(self._assemble)
        self.control_panel.sig_save_state.connect(self._save_state)
        self.control_panel.sig_load_state.connect(self._load_state)
        self.control_panel.sig_run_fpga.connect(self._run_on_fpga)
        left.addWidget(self.control_panel)
        left.setSizes([620, 180])

        # ── Right: registers, listing, memory, display, log ──
        right = QSplitter(Qt.Vertical)
        self.right_splitter = right
        self.reg_panel = RegisterPanel()
        self.reg_panel.collapsed_changed.connect(self._register_panel_collapsed)
        right.addWidget(self.reg_panel)

        self.tabs = QTabWidget()
        self.listing_panel = ListingPanel()
        self.listing_panel.sig_source_line_selected.connect(self._listing_source_line_selected)
        self.tabs.addTab(self.listing_panel, "Machine Code")
        self.mem_panel = MemoryPanel()
        self.mem_panel.cell_written.connect(self._mem_cell_written)
        self.tabs.addTab(self.mem_panel, "Memory")
        self.display_panel = DisplayPanel()
        self.display_panel.memory_written.connect(self._display_mem_written)
        self.display_panel.memory_region_written.connect(self._display_mem_region_written)
        self.display_panel.key_register_changed.connect(self._key_register_changed)
        self.tabs.addTab(self.display_panel, "Display")
        self.hist_panel = HistoryPanel()
        self.tabs.addTab(self.hist_panel, "Execution Log")
        # Keep font/log actions beside the view tabs instead of spending a
        # separate row on a heading that repeats the selected tab's title.
        for panel in (self.listing_panel, self.hist_panel):
            panel.layout().removeWidget(panel.view_controls)
            panel.view_controls.setParent(self.tabs)
            panel.view_controls.hide()
        self.tabs.currentChanged.connect(self._right_tab_changed)
        tab_font = QFont('Helvetica Neue')
        tab_font.setPixelSize(14)
        tab_font.setWeight(700)
        self.tabs.tabBar().setFont(tab_font)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setStyleSheet("""
            QTabWidget::tab-bar { alignment: left; left: 2px; }
            QTabBar {
                font-size: 14px;
                font-weight: 700;
            }
            QTabBar::tab {
                min-width: 80px;
                padding: 7px 12px;
            }
        """)
        self._update_view_controls()
        right.addWidget(self.tabs)
        right.setSizes([220, 660])

        # ── Splitter layout ──
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left)
        main_splitter.addWidget(right)
        main_splitter.setSizes([680, 680])

        root.addWidget(main_splitter)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.editor_panel.sig_status.connect(self.status.showMessage)
        self.copyright_label = QLabel(
            "Copyright © Ayon Chakraborty, IIT Madras. All rights reserved."
        )
        self.copyright_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status.addPermanentWidget(self.copyright_label)
        self.status.showMessage("Ready. Write or load assembly, then click Assemble & Load.")

    def _register_panel_collapsed(self, collapsed):
        if collapsed:
            self.right_splitter.setSizes([self.reg_panel.minimumHeight(), self.right_splitter.height()])
        else:
            reg_height = self.reg_panel.maximumHeight()
            self.right_splitter.setSizes([reg_height, max(1, self.right_splitter.height() - reg_height)])

    def _right_tab_changed(self, _index):
        self._update_view_controls()
        if self.tabs.currentWidget() is self.mem_panel:
            self.mem_panel.update_mem(self.cpu.mem)
        elif self.tabs.currentWidget() is self.display_panel:
            self.display_panel.update_mem(self.cpu.mem)
            # Give the canvas focus so arrow keys / WASD reach the game at once.
            self.display_panel.raster.setFocus()

    def _update_view_controls(self):
        controls = getattr(self.tabs.currentWidget(), "view_controls", None)
        previous = self.tabs.cornerWidget(Qt.TopRightCorner)
        if previous is not controls:
            if previous is not None:
                previous.hide()
            self.tabs.setCornerWidget(controls, Qt.TopRightCorner)
        if controls is not None:
            controls.show()

    def _key_register_changed(self, bits):
        """Live keyboard bits from the Display canvas → memory register 0x05FF."""
        self.cpu.mem[DisplayPanel.KEY_REGISTER] = bits & 0xFF
        # Keep the memory browser in sync if it happens to be the visible tab.
        if self.tabs.currentWidget() is self.mem_panel:
            self.mem_panel.update_mem(self.cpu.mem)

    def _listing_source_line_selected(self, line):
        self.editor_panel.highlight_execution_line(line)
        self.status.showMessage(f"Highlighted source line {line}.")

    # ── Breakpoints ──────────────────────────────────────────────────────────
    def _rebuild_breakpoint_addrs(self):
        lines = self.editor_panel.get_breakpoints()
        self._breakpoint_addrs = {
            entry['addr'] for entry in self.listing
            if entry.get('lineno') in lines
        }
        self._breakpoint_line_for_addr = {
            entry['addr']: entry.get('lineno') for entry in self.listing
            if entry.get('lineno') in lines
        }
        self._line_for_addr = {
            entry['addr']: entry.get('lineno') for entry in self.listing
            if entry.get('lineno') is not None
        }

    def _breakpoints_changed(self, _lines):
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        self._rebuild_breakpoint_addrs()
        count = len(self._breakpoint_addrs)
        if self._loaded:
            self.status.showMessage(
                f"{count} active breakpoint{'s' if count != 1 else ''} mapped to instructions."
            )

    def _at_breakpoint(self):
        return self._loaded and self.cpu.pc in self._breakpoint_addrs

    def _reset_runtime_deferrals(self):
        self._defer_realtime_state_panels = False
        self._defer_realtime_memory_panels = False
        self._defer_realtime_editor_highlight = False
        self._record_realtime_trace = True
        self._runtime_tick_budget_sec = 0.0

    def _stop_at_breakpoint(self):
        was_high_speed = self._defer_realtime_state_panels
        self.timer.stop()
        self.control_panel.set_running(False)
        self._reset_runtime_deferrals()
        self._resume_breakpoint_pc = self.cpu.pc
        self._skip_breakpoint_pc = None
        if was_high_speed:
            self._clear_undo_stack()
        self._update_all()
        line = self._breakpoint_line_for_addr.get(self.cpu.pc)
        where = f"line {line}, " if line else ""
        self.status.showMessage(f"Breakpoint hit at {where}PC=0x{self.cpu.pc:04X}. Step or Run to continue.")

    def _snapshot_cpu(self):
        return {
            'reg': list(self.cpu.reg),
            'pc': self.cpu.pc,
            'mem': bytes(self.cpu.mem),
            'halted': self.cpu.halted,
            'error': self.cpu.error,
            'cycle_count': self.cpu.cycle_count,
            'instr_count': self.cpu.instr_count,
            'last_instr': dict(self.cpu.last_instr) if isinstance(self.cpu.last_instr, dict) else self.cpu.last_instr,
            'history': list(self.cpu.history),
        }

    def _push_undo_state(self):
        self._undo_stack.append(self._snapshot_cpu())
        if len(self._undo_stack) > self._max_undo_states:
            self._undo_stack.pop(0)

    def _restore_cpu_snapshot(self, snap):
        self.cpu.reg = list(snap['reg'])
        self.cpu.pc = snap['pc'] & 0x7FF
        self.cpu.mem[:] = snap['mem']
        self.cpu.halted = bool(snap['halted'])
        self.cpu.error = snap['error']
        self.cpu.cycle_count = int(snap['cycle_count'])
        self.cpu.instr_count = int(snap['instr_count'])
        self.cpu.last_instr = snap['last_instr']
        self.cpu.history = list(snap['history'])

    def _clear_undo_stack(self):
        self._undo_stack.clear()

    def _set_ready_badge(self):
        self.control_panel.status_badge.setText("READY")
        self.control_panel.status_badge.setStyleSheet(
            f"background:{C['accent']};color:white;border-radius:8px;"
            "padding:2px 8px;font-size:11px;font-weight:bold;")

    def _rebuild_line_for_addr(self):
        self._line_for_addr = {
            entry['addr']: entry.get('lineno') for entry in self.listing
            if entry.get('lineno') is not None
        }

    # ── Machine state save / boot ────────────────────────────────────────────
    def _machine_state_payload(self):
        return {
            'format': 'tara-machine-state',
            'version': 1,
            'source': self.editor_panel.get_source(),
            'loaded': self._loaded,
            'listing': self.listing,
            'cpu': {
                'reg': list(self.cpu.reg),
                'pc': self.cpu.pc,
                'mem_hex': self.cpu.mem.hex(),
                'halted': self.cpu.halted,
                'error': self.cpu.error,
                'cycle_count': self.cpu.cycle_count,
                'instr_count': self.cpu.instr_count,
                'last_instr': self.cpu.last_instr,
            },
        }

    def _save_state(self):
        from PyQt5.QtWidgets import QFileDialog
        if self.timer.isActive():
            self._stop()

        path, _ = QFileDialog.getSaveFileName(
            self, "Save TARA Machine State", DEFAULT_CPU_STATE_PATH,
            "TARA machine state (*.json);;All files (*)")
        if not path:
            return False

        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._machine_state_payload(), f, indent=2)
            self.status.showMessage(f"Machine state saved to {os.path.basename(path)}.")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Machine State", f"Could not save state:\n{e}")
            return False

    def _confirm_power_off(self):
        if self.timer.isActive():
            self._stop()

        choice = QMessageBox.question(
            self,
            "Power Off",
            "Save machine state before exiting?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if choice == QMessageBox.Yes:
            if self._save_state():
                self.close()
        else:
            self.close()

    def _load_state(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Boot TARA Machine State", DEFAULT_CPU_STATE_PATH,
            "TARA machine state (*.json);;All files (*)")
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            self._apply_machine_state(payload)
            self.status.showMessage(f"Booted machine state from {os.path.basename(path)}.")
        except Exception as e:
            QMessageBox.critical(self, "Boot Machine State", f"Could not boot state:\n{e}")

    def _apply_machine_state(self, payload):
        if payload.get('format') != 'tara-machine-state':
            raise ValueError("Not a TARA machine-state file.")

        cpu_state = payload.get('cpu', {})
        mem = bytes.fromhex(cpu_state.get('mem_hex', ''))
        if len(mem) != TaraCPU.MEM_SIZE:
            raise ValueError(f"Machine-state memory must be {TaraCPU.MEM_SIZE} bytes.")

        self.timer.stop()
        self._reset_runtime_deferrals()
        source = payload.get('source', '')
        self.editor_panel.editor.setPlainText(source)
        self.editor_panel.set_usage_example(None)
        self._loaded_usage_context = None
        self.editor_panel.show_errors([])

        listing = payload.get('listing') or []
        if source.strip():
            _words, rebuilt_listing, errors, _labels = assemble(source)
            if not errors:
                listing = rebuilt_listing
            else:
                self.editor_panel.show_errors(errors)

        self.listing = listing
        self.listing_panel.load(self.listing)
        self._rebuild_line_for_addr()
        self._rebuild_breakpoint_addrs()
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        self._clear_undo_stack()

        self.cpu.reset()
        self.cpu.reg = [int(v) & 0xFFFF for v in cpu_state.get('reg', [0] * 8)[:8]]
        while len(self.cpu.reg) < 8:
            self.cpu.reg.append(0)
        self.cpu.pc = int(cpu_state.get('pc', 0)) & 0x7FF
        self.cpu.mem[:] = mem
        self.cpu.halted = bool(cpu_state.get('halted', False))
        self.cpu.error = cpu_state.get('error')
        self.cpu.cycle_count = int(cpu_state.get('cycle_count', 0))
        self.cpu.instr_count = int(cpu_state.get('instr_count', 0))
        self.cpu.last_instr = cpu_state.get('last_instr')
        self._loaded = bool(payload.get('loaded', True))

        if self.cpu.halted:
            self.control_panel.set_halted()
        else:
            self.control_panel.set_running(False)
            self.control_panel.btn_step.setEnabled(self._loaded)
            self.control_panel.btn_run.setEnabled(self._loaded)
            if self._loaded:
                self._set_ready_badge()
        self.hist_panel.clear()
        self._update_all()

    # ── Assemble ──────────────────────────────────────────────────────────────
    def _assemble(self):
        src = self.editor_panel.get_source()
        if not src.strip():
            self._clear_undo_stack()
            self.editor_panel.highlight_execution_line(None)
            self.status.showMessage("No source code to assemble.")
            return

        usage_context = self.editor_panel.usage_example_context()
        self.usage_stats.record("assembly_started", usage_context)
        words, listing, errors, labels = assemble(src)
        self.editor_panel.show_errors(errors)

        if errors:
            self.usage_stats.record("assembly_failed", usage_context)
            self._clear_undo_stack()
            self._line_for_addr = {}
            self.editor_panel.highlight_execution_line(None)
            self.status.showMessage(f"Assembly failed: {len(errors)} error(s)")
            return

        self.usage_stats.record("assembly_succeeded", usage_context)

        self.listing = listing
        self.listing_panel.load(listing)
        self._reset_runtime_deferrals()
        self._rebuild_line_for_addr()
        self._rebuild_breakpoint_addrs()
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        self._clear_undo_stack()

        # Reset CPU state while preserving data memory outside the new program.
        preserved_mem = bytearray(self.cpu.mem)
        self.cpu.reset()
        self.cpu.mem[:] = preserved_mem
        self.cpu.load_program([w for (_, w) in words], start=0)
        self._loaded_usage_context = usage_context
        self._loaded = True
        self.control_panel.set_running(False)
        self.control_panel.btn_step.setEnabled(True)
        self.control_panel.btn_run.setEnabled(True)
        self._set_ready_badge()

        self._update_all()
        self.status.showMessage(
            f"Assembled {len(listing)} instructions, {len(labels)} labels. PC=0x0000. Ready to run.")

    # ── Step ──────────────────────────────────────────────────────────────────
    def _step(self):
        if not self._loaded or self.cpu.halted:
            return
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        self._push_undo_state()
        prev_snap_count = len(self.cpu.history)
        ok = self.cpu.step()
        if len(self.cpu.history) > prev_snap_count:
            self.hist_panel.log_step(self.cpu.history[-1], self.cpu)
        self._update_all()
        if self.cpu.halted:
            self.control_panel.set_halted()
            self.control_panel.set_step_back_enabled(bool(self._undo_stack))
            msg = f"Halted at PC=0x{self.cpu.pc:04X}"
            if self.cpu.error:
                msg += f" — {self.cpu.error}"
            self.status.showMessage(msg)

    def _step_back(self):
        if not self._loaded or not self._undo_stack:
            return
        self.timer.stop()
        self.control_panel.set_running(False)
        self._reset_runtime_deferrals()
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        snap = self._undo_stack.pop()
        remove_log_entry = len(self.cpu.history) > len(snap.get('history', []))
        self._restore_cpu_snapshot(snap)
        if remove_log_entry:
            self.hist_panel.remove_last_entry()
        if self.cpu.halted:
            self.control_panel.set_halted()
        else:
            self.control_panel.btn_step.setEnabled(True)
            self.control_panel.btn_run.setEnabled(True)
            self._set_ready_badge()
        self._update_all()
        self.status.showMessage(f"Stepped back to PC=0x{self.cpu.pc:04X}.")

    # ── Run / Stop ────────────────────────────────────────────────────────────
    def _configure_clock(self, freq):
        was_high_speed = self._defer_realtime_state_panels
        high_speed = freq > 25
        self._defer_realtime_state_panels = high_speed
        self._defer_realtime_memory_panels = high_speed
        self._defer_realtime_editor_highlight = high_speed
        self._record_realtime_trace = not high_speed

        if high_speed:
            self._clear_undo_stack()
        elif was_high_speed:
            self._clear_undo_stack()

        # For high frequencies, batch multiple instructions per tick with a short
        # event-loop slice so stop/pause and other UI events stay responsive.
        if freq >= 1000:
            interval_ms = 10
            self._batch = max(1, int(freq * interval_ms / 1000))
        else:
            interval_ms = max(1, int(1000 / freq))
            self._batch = 1
        self._runtime_tick_budget_sec = 0.008 if high_speed else 0.0

        self.timer.start(interval_ms)
        if was_high_speed and not high_speed:
            self._update_all()
        self.status.showMessage(f"Running at {freq:.1f} Hz (batch={self._batch})...")

    def _clock_frequency_changed(self, freq):
        if self.timer.isActive():
            self._configure_clock(freq)

    def _run(self, freq, *, track_usage=True):
        if not self._loaded or self.cpu.halted:
            return
        if self._at_breakpoint():
            if self._resume_breakpoint_pc == self.cpu.pc:
                self._skip_breakpoint_pc = self.cpu.pc
                self._resume_breakpoint_pc = None
            else:
                self._stop_at_breakpoint()
                return
        if track_usage and not self.timer.isActive():
            self.usage_stats.record("program_run", self._loaded_usage_context)
        self._configure_clock(freq)
        self.control_panel.set_running(True)

    def _stop(self):
        was_high_speed = self._defer_realtime_state_panels
        self.timer.stop()
        self.control_panel.set_running(False)
        self._reset_runtime_deferrals()
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        if was_high_speed:
            self._clear_undo_stack()
        self.status.showMessage(
            "Stopped. Step-back history cleared after high-speed run."
            if was_high_speed else "Stopped."
        )
        self._update_all()

    def _clock_tick(self):
        tick_started = time.perf_counter()
        for _ in range(self._batch):
            if self.cpu.halted:
                was_high_speed = self._defer_realtime_state_panels
                self.timer.stop()
                self.control_panel.set_halted()
                self._reset_runtime_deferrals()
                if was_high_speed:
                    self._clear_undo_stack()
                self._update_all()
                msg = f"Halted at PC=0x{self.cpu.pc:04X}"
                if self.cpu.error:
                    msg += f" — {self.cpu.error}"
                self.status.showMessage(msg)
                return
            if self._at_breakpoint():
                if self._skip_breakpoint_pc == self.cpu.pc:
                    self._skip_breakpoint_pc = None
                else:
                    self._stop_at_breakpoint()
                    return
            if self._record_realtime_trace:
                self._push_undo_state()
                prev_snap_count = len(self.cpu.history)
                ok = self.cpu.step(record_history=True)
                if len(self.cpu.history) > prev_snap_count:
                    self.hist_panel.log_step(self.cpu.history[-1], self.cpu)
            else:
                ok = self.cpu.step(record_history=False)
            if not ok:
                break
            if (
                self._runtime_tick_budget_sec
                and time.perf_counter() - tick_started >= self._runtime_tick_budget_sec
            ):
                break
        if self.cpu.halted:
            was_high_speed = self._defer_realtime_state_panels
            self._reset_runtime_deferrals()
            if was_high_speed:
                self._clear_undo_stack()
            self._update_all()
        else:
            self._update_runtime()

    # ── Reset ────────────────────────────────────────────────────────────────
    def _reset(self):
        self.timer.stop()
        self._reset_runtime_deferrals()
        self._resume_breakpoint_pc = None
        self._skip_breakpoint_pc = None
        self._clear_undo_stack()
        if self._loaded:
            # Re-assemble and reload
            self._assemble()
        else:
            self.cpu.reset()
        self.hist_panel.clear()
        self.control_panel.set_running(False)
        self._update_all()
        self.status.showMessage("Reset. CPU state cleared.")

    # ── Memory cell edited by user ────────────────────────────────────────────
    def _mem_cell_written(self, addr, val):
        """Propagate a user-edited memory cell back into the live CPU."""
        self._clear_undo_stack()
        if addr == -1:
            # Bulk update — copy entire panel buffer into CPU
            self.cpu.mem[:] = self.mem_panel._mem
        elif 0 <= addr < TaraCPU.MEM_SIZE:
            self.cpu.mem[addr] = val & 0xFF
        # Refresh listing in case code region was edited
        self.listing_panel.highlight_pc(self.cpu.pc)
        self.display_panel.update_mem(self.cpu.mem)
        self.status.showMessage(
            f"Memory written: 0x{addr:04X} ← 0x{val:02X}" if addr >= 0
            else "Bulk memory update applied."
        )

    def _display_mem_written(self, addr, val):
        """Propagate display-panel I/O writes back into the live CPU."""
        if 0 <= addr < TaraCPU.MEM_SIZE:
            self._clear_undo_stack()
            self.cpu.mem[addr] = val & 0xFF
            self.mem_panel.update_mem(self.cpu.mem)
            self.listing_panel.highlight_pc(self.cpu.pc)
            self.status.showMessage(f"Display I/O: 0x{addr:04X} ← 0x{val:02X}")

    def _display_mem_region_written(self, start, data):
        """Propagate bulk display-buffer writes back into the live CPU."""
        end = min(TaraCPU.MEM_SIZE, start + len(data))
        if 0 <= start < end:
            self._clear_undo_stack()
            self.cpu.mem[start:end] = data[:end - start]
            self.mem_panel.update_mem(self.cpu.mem)
            self.listing_panel.highlight_pc(self.cpu.pc)
            label = "Display buffer" if (
                start < self.display_panel.DISPLAY_BASE + self.display_panel.DISPLAY_BYTES
                and end > self.display_panel.DISPLAY_BASE
            ) else "Image data"
            self.status.showMessage(
                f"{label} copied: 0x{start:04X}-0x{end - 1:04X} ({end - start} bytes)"
            )

    # ── Update all UI panels ──────────────────────────────────────────────────
    def _update_all(self):
        self._update_ui(update_state_panels=True)

    def _update_runtime(self):
        memory_tab_visible = self.tabs.currentWidget() is self.mem_panel
        self._update_ui(
            update_state_panels=not self._defer_realtime_state_panels,
            update_memory_panels=memory_tab_visible or not self._defer_realtime_memory_panels,
            update_display_panel=True,
            update_editor_highlight=not self._defer_realtime_editor_highlight,
        )

    def _update_ui(
        self,
        update_state_panels=True,
        update_memory_panels=True,
        update_display_panel=True,
        update_editor_highlight=True,
    ):
        if update_state_panels:
            self.reg_panel.update_regs(self.cpu.reg)
        if update_memory_panels:
            self.mem_panel.update_mem(self.cpu.mem)
        if update_display_panel:
            self.display_panel.update_mem(self.cpu.mem)
        if update_state_panels:
            self.listing_panel.highlight_pc(self.cpu.pc)
        if update_editor_highlight:
            self.editor_panel.highlight_execution_line(self._line_for_addr.get(self.cpu.pc))
        self.control_panel.update_cpu(self.cpu)
        self.control_panel.set_step_back_enabled(bool(self._undo_stack) and self._loaded)


# ─── Entry point ───────────────────────────────────────────────────────────────
def main():
    ensure_config_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName("TARA Studio")
    if os.path.exists(APP_ICON_PATH):
        app.setWindowIcon(_rounded_app_icon(APP_ICON_PATH))

    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(C['bg']))
    palette.setColor(QPalette.WindowText,      QColor(C['text']))
    palette.setColor(QPalette.Base,            QColor(C['panel']))
    palette.setColor(QPalette.AlternateBase,   QColor(C['row_alt']))
    palette.setColor(QPalette.ToolTipBase,     QColor(C['panel']))
    palette.setColor(QPalette.ToolTipText,     QColor(C['text']))
    palette.setColor(QPalette.Text,            QColor(C['text']))
    palette.setColor(QPalette.Button,          QColor(C['panel']))
    palette.setColor(QPalette.ButtonText,      QColor(C['text']))
    palette.setColor(QPalette.Highlight,       QColor(C['highlight']))
    palette.setColor(QPalette.HighlightedText, QColor('white'))
    app.setPalette(palette)

    win = TaraSimWindow()
    # OS-level Quit can bypass closeEvent; let the bounded compiler subprocess
    # finish before Qt destroys its worker thread in that case.
    app.aboutToQuit.connect(lambda: win.compiler_panel.shutdown(timeout_ms=35000))
    app.aboutToQuit.connect(win._finish_usage_tracking)
    win.showFullScreen()
    win.start_usage_tracking()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
