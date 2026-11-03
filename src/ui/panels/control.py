# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — The CPU control bar (load/step/run/reset/save/boot, FPGA run, clock speed).

Classes:
  ControlPanel -- The CPU control bar: Load, Step, Back, Run/Stop, Reset, Save, Boot, the FPGA-run button, and clock-speed selection.
"""

import math

from PyQt5.QtCore import Qt, pyqtSignal, QSize, QRectF
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QGraphicsDropShadowEffect, QSlider, QStyle, QVBoxLayout,
)

from src.ui.assets import _panel_title
from src.ui.theme import C


class ControlPanel(QGroupBox):
    """The CPU control bar: Load, Step, Back, Run/Stop, Reset, Save, Boot, the FPGA-run button, and clock-speed selection."""
    sig_step    = pyqtSignal()
    sig_step_back = pyqtSignal()
    sig_run     = pyqtSignal(float)   # freq Hz
    sig_clock_changed = pyqtSignal(float)  # freq Hz
    sig_stop    = pyqtSignal()
    sig_reset   = pyqtSignal()
    sig_assemble= pyqtSignal()
    sig_save_state = pyqtSignal()
    sig_load_state = pyqtSignal()
    sig_run_fpga   = pyqtSignal()   # assemble current code & run it through the FPGA tool

    def __init__(self):
        super().__init__("")
        self._collapsed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2,2,8,8)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(_panel_title("CPU Control"))
        header.addStretch()
        self.collapse_btn = QPushButton("-")
        self.collapse_btn.setFixedSize(30, 24)
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.setToolTip("Collapse CPU controls")
        self.collapse_btn.setStyleSheet(
            f"QPushButton {{ background:#FFFFFF;border:1px solid {C['border']};"
            f"color:{C['accent']};border-radius:6px;padding:0px;font-size:18px;font-weight:800; }}"
            f"QPushButton:hover {{ border-color:{C['accent']}; background:#F7EFE5; }}"
            "QPushButton:pressed { background:#EBD9C4; }"
        )
        self.collapse_btn.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.collapse_btn)
        layout.addLayout(header)

        # PC + stats row
        stat_row = QHBoxLayout()
        self.pc_lbl = QLabel("PC")
        self.pc_lbl.setStyleSheet(f"color:{C['dim']};font-size:11px;font-weight:bold;")
        stat_row.addWidget(self.pc_lbl)
        self.pc_val = QLabel("0x0000")
        self.pc_val.setObjectName("lbl_pc")
        stat_row.addWidget(self.pc_val)
        stat_row.addSpacing(12)
        self.cyc_lbl = QLabel("Cycles: 0")
        self.cyc_lbl.setObjectName("lbl_cycles")
        stat_row.addWidget(self.cyc_lbl)
        self.instr_lbl = QLabel("Instrs: 0")
        self.instr_lbl.setObjectName("lbl_cycles")
        stat_row.addWidget(self.instr_lbl)
        stat_row.addStretch()
        self.status_badge = QLabel("IDLE")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setMinimumWidth(70)
        self.status_badge.setStyleSheet(
            f"background:{C['navy_soft']};color:{C['accent']};border-radius:8px;padding:2px 8px;font-size:11px;font-weight:bold;")
        stat_row.addWidget(self.status_badge)
        layout.addLayout(stat_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_asm = QPushButton("Load")
        self.btn_asm.setObjectName("btn_assemble")
        self.btn_asm.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.btn_step_back = QPushButton("Back")
        self.btn_step_back.setObjectName("btn_step")
        self.btn_step_back.setIcon(self._control_icon(QStyle.SP_ArrowBack))
        self.btn_step_back.setToolTip("Step backward one instruction")
        self.btn_step  = QPushButton("Step")
        self.btn_step.setObjectName("btn_step")
        self.btn_step.setIcon(self._control_icon(QStyle.SP_ArrowForward))
        self.btn_step.setToolTip("Step forward one instruction")
        self.btn_run   = QPushButton("Run")
        self.btn_run.setObjectName("btn_run")
        self.btn_run.setIcon(self._control_icon(QStyle.SP_MediaPlay))

        self.btn_asm.clicked.connect(self.sig_assemble)
        self.btn_step_back.clicked.connect(self.sig_step_back)
        self.btn_step.clicked.connect(self.sig_step)
        self.btn_run.clicked.connect(self._run_toggled)

        for b in (self.btn_asm, self.btn_step_back, self.btn_step, self.btn_run):
            b.setMinimumHeight(50)
            b.setIconSize(QSize(28, 28))
            b.setFont(QFont('Segoe UI', 18, weight=800))
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._add_button_shadow(b, '#7A1E2B')
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        state_row = QHBoxLayout()
        state_row.setSpacing(6)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("btn_reset")
        self.btn_reset.setIcon(self._control_icon(QStyle.SP_BrowserReload))
        self.btn_save_state = QPushButton("Save")
        self.btn_save_state.setObjectName("btn_save_state")
        self.btn_save_state.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_boot_state = QPushButton("Boot")
        self.btn_boot_state.setObjectName("btn_boot_state")
        # "Run on FPGA": assemble the current editor code and run it through the
        # FPGA tool, either on the board or against the simulator-memory target.
        self.btn_run_fpga = QPushButton("FPGA ▶")
        self.btn_run_fpga.setObjectName("btn_run_fpga")
        self.btn_run_fpga.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.btn_run_fpga.setEnabled(False)
        self.btn_run_fpga.setToolTip("Connect to FPGA USB or Simulator Memory in the 'TARA FPGA Tool' tab first")
        self.btn_run_fpga.setStyleSheet(
            "QPushButton{background:#7A1E2B;color:#FFFFFF;border:none;border-radius:8px;font-weight:800;}"
            "QPushButton:hover{background:#641624;}"
            "QPushButton:disabled{background:#CBB9AE;color:#F2ECE6;}")
        self.btn_reset.clicked.connect(self.sig_reset)
        self.btn_save_state.clicked.connect(self.sig_save_state)
        self.btn_boot_state.clicked.connect(self.sig_load_state)
        self.btn_run_fpga.clicked.connect(self.sig_run_fpga)
        for b in (self.btn_reset, self.btn_save_state, self.btn_boot_state, self.btn_run_fpga):
            b.setMinimumHeight(50)
            b.setIconSize(QSize(28, 28))
            b.setFont(QFont('Segoe UI', 18, weight=800))
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._add_button_shadow(b, '#7A1E2B')
            state_row.addWidget(b)
        layout.addLayout(state_row)

        # Frequency control
        freq_row = QHBoxLayout()
        self.clock_lbl = QLabel("Clock:")
        freq_row.addWidget(self.clock_lbl)
        self.freq_combo = QComboBox()
        self.freq_combo.setEditable(True)
        self.freq_combo.setFixedWidth(104)
        presets = ['1 Hz','5 Hz','10 Hz','25 Hz','50 Hz','100 Hz','500 Hz','1 kHz','Max']
        for p in presets:
            self.freq_combo.addItem(p)
        self._clock_hz = 10.0
        self._running = False
        if self.freq_combo.lineEdit():
            self.freq_combo.lineEdit().setAlignment(Qt.AlignCenter)
            self.freq_combo.lineEdit().editingFinished.connect(self._clock_text_edited)
        self.freq_combo.setCurrentText(self._format_freq(self._clock_hz))
        self.freq_combo.activated[str].connect(self._preset_changed)
        freq_row.addWidget(self.freq_combo)

        self.freq_slider = QSlider(Qt.Horizontal)
        self.freq_slider.setRange(-10, 50)  # log10 Hz, scaled by 10: 0.1 Hz through 100 kHz
        self.freq_slider.setValue(self._freq_to_slider_value(self._clock_hz))
        self.freq_slider.setToolTip("Drag to set CPU clock speed.")
        self.freq_slider.setMinimumWidth(110)
        self.freq_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.freq_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: #E4D7CB;
                border: none;
                border-radius: 4px;
            }
            QSlider::sub-page:horizontal {
                background: #A6792E;
                border: none;
                border-radius: 4px;
            }
            QSlider::add-page:horizontal {
                background: #E4D7CB;
                border: none;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -4px 0;
                border-radius: 8px;
                background: #FFFFFF;
                border: 2px solid #7A1E2B;
            }
            QSlider::handle:horizontal:hover {
                border-color: #A6792E;
                background: #F7EFE5;
            }
        """)
        self.freq_slider.valueChanged.connect(self._slider_changed)
        freq_row.addWidget(self.freq_slider, 1)
        layout.addLayout(freq_row)

        self._collapsible_widgets = [
            self.pc_lbl, self.pc_val, self.cyc_lbl, self.instr_lbl, self.status_badge,
            self.btn_asm, self.btn_step_back, self.btn_step, self.btn_run,
            self.btn_reset, self.btn_save_state, self.btn_boot_state,
            self.clock_lbl, self.freq_combo, self.freq_slider,
        ]

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return

        self._collapsed = collapsed
        for widget in self._collapsible_widgets:
            widget.setVisible(not collapsed)
        self.collapse_btn.setText("+" if collapsed else "-")
        self.collapse_btn.setToolTip(
            "Expand CPU controls" if collapsed else "Collapse CPU controls"
        )
        if collapsed:
            self.setMinimumHeight(38)
            self.setMaximumHeight(38)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
        self.updateGeometry()

    def _control_icon(self, standard_icon):
        """Draw clear navigation glyphs without tinting native file artwork."""
        icon = QIcon()
        for mode, color, opacity in (
            (QIcon.Normal, C['accent'], 1.0),
            (QIcon.Disabled, C['dim'], 0.45),
        ):
            pixmap = QPixmap(84, 84)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.scale(3, 3)
            ink = QColor(color)
            ink.setAlphaF(opacity)
            painter.setPen(QPen(ink, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            if standard_icon in (QStyle.SP_ArrowBack, QStyle.SP_ArrowForward):
                if standard_icon == QStyle.SP_ArrowBack:
                    path.moveTo(22, 14)
                    path.lineTo(6, 14)
                    path.moveTo(12, 8)
                    path.lineTo(6, 14)
                    path.lineTo(12, 20)
                else:
                    path.moveTo(6, 14)
                    path.lineTo(22, 14)
                    path.moveTo(16, 8)
                    path.lineTo(22, 14)
                    path.lineTo(16, 20)
                painter.drawPath(path)
            elif standard_icon == QStyle.SP_MediaPlay:
                path.moveTo(9, 6)
                path.lineTo(22, 14)
                path.lineTo(9, 22)
                path.closeSubpath()
                painter.fillPath(path, ink)
            elif standard_icon == QStyle.SP_MediaStop:
                painter.setPen(Qt.NoPen)
                painter.setBrush(ink)
                painter.drawRoundedRect(QRectF(7, 7, 14, 14), 2, 2)
            elif standard_icon == QStyle.SP_BrowserReload:
                path.moveTo(7, 9)
                path.cubicTo(10, 5, 16, 4, 20, 8)
                path.cubicTo(24, 12, 23, 18, 19, 21)
                path.cubicTo(15, 24, 9, 23, 6, 19)
                path.moveTo(7, 4)
                path.lineTo(7, 10)
                path.lineTo(13, 10)
                painter.drawPath(path)
            painter.end()
            pixmap.setDevicePixelRatio(3.0)
            icon.addPixmap(pixmap, mode)
        return icon

    def _add_button_shadow(self, button, color):
        shadow = QGraphicsDropShadowEffect(button)
        shadow.setBlurRadius(6)
        shadow.setOffset(0, 2)
        shadow_color = QColor(color)
        shadow_color.setAlpha(18)
        shadow.setColor(shadow_color)
        button.setGraphicsEffect(shadow)

    def _freq_to_slider_value(self, value):
        return max(-10, min(50, round(math.log10(max(0.1, value)) * 10)))

    def _slider_to_freq(self, value):
        return max(0.1, min(100000.0, 10 ** (value / 10)))

    def _format_freq(self, value):
        if value >= 1000:
            shown = value / 1000
            return f"{shown:.1f} kHz" if shown < 10 else f"{shown:.0f} kHz"
        if value < 10:
            return f"{value:.1f} Hz"
        return f"{value:.0f} Hz"

    def _parse_freq(self, text):
        raw = text.strip().lower().replace(' ', '')
        if raw == 'max':
            return 100000.0
        mult = 1000.0 if raw.endswith('khz') else 1.0
        raw = raw.removesuffix('khz').removesuffix('hz')
        return max(0.1, min(100000.0, float(raw) * mult))

    def _set_clock_frequency(self, value, update_slider=True):
        value = max(0.1, min(100000.0, value))
        changed = value != self._clock_hz
        self._clock_hz = value
        self.freq_combo.blockSignals(True)
        self.freq_combo.setCurrentText(self._format_freq(self._clock_hz))
        self.freq_combo.blockSignals(False)
        if update_slider:
            slider_value = self._freq_to_slider_value(self._clock_hz)
            if self.freq_slider.value() != slider_value:
                self.freq_slider.blockSignals(True)
                self.freq_slider.setValue(slider_value)
                self.freq_slider.blockSignals(False)
        if changed:
            self.sig_clock_changed.emit(self._clock_hz)

    def _slider_changed(self, value):
        self._set_clock_frequency(self._slider_to_freq(value), update_slider=False)

    def _clock_text_edited(self):
        try:
            self._set_clock_frequency(self._parse_freq(self.freq_combo.currentText()))
        except ValueError:
            self._set_clock_frequency(self._clock_hz)

    def _preset_changed(self, text):
        mapping = {
            '1 Hz': 1, '5 Hz': 5, '10 Hz': 10, '25 Hz': 25,
            '50 Hz': 50, '100 Hz': 100, '500 Hz': 500, '1 kHz': 1000,
            'Max': 100000,
        }
        if text in mapping:
            self._set_clock_frequency(mapping[text])

    def _run_toggled(self):
        if self._running:
            self.sig_stop.emit()
        else:
            self.sig_run.emit(self._clock_hz)

    def set_running(self, running):
        self._running = running
        self.btn_step.setEnabled(not running)
        self.btn_step_back.setEnabled(not running and self.btn_step_back.isEnabled())
        self.btn_run.setProperty("running", running)
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        if running:
            self.btn_run.setText("Stop")
            self.btn_run.setIcon(self._control_icon(QStyle.SP_MediaStop))
            self.status_badge.setText("RUNNING")
            self.status_badge.setStyleSheet(
                f"background:{C['accent2']};color:white;border-radius:8px;padding:2px 8px;font-size:11px;font-weight:bold;")
        else:
            self.btn_run.setText("Run")
            self.btn_run.setIcon(self._control_icon(QStyle.SP_MediaPlay))
            self.status_badge.setText("IDLE")
            self.status_badge.setStyleSheet(
                f"background:{C['navy_soft']};color:{C['accent']};border-radius:8px;padding:2px 8px;font-size:11px;font-weight:bold;")

    def set_halted(self):
        self.btn_run.setEnabled(False)
        self.btn_step.setEnabled(False)
        self.btn_step_back.setEnabled(False)
        self._running = False
        self.btn_run.setProperty("running", False)
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        self.btn_run.setText("Run")
        self.btn_run.setIcon(self._control_icon(QStyle.SP_MediaPlay))
        self.status_badge.setText("HALTED")
        self.status_badge.setStyleSheet(
            f"background:{C['danger']};color:white;border-radius:8px;padding:2px 8px;font-size:11px;font-weight:bold;")

    def update_cpu(self, cpu):
        self.pc_val.setText(f'0x{cpu.pc:04X}')
        self.cyc_lbl.setText(f'Cycles: {cpu.cycle_count}')
        self.instr_lbl.setText(f'Instrs: {cpu.instr_count}')

    def set_step_back_enabled(self, enabled):
        self.btn_step_back.setEnabled(bool(enabled and not self._running))
