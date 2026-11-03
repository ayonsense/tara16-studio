# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""The ISA reference dialog.

A scrollable, colour-coded table of every TARA instruction (group, mnemonic,
encoding and effect), opened from the editor toolbar's 'ISA' button."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.simulation.cpu import OP_NAME, TaraCPU
from src.ui.theme import C, UI_SETTINGS, save_ui_setting

ISA_ROWS = [
    ('System', '#FFF0F0', 'NOP',  'NOP',                 'No operation'),
    ('System', '#FFF0F0', 'HLT',  'HLT',                 'Halt execution'),
    ('Move / Immediate', '#FFF7E6', 'MOV',  'MOV Rd, Rs',       'Rd = Rs'),
    ('Move / Immediate', '#FFF7E6', 'LIL',  'LIL Rd, imm8',     'Rd[7:0] = imm8, high byte cleared'),
    ('Move / Immediate', '#FFF7E6', 'LIH',  'LIH Rd, imm8',     'Rd[15:8] = imm8, low byte preserved'),
    ('Memory', '#EEF8FF', 'LDW',  'LDW Rd, off5(Rb)',    'Load 16-bit word from memory'),
    ('Memory', '#EEF8FF', 'STW',  'STW Rs, off5(Rb)',    'Store 16-bit word to memory'),
    ('Memory', '#EEF8FF', 'LDB',  'LDB Rd, off5(Rb)',    'Load byte from memory'),
    ('Memory', '#EEF8FF', 'STB',  'STB Rs, off5(Rb)',    'Store low byte to memory'),
    ('Arithmetic', '#F1FFF4', 'ADD',  'ADD Rd, Ra, Rb',  'Rd = Ra + Rb'),
    ('Arithmetic', '#F1FFF4', 'SUB',  'SUB Rd, Ra, Rb',  'Rd = Ra - Rb'),
    ('Arithmetic', '#F1FFF4', 'ADDI', 'ADDI Rd, imm8',   'Rd = Rd + sign-extended imm8'),
    ('Arithmetic', '#F1FFF4', 'MUL',  'MUL Rd, Ra, Rb',  'Rd = Ra * Rb'),
    ('Logic', '#F4F0FF', 'AND',  'AND Rd, Ra, Rb',       'Rd = Ra & Rb'),
    ('Logic', '#F4F0FF', 'OR',   'OR Rd, Ra, Rb',        'Rd = Ra | Rb'),
    ('Logic', '#F4F0FF', 'XOR',  'XOR Rd, Ra, Rb',       'Rd = Ra ^ Rb'),
    ('Logic', '#F4F0FF', 'NOT',  'NOT Rd, Rs',           'Rd = bitwise not Rs'),
    ('Shift / Compare', '#EEFDFB', 'SHL', 'SHL Rd, shamt', 'Rd = Rd << shamt'),
    ('Shift / Compare', '#EEFDFB', 'SHR', 'SHR Rd, shamt', 'Rd = Rd >> shamt'),
    ('Shift / Compare', '#EEFDFB', 'SLT', 'SLT Rd, Ra, Rb', 'Rd = 1 if signed Ra < signed Rb else 0'),
    ('Control Flow', '#FFF2E8', 'BZ',   'BZ Rt, label',  'Branch if Rt == 0'),
    ('Control Flow', '#FFF2E8', 'BN',   'BN Rt, label',  'Branch if Rt < 0'),
    ('Control Flow', '#FFF2E8', 'JMP',  'JMP label',     'PC-relative jump'),
    ('Control Flow', '#FFF2E8', 'CALL', 'CALL label',    'R6 = return PC, then jump'),
    ('Control Flow', '#FFF2E8', 'RET',  'RET',           'PC = R6'),
    ('Stack', '#F6F7F9', 'PUSH', 'PUSH Rs',              'R7 -= 2; store Rs at stack top'),
    ('Stack', '#F6F7F9', 'POP',  'POP Rd',               'Load stack top into Rd; R7 += 2'),
]


ISA_FONT_MIN = 11
ISA_FONT_MAX = 30


