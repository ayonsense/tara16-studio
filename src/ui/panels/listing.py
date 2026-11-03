# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — The machine-code listing panel (the assembled-instruction view).

Classes:
  ListingPanel -- The 'Machine Code' tab: the assembled instruction listing with address, hex encoding, binary fields and mnemonic, with the current PC row highlighted.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.ui.theme import C, UI_SETTINGS, save_ui_setting

from src.ui.panels.common import _apply_font_button_style


class ListingPanel(QGroupBox):
    """The 'Machine Code' tab: the assembled instruction listing with address, hex encoding, binary fields and mnemonic, with the current PC row highlighted."""
    sig_source_line_selected = pyqtSignal(int)

    def __init__(self):
        super().__init__("")
        self._font_size = UI_SETTINGS["listing_font_size"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,2,8,8)
        layout.setSpacing(4)

        self.view_controls = QWidget()
        self.view_controls.setFixedHeight(28)
        header = QHBoxLayout(self.view_controls)
        header.setContentsMargins(0, 1, 0, 1)
        header.setSpacing(4)
        self.font_dec_btn = QPushButton("A-")
        self.font_inc_btn = QPushButton("A+")
        for btn in (self.font_dec_btn, self.font_inc_btn):
            self._style_font_button(btn)
            header.addWidget(btn)
        self.font_dec_btn.setToolTip("Decrease listing font size")
        self.font_inc_btn.setToolTip("Increase listing font size")
        self.font_dec_btn.clicked.connect(lambda: self.adjust_font_size(-1))
        self.font_inc_btn.clicked.connect(lambda: self.adjust_font_size(1))
        layout.addWidget(self.view_controls, 0, Qt.AlignRight)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['Addr', 'Hex', 'Binary'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 260)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFont(self._listing_font())
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                border-radius: 4px;
            }}
            QTableWidget::item {{ padding: 2px 6px; }}
            QTableWidget::item:alternate {{ background-color: {C['row_alt']}; }}
            QTableWidget::item:selected {{ background-color: {C['pc_row']}; color: {C['text']}; }}
        """)
        self.table.cellClicked.connect(self._cell_clicked)
        layout.addWidget(self.table)

        self._row_for_addr = {}
        self._line_for_row = {}
        self._apply_font_size()

    def _style_font_button(self, button):
        _apply_font_button_style(button)

    def _listing_font(self, weight=-1):
        font = QFont('Menlo')
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(self._font_size)
        if weight != -1:
            font.setWeight(weight)
        return font

    def _apply_font_size(self):
        font = self._listing_font()
        header_font = QFont('Segoe UI')
        header_font.setPixelSize(max(9, self._font_size - 1))
        header_font.setWeight(700)
        self.table.setFont(font)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setFont(header_font)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(max(24, QFontMetrics(font).height() + 8))

        fm = QFontMetrics(font)
        self.font_dec_btn.setEnabled(self._font_size > 9)
        self.font_inc_btn.setEnabled(self._font_size < 40)
        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is not None:
                    item.setFont(font)
        self._fit_columns_to_content(fm)
        if self.table.rowCount():
            self._sync_row_heights()

    def _content_column_width(self, table, col, fm, header_text, padding=24, minimum=44, maximum=360):
        width = fm.horizontalAdvance(header_text)
        for row in range(table.rowCount()):
            item = table.item(row, col)
            if item is not None:
                width = max(width, fm.horizontalAdvance(item.text()))
        return max(minimum, min(maximum, width + padding))

    def _fit_columns_to_content(self, fm=None):
        fm = fm or QFontMetrics(self.table.font())
        specs = [
            (0, 'Addr', 24, 72, 180),
            (1, 'Hex', 24, 72, 180),
            (2, 'Binary', 44, 210, 720),
        ]
        for col, header, padding, minimum, maximum in specs:
            self.table.setColumnWidth(
                col,
                self._content_column_width(self.table, col, fm, header, padding, minimum, maximum)
            )

    def adjust_font_size(self, delta):
        self._font_size = max(9, min(40, self._font_size + delta))
        save_ui_setting("listing_font_size", self._font_size)
        self._apply_font_size()

    def load(self, listing):
        self.table.setRowCount(0)
        self._row_for_addr = {}
        self._line_for_row = {}
        for row, entry in enumerate(listing):
            self.table.insertRow(row)
            addr = entry['addr']
            word = entry['word']
            self._row_for_addr[addr] = row
            self._line_for_row[row] = entry.get('lineno')

            b = f'{word:016b}'
            bfmt = f'{b[0:5]} {b[5:8]} {b[8:11]} {b[11:14]} {b[14:16]}'

            vals = [
                f'0x{addr:04X}',
                f'0x{word:04X}',
                bfmt,
            ]
            for col, txt in enumerate(vals):
                item = QTableWidgetItem(txt)
                item.setFont(self._listing_font())
                item.setTextAlignment(Qt.AlignVCenter |
                    (Qt.AlignRight if col < 3 else Qt.AlignLeft))
                if col == 0:
                    fg = QColor(C['dim'])
                elif col == 1:
                    fg = QColor(C['highlight'])
                elif col == 2:
                    fg = QColor(C['dim'])
                else:
                    fg = QColor('#A65F00')
                item.setForeground(fg)
                item.setData(Qt.UserRole + 20, fg)
                self.table.setItem(row, col, item)

        self._apply_font_size()

    def _sync_row_heights(self):
        row_height = max(28, QFontMetrics(self.table.font()).height() + 14)
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, row_height)

    def _cell_clicked(self, row, _col):
        line = self._line_for_row.get(row)
        if isinstance(line, int) and line > 0:
            self.sig_source_line_selected.emit(line)

    def highlight_pc(self, pc):
        pc_row = self._row_for_addr.get(pc)
        self.table.clearSelection()
        for addr, row in self._row_for_addr.items():
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item:
                    if addr == pc:
                        item.setData(Qt.BackgroundRole, QColor(C['pc_row']))
                        item.setData(Qt.ForegroundRole, QColor(C['text']))
                    else:
                        item.setData(Qt.BackgroundRole, QColor(C['row_alt'] if row % 2 else C['panel']))
                        fg = item.data(Qt.UserRole + 20)
                        if isinstance(fg, QColor):
                            item.setData(Qt.ForegroundRole, fg)

        if pc in self._row_for_addr:
            horizontal_pos = self.table.horizontalScrollBar().value()
            self.table.selectRow(pc_row)
            self.table.scrollToItem(
                self.table.item(pc_row, 0),
                QAbstractItemView.PositionAtCenter
            )
            self.table.horizontalScrollBar().setValue(horizontal_pos)
