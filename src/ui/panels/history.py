# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — The execution-log (history) panel.

Classes:
  HistoryPanel -- The 'Execution Log' tab: a per-instruction trace of cycle, PC, mnemonic, operands and register changes.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QGroupBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from src.simulation.cpu import sext
from src.ui.theme import UI_SETTINGS, save_ui_setting

from src.ui.panels.common import _apply_font_button_style


class HistoryPanel(QGroupBox):
    """The 'Execution Log' tab: a per-instruction trace of cycle, PC, mnemonic, operands and register changes."""
    def __init__(self):
        super().__init__("")
        self._font_size = UI_SETTINGS["history_log_font_size"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,2,8,8)
        layout.setSpacing(4)

        self.view_controls = QWidget()
        self.view_controls.setFixedHeight(28)
        hdr = QHBoxLayout(self.view_controls)
        hdr.setContentsMargins(0, 1, 0, 1)
        hdr.setSpacing(4)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setMaximumWidth(60)
        self.clear_btn.setFixedHeight(26)
        self.clear_btn.setStyleSheet("QPushButton {padding:2px 8px;font-size:12px;}")
        self.clear_btn.clicked.connect(self.clear)
        hdr.addWidget(self.clear_btn)
        self.font_dec_btn = QPushButton("A-")
        self.font_inc_btn = QPushButton("A+")
        for btn in (self.font_dec_btn, self.font_inc_btn):
            _apply_font_button_style(btn)
            hdr.addWidget(btn)
        self.font_dec_btn.clicked.connect(lambda: self.adjust_font_size(-1))
        self.font_inc_btn.clicked.connect(lambda: self.adjust_font_size(1))
        layout.addWidget(self.view_controls, 0, Qt.AlignRight)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        layout.addWidget(self.log)
        self._apply_font_size()

    def _log_font(self):
        font = QFont('Menlo')
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(self._font_size)
        return font

    def _apply_font_size(self):
        self.log.setFont(self._log_font())
        self.font_dec_btn.setEnabled(self._font_size > 9)
        self.font_inc_btn.setEnabled(self._font_size < 30)
        self.font_dec_btn.setToolTip(f"Decrease execution log font size ({self._font_size} px)")
        self.font_inc_btn.setToolTip(f"Increase execution log font size ({self._font_size} px)")

    def adjust_font_size(self, delta):
        self._font_size = max(9, min(30, self._font_size + delta))
        save_ui_setting("history_log_font_size", self._font_size)
        self._apply_font_size()

    def log_step(self, snap, cpu):
        if not snap:
            return
        d = snap.get('instr')
        if not d:
            return
        regs_before = snap['reg']
        regs_after  = cpu.reg
        changed = [f'R{i}=0x{regs_after[i]:04X}' for i in range(8)
                   if regs_after[i] != regs_before[i]]
        line = f"[{snap['cycle']:5d}] PC=0x{snap['pc']:04X}  {d['name']:<5} {self._ops(d):<18}"
        if changed:
            line += "  → " + ', '.join(changed)
        self.log.appendPlainText(line)

    def _ops(self, d):
        n = d['name']
        if n in ('NOP','HLT','RET'):    return ''
        if n in ('MOV','NOT'):          return f'R{d["rd"]}, R{d["rsA"]}'
        if n in ('LIL','LIH','ADDI','SHL','SHR'): return f'R{d["rd"]}, {d["imm8"]}'
        if n in ('ADD','SUB','MUL','AND','OR','XOR','SLT'): return f'R{d["rd"]}, R{d["rsA"]}, R{d["rsB"]}'
        if n in ('LDW','LDB'):          return f'R{d["rd"]}, {sext(d["off5"],5)}(R{d["rsA"]})'
        if n in ('STW','STB'):          return f'R{d["rd"]}, {sext(d["off5"],5)}(R{d["rsA"]})'
        if n in ('BZ','BN'):            return f'R{d["rd"]}, {sext(d["rel8"],8)}'
        if n in ('JMP','CALL'):         return f'{sext(d["rel11"],11)}'
        if n in ('PUSH','POP'):         return f'R{d["rd"]}'
        return ''

    def clear(self):
        self.log.clear()

    def remove_last_entry(self):
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()
        self.log.setTextCursor(cursor)
