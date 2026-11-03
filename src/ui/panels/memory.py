# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — The memory browser: the byte/word grid panel, its in-place cell editor, the heat-map cell delegate and the bulk memory-tools dialog.

Classes:
  HeatmapCellDelegate -- Table-cell painter that fills each cell with the heat-map colour stored in its item data, so the colouring survives the global stylesheet.
  CellEditor -- A QLineEdit used for in-place editing of a memory cell; parses hex/dec/bin input and validates the byte value.
  MemoryPanel -- The 'Memory' tab: a paged byte/word grid with jump-to, inline editing, heat-map colouring, Hex/Dec toggle and the memory-tools dialog.
"""


from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.simulation.cpu import TaraCPU
from src.ui.theme import C, UI_SETTINGS, save_ui_setting

from src.ui.panels.mem_tools import MemToolsDialog
from src.ui.panels.common import DEFAULT_MEMORY_CMAP, HEATMAP_BG_ROLE, HEATMAP_FG_ROLE, MPL_GET_CMAP, _apply_font_button_style


class HeatmapCellDelegate(QStyledItemDelegate):
    """Table-cell painter that fills each cell with the heat-map colour stored in its item data, so the colouring survives the global stylesheet."""
    def paint(self, painter, option, index):
        bg = index.data(HEATMAP_BG_ROLE)
        fg = index.data(HEATMAP_FG_ROLE)
        if isinstance(bg, QColor):
            painter.save()
            painter.fillRect(option.rect, bg)
            if option.state & QStyle.State_Selected:
                painter.setPen(QColor(C['accent']))
                painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
            painter.setPen(fg if isinstance(fg, QColor) else QColor(C['text']))
            painter.setFont(option.font)
            painter.drawText(option.rect, Qt.AlignCenter, str(index.data(Qt.DisplayRole) or ''))
            painter.restore()
            return

        super().paint(painter, option, index)


class CellEditor(QLineEdit):
    """
    A QLineEdit that floats exactly over a clicked memory cell.
    Accepts hex (0xFF), binary (0b11), or decimal.  Enter commits, Escape cancels.
    """
    committed = pyqtSignal(int, int)   # addr, new_byte_value

    def __init__(self, parent_viewport, cell_rect, addr, cur_val, font_size=None):
        super().__init__(parent_viewport)
        self.addr    = addr
        self.cur_val = cur_val
        self._font_size = font_size or UI_SETTINGS["memory_font_size"]

        self.setFont(QFont('Menlo', self._font_size))
        self.setAlignment(Qt.AlignCenter)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setText(f'{cur_val:02X}')
        self.selectAll()

        # Style: bright border to signal edit mode
        self.setStyleSheet(f"""
            QLineEdit {{
                background: {C['panel']};
                border: 2px solid {C['accent']};
                border-radius: 3px;
                color: {C['text']};
                font-family: 'Menlo', monospace;
                font-size: {self._font_size}px;
                padding: 0px;
            }}
        """)

        # Size and position exactly over the cell
        self.setGeometry(cell_rect)
        self.show()
        self.setFocus()

        self.returnPressed.connect(self._commit)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def focusOutEvent(self, e):
        # Commit on focus loss (clicking elsewhere)
        self._commit()
        super().focusOutEvent(e)

    def _commit(self):
        if not self.isVisible():
            return
        txt = self.text().strip()
        try:
            if txt.lower().startswith('0x'):
                val = int(txt, 16)
            elif txt.lower().startswith('0b'):
                val = int(txt, 2)
            else:
                val = int(txt, 16) if all(c in '0123456789abcdefABCDEF' for c in txt) else int(txt)
            val &= 0xFF
            self.committed.emit(self.addr, val)
        except ValueError:
            pass   # silently discard bad input
        self.hide()
        self.close()




class MemoryPanel(QGroupBox):
    """The 'Memory' tab: a paged byte/word grid with jump-to, inline editing, heat-map colouring, Hex/Dec toggle and the memory-tools dialog."""
    COLS = 16
    # Emitted when any byte changes (addr=-1 means bulk update)
    cell_written = pyqtSignal(int, int)

    def __init__(self):
        super().__init__("")
        self._mem       = bytearray(TaraCPU.MEM_SIZE)
        self._tools_dlg = None          # MemToolsDialog (lazy)
        self._cell_ed   = None          # active CellEditor widget
        self._heatmap_enabled = bool(MPL_GET_CMAP)
        self._heatmap_cmap_name = DEFAULT_MEMORY_CMAP
        self._heatmap_cmap = self._resolve_cmap(self._heatmap_cmap_name)
        self._font_size = UI_SETTINGS["memory_font_size"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 1, 8, 8)
        layout.setSpacing(4)

        # ── Toolbar ───────────────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Jump to:"))
        self.start_edit = QLineEdit('0x000')
        self.start_edit.setFixedWidth(90)
        self.start_edit.setToolTip("Byte address (hex 0x… or decimal). Press Enter.")
        self.start_edit.returnPressed.connect(self.refresh)
        ctrl.addWidget(self.start_edit)

        prev_btn = QPushButton("◀ Prev")
        prev_btn.setToolTip("Scroll back one block (256 bytes)")
        prev_btn.setMinimumWidth(78)
        prev_btn.clicked.connect(self._prev_block)
        ctrl.addWidget(prev_btn)

        next_btn = QPushButton("Next ▶")
        next_btn.setToolTip("Scroll forward one block (256 bytes)")
        next_btn.setMinimumWidth(82)
        next_btn.clicked.connect(self._next_block)
        ctrl.addWidget(next_btn)

        ctrl.addSpacing(10)

        self.tools_btn = QPushButton("🛠  Memory Tools")
        self.tools_btn.setMinimumWidth(138)
        self.tools_btn.setStyleSheet(
            f"background:{C['navy_soft']};border:1px solid #D8BE9F;"
            f"color:{C['accent']};border-radius:7px;padding:4px 6px;font-size:12px;font-weight:bold;")
        self.tools_btn.clicked.connect(self._open_tools)
        ctrl.addWidget(self.tools_btn)

        self.font_dec_btn = QPushButton("A-")
        self.font_inc_btn = QPushButton("A+")
        for btn in (self.font_dec_btn, self.font_inc_btn):
            self._style_font_button(btn)
            ctrl.addWidget(btn)
        self.font_dec_btn.setToolTip("Decrease memory matrix font size")
        self.font_inc_btn.setToolTip("Increase memory matrix font size")
        self.font_dec_btn.clicked.connect(lambda: self.adjust_font_size(-1))
        self.font_inc_btn.clicked.connect(lambda: self.adjust_font_size(1))

        # One compact control shows the current format; checked means decimal.
        ctrl.addSpacing(4)
        self.format_toggle = QPushButton("Hex")
        self.format_toggle.setCheckable(True)
        self.format_toggle.setFixedSize(54, 28)
        self.format_toggle.setCursor(Qt.PointingHandCursor)
        self.format_toggle.setAccessibleName("Memory values: hexadecimal")
        self.format_toggle.setToolTip("Values shown in hexadecimal. Click to switch to decimal.")
        self.format_toggle.setStyleSheet(f"""
            QPushButton {{ background:{C['panel2']}; color:{C['accent']};
                border:1px solid {C['border']}; border-radius:7px;
                padding:3px 8px; font-size:12px; font-weight:700; }}
            QPushButton:hover {{ border-color:{C['accent2']}; }}
            QPushButton:pressed {{ background:{C['selected']}; color:{C['accent']}; }}
            QPushButton:focus {{ border-color:{C['accent']}; }}
            QPushButton:checked {{ background:{C['selected']}; border-color:{C['accent2']}; }}
        """)
        self.format_toggle.toggled.connect(self._format_toggled)
        ctrl.addWidget(self.format_toggle)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── Hex grid ──────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setFont(self._memory_font())
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setItemDelegate(HeatmapCellDelegate(self.table))
        self.table.setContextMenuPolicy(Qt.NoContextMenu)
        self.table.cellClicked.connect(self._on_cell_click)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['panel']};
                alternate-background-color:{C['row_alt']};
                font-family:'Menlo', 'Fira Code', 'Consolas', monospace;
                font-size:{self._font_size}px;
            }}
            QTableWidget::viewport {{
                background:{C['panel']};
            }}
            QHeaderView {{
                background:{C['panel']};
            }}
            QHeaderView::section {{
                background:{C['panel']};
                border:1px solid {C['border']};
            }}
            QTableCornerButton::section {{
                background:{C['panel']};
                border:1px solid {C['border']};
            }}
        """)
        self.table.horizontalHeader().setStyleSheet(
            f"QHeaderView {{ background:{C['panel']}; }}"
            f"QHeaderView::section {{ background:{C['panel']}; border:1px solid {C['border']}; }}"
        )
        self.table.verticalHeader().setStyleSheet(
            f"QHeaderView {{ background:{C['panel']}; }}"
            f"QHeaderView::section {{ background:{C['panel']}; border:1px solid {C['border']}; }}"
        )
        layout.addWidget(self.table)
        self._apply_font_size()

    def _style_font_button(self, button):
        _apply_font_button_style(button)

    def _format_toggled(self, decimal):
        current, alternate = ('decimal', 'hexadecimal') if decimal else ('hexadecimal', 'decimal')
        self.format_toggle.setText("Dec" if decimal else "Hex")
        self.format_toggle.setAccessibleName("Memory values: " + current)
        self.format_toggle.setToolTip(f"Values shown in {current}. Click to switch to {alternate}.")
        self.refresh()

    def _memory_font(self, size=None, weight=-1):
        font = QFont('Menlo')
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(size or self._font_size)
        if weight != -1:
            font.setWeight(weight)
        return font

    def _apply_font_size(self):
        font = self._memory_font()
        self.table.setFont(font)
        header_font = QFont('Segoe UI')
        header_font.setPixelSize(max(9, self._font_size - 1))
        header_font.setWeight(700)
        self.table.horizontalHeader().setFont(header_font)
        fm = QFontMetrics(font)
        row_height = max(24, fm.height() + 10)
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, row_height)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['panel']};
                alternate-background-color:{C['row_alt']};
                font-family:'Menlo', 'Fira Code', 'Consolas', monospace;
                font-size:{self._font_size}px;
            }}
            QTableWidget::viewport {{
                background:{C['panel']};
            }}
            QHeaderView {{
                background:{C['panel']};
            }}
            QHeaderView::section {{
                background:{C['panel']};
                border:1px solid {C['border']};
            }}
            QTableCornerButton::section {{
                background:{C['panel']};
                border:1px solid {C['border']};
            }}
        """)
        self.font_dec_btn.setEnabled(self._font_size > 9)
        self.font_inc_btn.setEnabled(self._font_size < 24)

    def adjust_font_size(self, delta):
        self._font_size = max(9, min(24, self._font_size + delta))
        save_ui_setting("memory_font_size", self._font_size)
        self._apply_font_size()
        self.refresh()

    # ── public API ────────────────────────────────────────────────────────────
    def update_mem(self, mem):
        self._mem = bytearray(mem)
        self.refresh()

    def _prev_block(self):
        addr = max(0, self._start_addr() - 16 * self.COLS)
        self.start_edit.setText(f'0x{addr:03X}')
        self.refresh()

    def _next_block(self):
        addr = min(TaraCPU.MEM_SIZE - 16 * self.COLS, self._start_addr() + 16 * self.COLS)
        self.start_edit.setText(f'0x{addr:03X}')
        self.refresh()

    def patch_bytes(self, start, data):
        for i, b in enumerate(data):
            a = start + i
            if 0 <= a < TaraCPU.MEM_SIZE:
                self._mem[a] = b & 0xFF

    def get_range(self, start, count):
        """Return a bytes slice of memory for export."""
        end = min(start + count, TaraCPU.MEM_SIZE)
        return bytes(self._mem[start:end])

    def _set_heatmap_enabled(self, enabled):
        self._heatmap_enabled = bool(enabled and self._heatmap_cmap)
        self.refresh()

    def _resolve_cmap(self, name):
        if not (MPL_GET_CMAP and name and name.strip()):
            return None
        try:
            return MPL_GET_CMAP(name.strip())
        except Exception:
            return None

    def _set_heatmap_cmap_name(self, name):
        name = name.strip()
        cmap = self._resolve_cmap(name)
        if cmap is None:
            self._heatmap_cmap = None
            self._heatmap_enabled = False
            self.refresh()
            return

        self._heatmap_cmap_name = name
        self._heatmap_cmap = cmap
        if self._heatmap_enabled:
            self._heatmap_enabled = True
            self.refresh()

    # ── internals ─────────────────────────────────────────────────────────────
    def _start_addr(self):
        s = self.start_edit.text().strip()
        try:
            v = int(s, 16) if s.lower().startswith('0x') else int(s)
            return max(0, min(2046, v))
        except Exception:
            return 0

    def _heatmap_qcolors(self, byte_val):
        if not (self._heatmap_enabled and self._heatmap_cmap):
            return None, None

        try:
            rgba = self._heatmap_cmap(byte_val / 255.0)
        except Exception:
            return None, None

        r, g, b = [max(0, min(255, int(round(ch * 255)))) for ch in rgba[:3]]
        bg = QColor(r, g, b)

        def luminance(color):
            channels = [channel / 255.0 for channel in color.getRgb()[:3]]
            linear = [channel / 12.92 if channel <= 0.04045
                      else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
            return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))

        background_luminance = luminance(bg)
        # Prefer Studio's text colour, switching to white on darker cells.
        # Black covers intermediate shades where both need more contrast.
        for foreground in (C['text'], '#FFFFFF', '#000000'):
            fg = QColor(foreground)
            lo, hi = sorted((background_luminance, luminance(fg)))
            if (hi + 0.05) / (lo + 0.05) >= 4.5:
                break
        return bg, fg

    def refresh(self):
        # Kill any open inline editor first
        if self._cell_ed and not self._cell_ed.isHidden():
            self._cell_ed.hide()

        start = self._start_addr()
        ROWS, COLS = 16, self.COLS

        self.table.setColumnCount(COLS + 1)
        self.table.setRowCount(ROWS)
        hdrs = ['Address'] + [f'+{i:X}' for i in range(COLS)]
        self.table.setHorizontalHeaderLabels(hdrs)
        font = self._memory_font()
        addr_font = self._memory_font(weight=QFont.Bold)
        self.table.setFont(font)
        fm = QFontMetrics(font)
        hexfmt = not self.format_toggle.isChecked()
        cell_width = max(30, fm.horizontalAdvance('FF' if hexfmt else '255') + 18)
        addr_width = max(82, fm.horizontalAdvance('0x0000') + 22)
        row_height = max(24, fm.height() + 10)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, addr_width)
        for c in range(1, COLS + 1):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, cell_width)
        vh = self.table.verticalHeader()
        vh.setDefaultSectionSize(row_height)
        vh.setSectionResizeMode(QHeaderView.Fixed)

        for row in range(ROWS):
            self.table.setRowHeight(row, row_height)
            base = start + row * COLS
            ai = QTableWidgetItem(f'0x{base:04X}')
            ai.setFont(addr_font)
            ai.setForeground(QColor(C['dim']))
            ai.setData(Qt.UserRole, -1)
            self.table.setItem(row, 0, ai)

            for col in range(COLS):
                addr = base + col
                if 0 <= addr < TaraCPU.MEM_SIZE:
                    v   = self._mem[addr]
                    txt = f'{v:02X}' if hexfmt else f'{v:d}'
                    clr = C['text'] if v else C['dim']
                else:
                    txt, clr = '--', C['dim']

                item = QTableWidgetItem(txt)
                item.setFont(font)
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, addr)
                if 0 <= addr < TaraCPU.MEM_SIZE:
                    bg, fg = self._heatmap_qcolors(v)
                    if bg is not None:
                        item.setData(HEATMAP_BG_ROLE, bg)
                        item.setData(HEATMAP_FG_ROLE, fg)
                    else:
                        item.setForeground(QColor(clr))
                    item.setToolTip(
                        f'0x{addr:04X}  →  0x{self._mem[addr]:02X}  '
                        f'({self._mem[addr]})  b{self._mem[addr]:08b}'
                    )
                else:
                    item.setForeground(QColor(clr))
                self.table.setItem(row, col + 1, item)

    def _on_cell_click(self, row, col):
        if col == 0:
            return
        item = self.table.item(row, col)
        if item is None:
            return
        addr = item.data(Qt.UserRole)
        if addr is None or not (0 <= addr < TaraCPU.MEM_SIZE):
            return

        # Close any previous editor
        if self._cell_ed and not self._cell_ed.isHidden():
            self._cell_ed.hide()

        # Compute cell rect in viewport coordinates
        vp        = self.table.viewport()
        cell_rect = self.table.visualItemRect(item)

        ed = CellEditor(vp, cell_rect, addr, self._mem[addr], self._font_size)
        ed.committed.connect(self._on_edit_committed)
        ed.show()
        ed.setFocus()
        self._cell_ed = ed

    def _on_edit_committed(self, addr, val):
        self._mem[addr] = val
        self.cell_written.emit(addr, val)
        self.refresh()

    # ── Memory Tools window ───────────────────────────────────────────────────
    def _open_tools(self):
        if self._tools_dlg is None:
            self._tools_dlg = MemToolsDialog(
                heatmap_enabled=self._heatmap_enabled,
                heatmap_cmap_name=self._heatmap_cmap_name,
            )
            self._tools_dlg.mem_changed.connect(self._on_bulk_write)
            self._tools_dlg.export_requested.connect(self._on_export_requested)
            self._tools_dlg.heatmap_enabled_changed.connect(self._set_heatmap_enabled)
            self._tools_dlg.heatmap_cmap_changed.connect(self._set_heatmap_cmap_name)
        pos = self.tools_btn.mapToGlobal(self.tools_btn.rect().bottomLeft())
        self._tools_dlg.move(pos)
        self._tools_dlg.show()
        self._tools_dlg.raise_()

    def _on_bulk_write(self, start, data):
        self.patch_bytes(start, data)
        self.start_edit.setText(f'0x{start:03X}')
        self.refresh()
        self.cell_written.emit(-1, 0)   # signal bulk update

    def _on_export_requested(self, start, count, path):
        mem_slice = self.get_range(start, count)
        include_zeros = self._tools_dlg.exp_zeros_cb.isChecked()
        self._tools_dlg.do_write_csv(mem_slice, start, path, include_zeros)
