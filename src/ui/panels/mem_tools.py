# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — the bulk memory-tools dialog (random fill and
CSV import/export of a memory range), used by the Memory panel."""

import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.paths import DEFAULT_MEMORY_DUMP_PATH, ensure_config_dirs
from src.simulation.cpu import TaraCPU
from src.ui.theme import C, MONO_SM

from src.ui.panels.common import DEFAULT_MEMORY_CMAP, MPL_CMAP_NAMES, MPL_GET_CMAP


class MemToolsDialog(QWidget):
    """
    Standalone tools window with three tabs:
      1. Random Fill   — write N random bytes/words from a start address
      2. CSV Import    — load a CSV (address, hex, decimal) into memory
      3. CSV Export    — save a memory range to CSV
    Emits mem_changed(start_addr, bytes_data) for random fill and CSV import.
    Emits export_requested(start, count, path) for CSV export.
    """
    mem_changed       = pyqtSignal(int, bytes)   # start, raw bytes to write
    export_requested  = pyqtSignal(int, int, str) # start, count, filepath
    heatmap_enabled_changed = pyqtSignal(bool)
    heatmap_cmap_changed = pyqtSignal(str)

    _STYLE = f"""
        QWidget   {{ background:{C['panel']}; color:{C['text']}; font-size:12px; }}
        QGroupBox {{ border:1px solid {C['border']}; border-radius:6px;
                     margin-top:10px; padding:10px 8px 8px 8px;
                     color:{C['accent']}; font-weight:bold; font-size:12px; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 4px; }}
        QLabel    {{ color:{C['dim']}; font-size:11px; }}
        QLabel.title {{ color:{C['text']}; font-weight:bold; font-size:12px; }}
        QLineEdit, QSpinBox {{
            background:{C['bg']}; border:1px solid {C['border']};
            border-radius:4px; color:{C['text']}; padding:4px 8px;
            font-family:'Menlo',monospace; font-size:12px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{ width:16px; }}
        QPushButton {{
            background:{C['bg']}; border:1px solid {C['border']};
            border-radius:5px; color:{C['text']}; padding:5px 14px; font-size:12px;
        }}
        QPushButton:hover  {{ border-color:{C['accent']}; color:{C['accent']}; }}
        QPushButton:pressed {{ background:{C['highlight']}; }}
        QComboBox {{
            background:{C['bg']}; border:1px solid {C['border']};
            border-radius:4px; color:{C['text']}; padding:4px 8px;
        }}
        QComboBox QAbstractItemView {{
            background:{C['panel']}; color:{C['text']};
            selection-background-color:{C['highlight']};
        }}
        QTabWidget::pane {{
            border:1px solid {C['border']}; border-radius:4px;
            background:{C['bg']};
        }}
        QTabBar::tab {{
            background:{C['panel2']}; color:{C['accent']};
            border:1px solid {C['border']}; border-bottom:none;
            border-radius:4px 4px 0 0; padding:5px 18px; margin-right:2px;
        }}
        QTabBar::tab:selected {{ color:{C['accent']}; background:{C['panel2']}; border-color:{C['accent2']}; }}
        QTableWidget {{
            background:{C['bg']}; border:1px solid {C['border']};
            gridline-color:{C['border']}; color:{C['text']};
        }}
        QHeaderView::section {{
            background:{C['panel']}; color:{C['dim']}; border:none;
            border-right:1px solid {C['border']}; border-bottom:1px solid {C['border']};
            padding:3px 6px; font-size:11px; font-weight:bold;
        }}
    """

    def __init__(self, heatmap_enabled=False, heatmap_cmap_name=DEFAULT_MEMORY_CMAP, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle("Memory Tools")
        self.setStyleSheet(self._STYLE)
        self.resize(460, 520)
        self._heatmap_enabled = bool(heatmap_enabled)
        self._heatmap_cmap_name = heatmap_cmap_name or DEFAULT_MEMORY_CMAP

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self._make_random_tab(),  "⚡  Random Fill")
        tabs.addTab(self._make_import_tab(),  "📥  CSV Import")
        tabs.addTab(self._make_export_tab(),  "📤  CSV Export")
        tabs.addTab(self._make_heatmap_tab(), "Heatmap")
        root.addWidget(tabs)

    # ── Tab 1: Random Fill ────────────────────────────────────────────────────
    def _make_random_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        box = QGroupBox("Write random values into memory")
        grid = QGridLayout(box)
        grid.setSpacing(8)
        grid.setColumnStretch(1, 1)

        def row(label, widget, r):
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(widget, r, 1)

        self.rnd_addr = QLineEdit('0x400')
        self.rnd_addr.setToolTip("Start address (hex 0x… or decimal)")
        row("Start address:", self.rnd_addr, 0)

        self.rnd_n = QSpinBox()
        self.rnd_n.setRange(1, TaraCPU.MEM_SIZE)
        self.rnd_n.setValue(256)
        row("Count (N):", self.rnd_n, 1)

        self.rnd_unit = QComboBox()
        self.rnd_unit.addItems(["Bytes  (8-bit, 0–255)", "Words  (16-bit, even address)"])
        row("Unit:", self.rnd_unit, 2)

        # value range on one line
        range_w = QWidget()
        range_h = QHBoxLayout(range_w)
        range_h.setContentsMargins(0, 0, 0, 0)
        self.rnd_lo = QLineEdit('0')
        self.rnd_lo.setMaximumWidth(65)
        self.rnd_hi = QLineEdit('255')
        self.rnd_hi.setMaximumWidth(65)
        range_h.addWidget(self.rnd_lo)
        range_h.addWidget(QLabel("  to  "))
        range_h.addWidget(self.rnd_hi)
        range_h.addStretch()
        grid.addWidget(QLabel("Value range:"), 3, 0)
        grid.addWidget(range_w, 3, 1)

        lay.addWidget(box)

        self.rnd_btn = QPushButton("⚡  Generate & Write")
        self.rnd_btn.setStyleSheet(f"background:{C['teal_soft']};border:1px solid {C['accent2']};color:{C['accent2']};font-weight:bold;padding:7px;border-radius:7px;")
        self.rnd_btn.clicked.connect(self._do_random)
        lay.addWidget(self.rnd_btn)

        self.rnd_status = QLabel("")
        self.rnd_status.setWordWrap(True)
        lay.addWidget(self.rnd_status)
        lay.addStretch()
        return w

    # ── Tab 2: CSV Import ─────────────────────────────────────────────────────
    def _make_import_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel(
            "CSV format:  <b>address, hex, decimal</b><br>"
            "Header row optional.  Address column drives where data is written.<br>"
            "Example row:  <code>0x0400, FF, 255</code>"
        )
        info.setStyleSheet(f"color:{C['dim']};font-size:11px;")
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        lay.addWidget(info)

        # Preview table
        self.imp_preview = QTableWidget()
        self.imp_preview.setColumnCount(3)
        self.imp_preview.setHorizontalHeaderLabels(['Address', 'Hex', 'Decimal'])
        self.imp_preview.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.imp_preview.verticalHeader().setVisible(False)
        self.imp_preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.imp_preview.setMaximumHeight(160)
        self.imp_preview.setFont(MONO_SM)
        lay.addWidget(self.imp_preview)

        self._imp_data = []   # list of (addr, byte_val) parsed from CSV

        btn_row = QHBoxLayout()
        self.imp_browse_btn = QPushButton("📂  Browse CSV…")
        self.imp_browse_btn.clicked.connect(self._browse_csv_import)
        btn_row.addWidget(self.imp_browse_btn)
        self.imp_apply_btn = QPushButton("⬇  Write to Memory")
        self.imp_apply_btn.setStyleSheet(f"background:{C['teal_soft']};border:1px solid {C['accent2']};color:{C['accent2']};font-weight:bold;padding:6px;border-radius:7px;")
        self.imp_apply_btn.setEnabled(False)
        self.imp_apply_btn.clicked.connect(self._apply_csv_import)
        btn_row.addWidget(self.imp_apply_btn)
        lay.addLayout(btn_row)

        self.imp_status = QLabel("")
        self.imp_status.setWordWrap(True)
        lay.addWidget(self.imp_status)
        lay.addStretch()
        return w

    # ── Tab 3: CSV Export ─────────────────────────────────────────────────────
    def _make_export_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel(
            "Exports a memory range to a CSV file.<br>"
            "Columns: <b>address, hex, decimal</b>"
        )
        info.setStyleSheet(f"color:{C['dim']};font-size:11px;")
        info.setTextFormat(Qt.RichText)
        lay.addWidget(info)

        box = QGroupBox("Export range")
        grid = QGridLayout(box)
        grid.setSpacing(8)
        grid.setColumnStretch(1, 1)

        self.exp_addr = QLineEdit('0x400')
        self.exp_addr.setToolTip("Start address (hex or decimal)")
        grid.addWidget(QLabel("Start address:"), 0, 0)
        grid.addWidget(self.exp_addr, 0, 1)

        self.exp_n = QSpinBox()
        self.exp_n.setRange(1, TaraCPU.MEM_SIZE)
        self.exp_n.setValue(256)
        grid.addWidget(QLabel("Count (bytes):"), 1, 0)
        grid.addWidget(self.exp_n, 1, 1)

        self.exp_zeros_cb = QCheckBox("Include zero bytes")
        self.exp_zeros_cb.setChecked(True)
        self.exp_zeros_cb.setStyleSheet(f"color:{C['dim']};")
        grid.addWidget(self.exp_zeros_cb, 2, 0, 1, 2)

        lay.addWidget(box)

        self.exp_btn = QPushButton("📤  Save CSV…")
        self.exp_btn.setStyleSheet(f"background:{C['navy_soft']};border:1px solid #9BB8FF;color:{C['accent']};font-weight:bold;padding:7px;border-radius:7px;")
        self.exp_btn.clicked.connect(self._do_export)
        lay.addWidget(self.exp_btn)

        self.exp_status = QLabel("")
        self.exp_status.setWordWrap(True)
        lay.addWidget(self.exp_status)
        lay.addStretch()
        return w

    def _make_heatmap_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        box = QGroupBox("Memory heatmap")
        grid = QGridLayout(box)
        grid.setSpacing(8)
        grid.setColumnStretch(1, 1)

        self.heatmap_cb = QCheckBox("Color visible memory cells by byte value")
        self.heatmap_cb.setChecked(self._heatmap_enabled and MPL_GET_CMAP is not None)
        self.heatmap_cb.toggled.connect(self._heatmap_toggled)
        grid.addWidget(self.heatmap_cb, 0, 0, 1, 2)

        grid.addWidget(QLabel("Colormap:"), 1, 0)
        self.cmap_edit = QLineEdit(self._heatmap_cmap_name)
        self.cmap_edit.setToolTip("TARA: cream → coffee → maroon. You can also enter a Matplotlib colormap name.")
        if MPL_GET_CMAP:
            completer = QCompleter(MPL_CMAP_NAMES, self.cmap_edit)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)
            self.cmap_edit.setCompleter(completer)
            self.cmap_edit.returnPressed.connect(self._heatmap_cmap_edited)
            self.cmap_edit.editingFinished.connect(self._heatmap_cmap_edited)
        else:
            self.heatmap_cb.setEnabled(False)
            self.heatmap_cb.setToolTip("Install matplotlib to enable heatmap mode.")
            self.cmap_edit.setText("matplotlib unavailable")
            self.cmap_edit.setEnabled(False)
        grid.addWidget(self.cmap_edit, 1, 1)

        lay.addWidget(box)
        self.heatmap_status = QLabel("")
        self.heatmap_status.setWordWrap(True)
        lay.addWidget(self.heatmap_status)
        lay.addStretch()
        return w

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _parse_addr(txt):
        txt = txt.strip()
        return int(txt, 16) if txt.lower().startswith('0x') else int(txt)

    def _set_status(self, lbl, ok, msg):
        lbl.setText(msg)
        lbl.setStyleSheet(f"color:{C['accent2'] if ok else C['danger']};font-size:11px;")

    def _resolve_cmap(self, name):
        if not (MPL_GET_CMAP and name and name.strip()):
            return None
        try:
            return MPL_GET_CMAP(name.strip())
        except Exception:
            return None

    def _heatmap_toggled(self, enabled):
        if enabled:
            name = self.cmap_edit.text().strip()
            if self._resolve_cmap(name) is None:
                self.heatmap_cb.blockSignals(True)
                self.heatmap_cb.setChecked(False)
                self.heatmap_cb.blockSignals(False)
                self._set_status(self.heatmap_status, False, "Unknown Matplotlib colormap name.")
                self.heatmap_enabled_changed.emit(False)
                return
            self._heatmap_cmap_name = name
            self.heatmap_cmap_changed.emit(name)

        self._heatmap_enabled = bool(enabled)
        self._set_status(
            self.heatmap_status,
            True,
            "Heatmap enabled." if enabled else "Heatmap disabled."
        )
        self.heatmap_enabled_changed.emit(self._heatmap_enabled)

    def _heatmap_cmap_edited(self):
        name = self.cmap_edit.text().strip()
        cmap = self._resolve_cmap(name)
        if cmap is None:
            self.cmap_edit.setStyleSheet(f"border:1px solid {C['danger']};")
            self._set_status(self.heatmap_status, False, "Unknown Matplotlib colormap name.")
            return

        self.cmap_edit.setStyleSheet("")
        self._heatmap_cmap_name = name
        self._set_status(self.heatmap_status, True, f"Colormap set to {name}.")
        self.heatmap_cmap_changed.emit(name)
        if self.heatmap_cb.isChecked():
            self.heatmap_enabled_changed.emit(True)

    # Random fill
    def _do_random(self):
        import random
        try:
            start = self._parse_addr(self.rnd_addr.text())
            n     = self.rnd_n.value()
            lo    = int(self.rnd_lo.text())
            hi    = int(self.rnd_hi.text())
            words = self.rnd_unit.currentIndex() == 1
        except Exception as e:
            self._set_status(self.rnd_status, False, f"⚠ {e}")
            return
        if lo > hi:
            lo, hi = hi, lo

        data = bytearray()
        if words:
            start &= ~1   # align to even
            for _ in range(n):
                v = random.randint(max(0, lo), min(65535, hi))
                data.append((v >> 8) & 0xFF)
                data.append(v & 0xFF)
        else:
            for _ in range(n):
                data.append(random.randint(max(0, lo), min(255, hi)))

        end = min(start + len(data), TaraCPU.MEM_SIZE)
        data = data[:end - start]
        self.mem_changed.emit(start, bytes(data))
        unit = "word" if words else "byte"
        self._set_status(self.rnd_status, True,
            f"✓ Wrote {n} {unit}s → 0x{start:04X} – 0x{start+len(data)-1:04X}")

    # CSV import
    def _browse_csv_import(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        self._load_csv_preview(path)

    def _load_csv_preview(self, path):
        import csv
        self._imp_data = []
        self.imp_preview.setRowCount(0)
        errors = 0
        try:
            with open(path, newline='', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                for raw in reader:
                    # skip blank / comment / header rows
                    if not raw:
                        continue
                    row = [c.strip() for c in raw]
                    # skip header row (first cell can't be parsed as address)
                    try:
                        addr = self._parse_addr(row[0])
                    except Exception:
                        continue
                    # value: prefer hex column, fall back to decimal
                    val = None
                    if len(row) >= 2 and row[1]:
                        try:
                            val = int(row[1], 16) & 0xFF
                        except Exception:
                            pass
                    if val is None and len(row) >= 3 and row[2]:
                        try:
                            val = int(row[2]) & 0xFF
                        except Exception:
                            errors += 1
                            continue
                    if val is None:
                        errors += 1
                        continue
                    self._imp_data.append((addr, val))

                    # Show up to 200 rows in preview
                    if len(self._imp_data) <= 200:
                        r = self.imp_preview.rowCount()
                        self.imp_preview.insertRow(r)
                        for c, txt in enumerate([f'0x{addr:04X}', f'{val:02X}', str(val)]):
                            item = QTableWidgetItem(txt)
                            item.setTextAlignment(Qt.AlignCenter)
                            self.imp_preview.setItem(r, c, item)

        except Exception as e:
            self._set_status(self.imp_status, False, f"⚠ Read error: {e}")
            return

        if not self._imp_data:
            self._set_status(self.imp_status, False, "⚠ No valid rows found in CSV")
            self.imp_apply_btn.setEnabled(False)
        else:
            n = len(self._imp_data)
            skipped = f"  ({errors} skipped)" if errors else ""
            self._set_status(self.imp_status, True,
                f"✓ Parsed {n} bytes from {os.path.basename(path)}{skipped}.  Click 'Write to Memory'.")
            self.imp_apply_btn.setEnabled(True)

    def _apply_csv_import(self):
        if not self._imp_data:
            return
        # Build a sparse write: group consecutive addresses together
        # then emit each contiguous run
        self._imp_data.sort(key=lambda x: x[0])
        start = self._imp_data[0][0]
        prev  = start - 1
        run   = bytearray()
        runs  = []
        for addr, val in self._imp_data:
            if addr != prev + 1 and run:
                runs.append((start, bytes(run)))
                start = addr
                run   = bytearray()
            run.append(val)
            prev = addr
        if run:
            runs.append((start, bytes(run)))

        for s, data in runs:
            self.mem_changed.emit(s, data)

        n = len(self._imp_data)
        self._set_status(self.imp_status, True, f"✓ Written {n} bytes to memory ({len(runs)} run(s)).")

    # CSV export
    def _do_export(self):
        from PyQt5.QtWidgets import QFileDialog
        ensure_config_dirs()
        try:
            start = self._parse_addr(self.exp_addr.text())
            count = self.exp_n.value()
        except Exception as e:
            self._set_status(self.exp_status, False, f"⚠ {e}")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", DEFAULT_MEMORY_DUMP_PATH, "CSV files (*.csv)")
        if not path:
            return

        # Signal main window to supply memory bytes
        self.export_requested.emit(start, count, path)

    def do_write_csv(self, mem_bytes, start, path, include_zeros):
        """Called by main window after export_requested; receives raw memory."""
        import csv
        count = len(mem_bytes)
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['address', 'hex', 'decimal'])
                written = 0
                for i, val in enumerate(mem_bytes):
                    if not include_zeros and val == 0:
                        continue
                    addr = start + i
                    w.writerow([f'0x{addr:04X}', f'{val:02X}', str(val)])
                    written += 1
            self._set_status(self.exp_status, True,
                f"✓ Exported {written} rows → {os.path.basename(path)}")
        except Exception as e:
            self._set_status(self.exp_status, False, f"⚠ {e}")
