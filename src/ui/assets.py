# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Shared TARA branding and rounded app-icon rendering."""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import QLabel, QSizePolicy

from src.paths import APP_ICON_PATH, BRAND_TEXT_LOGO_PATH
from src.ui.theme import C

def _add_brand_logo_pair(layout, icon_height=42, text_height=34):
    """Render the original icon and wordmark sharply on high-DPI displays."""
    for path, height, name in (
        (APP_ICON_PATH, icon_height, "TARA icon"),
        (BRAND_TEXT_LOGO_PATH, text_height, "TARA wordmark"),
    ):
        label = QLabel()
        label.setAccessibleName(name)
        label.setAlignment(Qt.AlignCenter)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        pixmap = QPixmap(path) if os.path.exists(path) else QPixmap()
        if not pixmap.isNull():
            ratio = label.devicePixelRatioF()
            pixmap = pixmap.scaledToHeight(round(height * ratio), Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            label.setPixmap(pixmap)
            label.setFixedSize(round(pixmap.width() / ratio), icon_height + 2)
        layout.addWidget(label, 0, Qt.AlignVCenter)

def _rounded_app_icon(path, size=256):
    pix = QPixmap(path)
    if pix.isNull():
        return QIcon()

    source = pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (source.width() - size) // 2)
    y = max(0, (source.height() - size) // 2)
    source = source.copy(x, y, size, size)

    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)
    path_clip = QPainterPath()
    path_clip.addRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)
    painter.setClipPath(path_clip)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return QIcon(rounded)

def _panel_title(text):
    label = QLabel(text)
    label.setStyleSheet(f"color:{C['title']};font-size:15px;font-weight:800;")
    return label