def _apply_font_button_style(button):
    button.setFixedSize(34, 26)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton {{ background:#FFFFFF;border:1px solid {C['border']};"
        f"color:{C['title']};border-radius:6px;padding:1px;font-weight:800; }}"
        f"QPushButton:hover {{ border-color:{C['accent']}; background:{C['panel2']}; }}"
        f"QPushButton:pressed {{ background:{C['selected']}; padding-top:3px; }}"
    )


class ISADialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_size = UI_SETTINGS["isa_font_size"]
        self.setWindowTitle("TARA ISA Reference")
        self.resize(820, 620)
        self.setStyleSheet(f"""
            QDialog {{ background:{C['panel']}; color:{C['text']}; }}
            QLabel#isa_title {{ color:{C['title']}; font-size:18px; font-weight:800; }}
            QLabel#isa_subtitle {{ color:{C['dim']}; font-size:12px; }}
            QTableWidget {{
                background:{C['panel']};
                border:1px solid {C['border']};
                border-radius:8px;
                gridline-color:{C['border']};
                selection-background-color:{C['highlight']};
            }}
            QTableWidget::item {{ padding:5px 8px; }}
            QHeaderView::section {{
                background:{C['navy_soft']};
                color:{C['accent']};
                border:none;
                border-right:1px solid {C['border']};
                border-bottom:1px solid {C['border']};
                padding:6px 8px;
                font-weight:800;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        title = QLabel("TARA ISA Reference")
        title.setObjectName("isa_title")
        title_row.addWidget(title)
        title_row.addStretch()
        self.font_dec_btn = QPushButton("A-")
        self.font_inc_btn = QPushButton("A+")
        for btn in (self.font_dec_btn, self.font_inc_btn):
            _apply_font_button_style(btn)
            title_row.addWidget(btn)
        self.font_dec_btn.clicked.connect(lambda: self.adjust_font_size(-1))
        self.font_inc_btn.clicked.connect(lambda: self.adjust_font_size(1))
        layout.addLayout(title_row)

        subtitle = QLabel("16-bit fixed-width instructions | 5-bit opcode | R0-R7 | byte-addressed memory")
        subtitle.setObjectName("isa_subtitle")
        layout.addWidget(subtitle)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Group', 'INST', 'Opcode', 'Format', 'Syntax', 'Effect'])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setRowCount(len(ISA_ROWS))

        cpu = TaraCPU()
        for row, (group, bg, inst, syntax, effect) in enumerate(ISA_ROWS):
            opcode = next((op for op, name in OP_NAME.items() if name == inst), None)
            fmt = cpu.decode((opcode or 0) << 11)['fmt'] if opcode is not None else ''
            vals = [group, inst, f'{opcode:02d}' if opcode is not None else '', fmt, syntax, effect]
            for col, value in enumerate(vals):
                item = QTableWidgetItem(value)
                item.setBackground(QColor(bg))
                item.setForeground(QColor(C['accent2'] if col == 1 else C['text']))
                if col in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                else:
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.table.setItem(row, col, item)

        for col in range(5):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self._apply_font_size()
        layout.addWidget(self.table)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _font(self, family='Segoe UI', size=None, weight=-1):
        font = QFont(family)
        if family == 'Menlo':
            font.setStyleHint(QFont.Monospace)
        font.setPixelSize(size or self._font_size)
        if weight != -1:
            font.setWeight(weight)
        return font

    def _apply_font_size(self):
        body_font = self._font()
        code_font = self._font('Menlo')
        code_bold_font = self._font('Menlo', weight=700)
        header_font = self._font(size=max(11, self._font_size - 2), weight=800)

        self.table.setFont(body_font)
        self.table.horizontalHeader().setFont(header_font)
        row_height = max(30, QFontMetrics(body_font).height() + 12)
        self.table.verticalHeader().setDefaultSectionSize(row_height)

        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, row_height)
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                if col in (1, 2, 3):
                    item.setFont(code_bold_font)
                elif col == 4:
                    item.setFont(code_font)
                else:
                    item.setFont(body_font)

        self.font_dec_btn.setEnabled(self._font_size > ISA_FONT_MIN)
        self.font_inc_btn.setEnabled(self._font_size < ISA_FONT_MAX)
        self.font_dec_btn.setToolTip(f"Decrease ISA table font size ({self._font_size} px)")
        self.font_inc_btn.setToolTip(f"Increase ISA table font size ({self._font_size} px)")
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)

    def adjust_font_size(self, delta):
        self._font_size = max(ISA_FONT_MIN, min(ISA_FONT_MAX, self._font_size + delta))
        save_ui_setting("isa_font_size", self._font_size)
        self._apply_font_size()
