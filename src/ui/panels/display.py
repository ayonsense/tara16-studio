# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — The pixel-display tab: the framebuffer raster widget and its colour/import dialogs.

Classes:
  DisplayRasterWidget -- Widget that renders the 64x64 framebuffer (memory 0x600-0x7FF) as a scaled pixel raster, with an optional pixel grid.
  DisplayColorDialog -- Small dialog to choose the on/off pixel colours for the display.
  DisplayImportDialog -- Dialog that imports an image file, scales/packs it to a 1-bpp glyph, and writes it into memory.
  DisplayPanel -- The 'Display' tab: hosts the raster widget plus its controls (colours, grid, image import).
"""

import math

from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import QColor, QFont, QPainter, QImage
from PyQt5.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QFileDialog, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from src.simulation.cpu import TaraCPU
from src.ui.theme import C

from src.ui.panels.common import DISPLAY_PIXEL_COLORS


class DisplayRasterWidget(QWidget):
    """Widget that renders the 64x64 framebuffer (memory 0x600-0x7FF) as a scaled pixel raster, with an optional pixel grid."""
    pixel_toggled = pyqtSignal(int, int)   # pixel index, new pixel value
    key_bits_changed = pyqtSignal(int)     # live one-hot keyboard bitmask

    # Maps keys to the one-hot bits read by programs at the keyboard register.
    #   bit0=UP  bit1=DOWN  bit2=LEFT  bit3=RIGHT  bit4=QUIT
    # Arrow keys and WASD both work; Q quits. These only fire while the display
    # canvas has focus, so they never clash with typing in the editor.
    GAME_KEYS = {
        Qt.Key_Up:    0x01, Qt.Key_W: 0x01,
        Qt.Key_Down:  0x02, Qt.Key_S: 0x02,
        Qt.Key_Left:  0x04, Qt.Key_A: 0x04,
        Qt.Key_Right: 0x08, Qt.Key_D: 0x08,
        Qt.Key_Q:     0x10,
    }

    def __init__(self, width, height, parent=None):
        super().__init__(parent)
        self.pixel_width = width
        self.pixel_height = height
        self._pixels = bytearray(width * height)
        self._cell_w = 1.0
        self._cell_h = 1.0
        self._origin = (0, 0)
        self._grid_rect = QRect()
        self._grid_visible = False
        self._pixel_colors = list(DISPLAY_PIXEL_COLORS)
        self._keys_down = 0
        self.setMinimumSize(width * 5 + 42, height * 5 + 24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_grid_visible(self, visible):
        self._grid_visible = visible
        self.update()

    def set_pixel_colors(self, colors):
        self._pixel_colors = list(colors[:2])
        while len(self._pixel_colors) < 2:
            self._pixel_colors.append(DISPLAY_PIXEL_COLORS[len(self._pixel_colors)])
        self.update()

    def set_pixels(self, pixels):
        self._pixels = bytearray(pixels[:self.pixel_width * self.pixel_height])
        needed = self.pixel_width * self.pixel_height - len(self._pixels)
        if needed > 0:
            self._pixels.extend(b'\x00' * needed)
        self.update()

    def _label_step(self, count, pixels, min_spacing):
        raw_step = max(1, math.ceil((count * min_spacing) / max(1, pixels)))
        for step in (1, 2, 4, 8, 16, 32, 64):
            if raw_step <= step:
                return step
        return raw_step

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(C['panel']))

        left_axis = 34
        bottom_axis = 20
        top_pad = 2
        right_pad = 2
        grid_w = max(1, self.width() - left_axis - right_pad)
        grid_h = max(1, self.height() - top_pad - bottom_axis)
        ox = left_axis
        oy = top_pad
        self._cell_w = grid_w / self.pixel_width
        self._cell_h = grid_h / self.pixel_height
        self._origin = (ox, oy)
        self._grid_rect = QRect(ox, oy, grid_w, grid_h)

        for y in range(self.pixel_height):
            for x in range(self.pixel_width):
                val = self._pixels[y * self.pixel_width + x]
                color = QColor(self._pixel_colors[1 if val else 0])
                x0 = round(ox + x * self._cell_w)
                display_y = self.pixel_height - 1 - y
                y0 = round(oy + display_y * self._cell_h)
                x1 = round(ox + (x + 1) * self._cell_w)
                y1 = round(oy + (display_y + 1) * self._cell_h)
                painter.fillRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0), color)

        painter.setFont(QFont('Menlo', 7))

        if self._grid_visible:
            painter.setPen(QColor('#E4D7CB'))
            for x in range(self.pixel_width + 1):
                px = round(ox + x * self._cell_w)
                painter.drawLine(px, oy, px, oy + grid_h)
            for y in range(self.pixel_height + 1):
                py = round(oy + y * self._cell_h)
                painter.drawLine(ox, py, ox + grid_w, py)

        painter.setPen(QColor(C['dim']))
        x_step = self._label_step(self.pixel_width, grid_w, 23)
        y_step = self._label_step(self.pixel_height, grid_h, 13)
        x_labels = list(range(0, self.pixel_width, x_step))
        y_labels = list(range(0, self.pixel_height, y_step))
        if x_labels[-1] != self.pixel_width - 1:
            x_labels.append(self.pixel_width - 1)
        if y_labels[-1] != self.pixel_height - 1:
            y_labels.append(self.pixel_height - 1)

        for x in x_labels:
            px = round(ox + (x + 0.5) * self._cell_w)
            painter.drawLine(px, oy + grid_h, px, oy + grid_h + 3)
            painter.drawText(px - 14, oy + grid_h + 4, 28, bottom_axis - 4, Qt.AlignCenter, str(x))

        for y in y_labels:
            py = round(oy + grid_h - (y + 0.5) * self._cell_h)
            painter.drawLine(ox - 3, py, ox, py)
            painter.drawText(0, py - 6, left_axis - 6, 12, Qt.AlignRight | Qt.AlignVCenter, str(y))

    def mousePressEvent(self, event):
        ox, oy = self._origin
        if not self._grid_rect.contains(event.pos()):
            return
        x = int((event.x() - ox) / self._cell_w)
        y = self.pixel_height - 1 - int((event.y() - oy) / self._cell_h)
        if 0 <= x < self.pixel_width and 0 <= y < self.pixel_height:
            index = y * self.pixel_width + x
            new_val = self._pixels[index] ^ 0x01
            self._pixels[index] = new_val
            self.pixel_toggled.emit(index, new_val)
            self.update()

    def keyPressEvent(self, e):
        bit = self.GAME_KEYS.get(e.key())
        if bit is None:
            super().keyPressEvent(e)
            return
        updated = self._keys_down | bit
        if updated != self._keys_down:
            self._keys_down = updated
            self.key_bits_changed.emit(updated)
        e.accept()

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return                      # ignore synthetic auto-repeat releases
        bit = self.GAME_KEYS.get(e.key())
        if bit is None:
            super().keyReleaseEvent(e)
            return
        updated = self._keys_down & ~bit
        if updated != self._keys_down:
            self._keys_down = updated
            self.key_bits_changed.emit(updated)
        e.accept()


class DisplayColorDialog(QDialog):
    """Small dialog to choose the on/off pixel colours for the display."""
    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Display Colors")
        self._colors = [QColor(c) for c in colors[:2]]
        while len(self._colors) < 2:
            self._colors.append(QColor('#000000'))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self._buttons = []
        for idx, label in enumerate(("0", "1")):
            grid.addWidget(QLabel(label), idx, 0)
            btn = QPushButton()
            btn.setFixedSize(78, 28)
            btn.clicked.connect(lambda _checked=False, i=idx: self._pick_color(i))
            self._buttons.append(btn)
            grid.addWidget(btn, idx, 1)
            self._update_button(idx)
        layout.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_button(self, idx):
        color = self._colors[idx].name().upper()
        self._buttons[idx].setText(color)
        self._buttons[idx].setStyleSheet(
            f"background:{color};border:1px solid {C['border']};border-radius:6px;"
            f"color:{'#FFFFFF' if self._colors[idx].lightness() < 110 else C['text']};"
            "font-size:11px;font-weight:bold;")

    def _pick_color(self, idx):
        color = QColorDialog.getColor(self._colors[idx], self, f"Color for {idx}")
        if color.isValid():
            self._colors[idx] = color
            self._update_button(idx)

    def colors(self):
        return [c.name().upper() for c in self._colors]


class DisplayImportDialog(QDialog):
    """Dialog that imports an image file, scales/packs it to a 1-bpp glyph, and writes it into memory."""
    def __init__(self, image_size, default_addr, display_base, display_width, display_height, display_bytes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Image")
        self._image_size = image_size
        self._default_addr = default_addr
        self._display_base = display_base
        self._display_width = display_width
        self._display_height = display_height
        self._display_bytes = display_bytes

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        source_lbl = QLabel(f"Source: {image_size.width()} x {image_size.height()} px")
        source_lbl.setStyleSheet(f"color:{C['dim']};font-size:11px;")
        layout.addWidget(source_lbl)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 128)
        self.width_spin.setValue(min(64, max(1, image_size.width())))
        self.width_spin.setSuffix(" px")
        grid.addWidget(QLabel("Width"), 0, 0)
        grid.addWidget(self.width_spin, 0, 1)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 128)
        self.height_spin.setValue(min(64, max(1, image_size.height())))
        self.height_spin.setSuffix(" px")
        grid.addWidget(QLabel("Height"), 1, 0)
        grid.addWidget(self.height_spin, 1, 1)

        self.addr_edit = QLineEdit(f"0x{default_addr:04X}")
        self.addr_edit.setToolTip("Destination byte address, e.g. 0x0400.")
        grid.addWidget(QLabel("Start"), 2, 0)
        grid.addWidget(self.addr_edit, 2, 1)

        self.format_combo = QComboBox()
        self.format_combo.addItems([
            "Auto",
            "Display framebuffer",
            "Glyph asset",
        ])
        self.format_combo.setToolTip("Auto uses framebuffer layout inside display memory, glyph layout elsewhere.")
        grid.addWidget(QLabel("Format"), 3, 0)
        grid.addWidget(self.format_combo, 3, 1)
        layout.addLayout(grid)

        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{C['dim']};font-size:11px;")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.width_spin.valueChanged.connect(self._update_summary)
        self.height_spin.valueChanged.connect(self._update_summary)
        self.addr_edit.textChanged.connect(self._update_summary)
        self.format_combo.currentTextChanged.connect(self._update_summary)
        self._update_summary()

    def _parse_addr(self):
        raw = self.addr_edit.text().strip()
        if not raw:
            raise ValueError("Missing destination address.")
        return int(raw, 16) if raw.lower().startswith("0x") else int(raw)

    def output_width(self):
        return self.width_spin.value()

    def output_height(self):
        return self.height_spin.value()

    def start_addr(self):
        return self._parse_addr()

    def storage_mode(self):
        fmt = self.format_combo.currentText()
        if fmt == "Display framebuffer":
            return "framebuffer"
        if fmt == "Glyph asset":
            return "glyph"
        try:
            start = self._parse_addr()
        except Exception:
            return "glyph"
        display_end = self._display_base + self._display_bytes
        return "framebuffer" if self._display_base <= start < display_end else "glyph"

    def byte_count(self):
        if self.storage_mode() == "framebuffer":
            return self._display_bytes
        return 2 + math.ceil(self.output_width() / 8) * self.output_height()

    def _update_summary(self):
        ok = True
        try:
            start = self._parse_addr()
            width = self.output_width()
            height = self.output_height()
            if self.storage_mode() == "framebuffer":
                display_end = self._display_base + self._display_bytes
                pixel_start = (start - self._display_base) * 8
                x = pixel_start % self._display_width
                y = pixel_start // self._display_width
                ok = (
                    self._display_base <= start < display_end
                    and x + width <= self._display_width
                    and y + height <= self._display_height
                )
                text = (
                    f"Display framebuffer: draws at pixel x={x}, y={y} with "
                    f"{self._display_width}-pixel row stride; writes "
                    f"0x{self._display_base:04X}-0x{display_end - 1:04X}."
                )
                if not ok:
                    text += " Image must fit inside the visible display from that start address."
            else:
                count = self.byte_count()
                end = start + count - 1
                ok = 0 <= start < TaraCPU.MEM_SIZE and end < TaraCPU.MEM_SIZE
                text = (
                    f"Glyph asset: {count} bytes at 0x{start:04X}-0x{end:04X}; "
                    "byte 0=width, byte 1=height, then packed row-major pixels."
                )
                if not ok:
                    text += f" Destination must fit inside 0x0000-0x{TaraCPU.MEM_SIZE - 1:04X}."
        except Exception as e:
            ok = False
            text = str(e)
        self.summary.setText(text)
        self.summary.setStyleSheet(f"color:{C['dim'] if ok else C['danger']};font-size:11px;")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)


class DisplayPanel(QGroupBox):
    """The 'Display' tab: hosts the raster widget plus its controls (colours, grid, image import)."""
    DISPLAY_BASE = 0x0600
    DISPLAY_WIDTH = 64
    DISPLAY_HEIGHT = 64
    DISPLAY_SIZE = DISPLAY_WIDTH * DISPLAY_HEIGHT
    DISPLAY_BYTES = DISPLAY_SIZE // 8
    KEY_REGISTER = 0x05FF          # live keyboard bits read by programs (LDB)

    memory_written = pyqtSignal(int, int)
    memory_region_written = pyqtSignal(int, object)
    key_register_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__("")
        self._mem = bytearray(TaraCPU.MEM_SIZE)
        self._display_bytes = bytes(self.DISPLAY_BYTES)
        self._pixel_colors = list(DISPLAY_PIXEL_COLORS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 8)
        layout.setSpacing(7)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.grid_btn = QPushButton("Grid OFF")
        self.grid_btn.setCheckable(True)
        self.grid_btn.setChecked(False)
        self.grid_btn.setMinimumHeight(28)
        self.grid_btn.setStyleSheet(
            f"background:{C['navy_soft']};border:1px solid #D8BE9F;"
            f"color:{C['accent']};border-radius:7px;padding:3px 10px;font-size:12px;font-weight:bold;")
        self.grid_btn.clicked.connect(self._toggle_grid)
        header.addWidget(self.grid_btn)
        self.color_btn = QPushButton("Colors")
        self.color_btn.setMinimumHeight(28)
        self.color_btn.setStyleSheet(
            f"background:#FFFFFF;border:1px solid {C['border']};"
            f"color:{C['accent']};border-radius:7px;padding:3px 10px;font-size:12px;font-weight:bold;")
        self.color_btn.clicked.connect(self._configure_colors)
        header.addWidget(self.color_btn)
        self.import_btn = QPushButton("Import Image")
        self.import_btn.setMinimumHeight(28)
        self.import_btn.setStyleSheet(
            f"background:#FFFFFF;border:1px solid {C['border']};"
            f"color:{C['accent']};border-radius:7px;padding:3px 10px;font-size:12px;font-weight:bold;")
        self.import_btn.clicked.connect(self._import_image)
        header.addWidget(self.import_btn)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setMinimumHeight(28)
        self.clear_btn.setStyleSheet(
            f"background:#FFF5F5;border:1px solid #F4A6A6;"
            f"color:{C['danger']};border-radius:7px;padding:3px 10px;font-size:12px;font-weight:bold;")
        self.clear_btn.clicked.connect(self._clear_display)
        header.addWidget(self.clear_btn)
        header.addStretch()
        layout.addLayout(header)

        info = QLabel(
            f"{self.DISPLAY_WIDTH}x{self.DISPLAY_HEIGHT} pixels at "
            f"0x{self.DISPLAY_BASE:04X}-0x{self.DISPLAY_BASE + self.DISPLAY_BYTES - 1:04X}    "
            "1 bit/pixel    ·    "
            f"click the canvas, then use ← ↑ ↓ → / WASD "
            f"(keys → 0x{self.KEY_REGISTER:04X})"
        )
        info.setStyleSheet(f"color:{C['dim']};font-size:11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.raster = DisplayRasterWidget(self.DISPLAY_WIDTH, self.DISPLAY_HEIGHT)
        self.raster.set_pixel_colors(self._pixel_colors)
        self.raster.set_grid_visible(False)
        self.raster.pixel_toggled.connect(self._on_pixel_toggled)
        self.raster.key_bits_changed.connect(self.key_register_changed)
        layout.addWidget(self.raster, 1)

    def _toggle_grid(self, checked):
        self.grid_btn.setText("Grid ON" if checked else "Grid OFF")
        self.raster.set_grid_visible(checked)

    def _configure_colors(self):
        dlg = DisplayColorDialog(self._pixel_colors, self)
        if dlg.exec_() == QDialog.Accepted:
            self._pixel_colors = dlg.colors()
            self.raster.set_pixel_colors(self._pixel_colors)

    def _import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Display Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All files (*)"
        )
        if not path:
            return

        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Import Image", "Could not read the selected image.")
            return

        dlg = DisplayImportDialog(
            image.size(),
            self.DISPLAY_BASE,
            self.DISPLAY_BASE,
            self.DISPLAY_WIDTH,
            self.DISPLAY_HEIGHT,
            self.DISPLAY_BYTES,
            self,
        )
        if dlg.exec_() != QDialog.Accepted:
            return

        width = dlg.output_width()
        height = dlg.output_height()
        start = dlg.start_addr()
        mode = dlg.storage_mode()
        if mode == "framebuffer":
            glyph_pixels = self._image_to_pixels(image, width, height, bottom_origin=True)
            pixels, data = self._draw_pixels_into_framebuffer(glyph_pixels, width, height, start)
            start = self.DISPLAY_BASE
        else:
            glyph_pixels = self._image_to_pixels(image, width, height, bottom_origin=False)
            data = bytes([width & 0xFF, height & 0xFF]) + self._pack_glyph_pixels(glyph_pixels, width, height)
        end = start + len(data)
        self._mem[start:end] = data
        if mode == "framebuffer":
            self._display_bytes = bytes(data)
            self.raster.set_pixels(pixels)
        elif self._overlaps_display(start, end):
            self.update_mem(self._mem)
        self.memory_region_written.emit(start, data)

    def _clear_display(self):
        start = self.DISPLAY_BASE
        end = start + self.DISPLAY_BYTES
        data = bytes(self.DISPLAY_BYTES)
        self._mem[start:end] = data
        self._display_bytes = data
        self.raster.set_pixels(bytearray(self.DISPLAY_SIZE))
        self.memory_region_written.emit(start, data)

    def update_mem(self, mem):
        start = self.DISPLAY_BASE
        end = start + self.DISPLAY_BYTES
        display_bytes = bytes(mem[start:end])
        self._mem[start:end] = display_bytes
        if display_bytes == self._display_bytes:
            return
        self._display_bytes = display_bytes
        self.raster.set_pixels(self._unpack_pixels(display_bytes))

    def _on_pixel_toggled(self, index, val):
        byte_index = index // 8
        pixel_slot = index % 8
        addr = self.DISPLAY_BASE + byte_index
        if 0 <= addr < len(self._mem):
            shift = 7 - pixel_slot
            cur = self._mem[addr]
            new_val = (cur & ~(0x01 << shift)) | ((val & 0x01) << shift)
            self._mem[addr] = new_val
            start = self.DISPLAY_BASE
            end = start + self.DISPLAY_BYTES
            self._display_bytes = bytes(self._mem[start:end])
            self.memory_written.emit(addr, new_val)

    def _unpack_pixels(self, packed):
        pixels = bytearray()
        for byte in packed:
            for shift in range(7, -1, -1):
                pixels.append((byte >> shift) & 0x01)
        return pixels[:self.DISPLAY_SIZE]

    def _pack_pixels(self, pixels):
        data = bytearray(math.ceil(len(pixels) / 8))
        for idx, val in enumerate(pixels):
            byte_index = idx // 8
            pixel_slot = idx % 8
            shift = 7 - pixel_slot
            data[byte_index] |= (val & 0x01) << shift
        return bytes(data)

    def _pack_glyph_pixels(self, pixels, width, height):
        row_bytes = math.ceil(width / 8)
        data = bytearray(row_bytes * height)
        for y in range(height):
            row_start = y * width
            for x in range(width):
                byte_index = y * row_bytes + x // 8
                shift = 7 - (x % 8)
                data[byte_index] |= (pixels[row_start + x] & 0x01) << shift
        return bytes(data)

    def _image_to_pixels(self, image, width, height, bottom_origin):
        scaled = image.convertToFormat(QImage.Format_ARGB32).scaled(
            width,
            height,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation
        )
        palette = [QColor(c) for c in self._pixel_colors]
        pixels = bytearray(width * height)
        for src_y in range(height):
            display_y = height - 1 - src_y if bottom_origin else src_y
            for x in range(width):
                source = QColor(scaled.pixel(x, src_y))
                pixels[display_y * width + x] = self._nearest_palette_index(source, palette)
        return pixels

    def _image_to_packed_pixels(self, image, width, height):
        pixels = self._image_to_pixels(image, width, height, bottom_origin=True)
        return pixels, self._pack_pixels(pixels)

    def _draw_pixels_into_framebuffer(self, glyph_pixels, glyph_width, glyph_height, dest_addr):
        framebuffer = self._unpack_pixels(self._display_bytes)
        pixel_start = (dest_addr - self.DISPLAY_BASE) * 8
        x0 = pixel_start % self.DISPLAY_WIDTH
        y0 = pixel_start // self.DISPLAY_WIDTH
        for y in range(glyph_height):
            for x in range(glyph_width):
                dest_x = x0 + x
                dest_y = y0 + y
                if 0 <= dest_x < self.DISPLAY_WIDTH and 0 <= dest_y < self.DISPLAY_HEIGHT:
                    framebuffer[dest_y * self.DISPLAY_WIDTH + dest_x] = glyph_pixels[y * glyph_width + x]
        return framebuffer, self._pack_pixels(framebuffer)

    def _overlaps_display(self, start, end):
        display_start = self.DISPLAY_BASE
        display_end = display_start + self.DISPLAY_BYTES
        return start < display_end and end > display_start

    def _nearest_palette_index(self, color, palette):
        r, g, b = color.red(), color.green(), color.blue()
        best_idx = 0
        best_dist = None
        for idx, candidate in enumerate(palette):
            dr = r - candidate.red()
            dg = g - candidate.green()
            db = b - candidate.blue()
            dist = dr * dr + dg * dg + db * db
            if best_dist is None or dist < best_dist:
                best_idx = idx
                best_dist = dist
        return best_idx
