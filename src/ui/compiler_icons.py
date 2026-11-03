# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Scalable, colourful action icons for the TARA compiler workspace.

``compiler_icon(name, size=36)`` returns a transparent QIcon with explicit
normal and disabled artwork. Shapes use a shared 48-unit drawing grid and are
rendered at 3x resolution for sharp edges on Retina displays. No platform emoji
fonts, external images, or additional packages are required. Construct icons
only after the application's QApplication has been created.

Available names: new, open, save, save_as, compile, export, assembly, c_file,
and terminal. Unknown names raise ValueError to expose misspelled action names.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


_ICON_NAMES = frozenset({
    "new", "open", "save", "save_as", "compile", "export", "assembly",
    "c_file", "terminal",
})


def _line(painter, points, color, width=3.0):
    """Draw an open stroke with the same soft joins throughout the icon set."""
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    painter.drawPath(path)


def _shape(painter, points, fill):
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(fill))
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    path.closeSubpath()
    painter.drawPath(path)


def _rounded(painter, x, y, width, height, radius, fill):
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(QRectF(x, y, width, height), radius, radius)


def _document(painter):
    _shape(painter, [(10, 4), (29, 4), (38, 13), (38, 42), (10, 42)], "#173D7A")
    _shape(painter, [(13, 7), (27, 7), (27, 16), (35, 16), (35, 39), (13, 39)], "#EAF7FF")
    _shape(painter, [(29, 7), (35, 13), (29, 13)], "#55B8EF")


def _save(painter):
    _shape(painter, [(7, 5), (34, 5), (41, 12), (41, 42), (7, 42)], "#1460BC")
    _rounded(painter, 12, 5, 20, 13, 1.5, "#B8E8FF")
    _rounded(painter, 26, 7, 4, 8, 1, "#173D7A")
    _rounded(painter, 13, 24, 22, 18, 2, "#EEF8FF")
    _line(painter, [(18, 29), (30, 29)], "#72ACDC", 2)
    _line(painter, [(18, 34), (28, 34)], "#72ACDC", 2)


def _draw(painter, name):
    if name in ("new", "c_file"):
        _document(painter)
        if name == "new":
            _line(painter, [(17, 22), (28, 22)], "#69A5D9", 2.4)
            _line(painter, [(17, 28), (25, 28)], "#69A5D9", 2.4)
            _rounded(painter, 26, 26, 19, 19, 6, "#098D77")
            _line(painter, [(35.5, 30.5), (35.5, 40.5)], "#FFFFFF", 2.7)
            _line(painter, [(30.5, 35.5), (40.5, 35.5)], "#FFFFFF", 2.7)
        else:
            _line(painter, [(28, 23), (25, 20), (20, 20), (17, 24),
                            (17, 30), (20, 34), (25, 34), (28, 31)], "#1460BC", 3)

    elif name == "open":
        _shape(painter, [(5, 11), (19, 11), (23, 16), (42, 16),
                         (42, 39), (5, 39)], "#D98A0B")
        _rounded(painter, 9, 18, 28, 17, 2, "#FFF2C2")
        gradient = QLinearGradient(0, 19, 0, 39)
        gradient.setColorAt(0, QColor("#FFCE59"))
        gradient.setColorAt(1, QColor("#F5A623"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        path = QPainterPath(QPointF(10, 22))
        path.lineTo(44, 22)
        path.lineTo(38, 40)
        path.lineTo(4, 40)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, [(13, 26), (37, 26)], "#FFE59A", 2)

    elif name in ("save", "save_as"):
        _save(painter)
        if name == "save_as":
            # The diagonal pencil remains legible even at the 28 px toolbar size.
            _shape(painter, [(24, 36), (38, 22), (44, 28), (30, 42)], "#FFBF3F")
            _shape(painter, [(24, 36), (30, 42), (21, 45)], "#153961")
            _shape(painter, [(38, 22), (41, 19), (47, 25), (44, 28)], "#F36D64")
            _line(painter, [(29, 36), (40, 25)], "#FFF0B2", 1.8)

    elif name == "compile":
        for offset in (14, 24, 34):
            _line(painter, [(offset, 3), (offset, 9)], "#159B80", 3)
            _line(painter, [(offset, 39), (offset, 45)], "#159B80", 3)
            _line(painter, [(3, offset), (9, offset)], "#159B80", 3)
            _line(painter, [(39, offset), (45, offset)], "#159B80", 3)
        _rounded(painter, 7, 7, 34, 34, 8, "#103451")
        _rounded(painter, 11, 11, 26, 26, 5, "#164F5C")
        _shape(painter, [(26, 11), (15, 26), (23, 26), (20, 38),
                         (34, 21), (26, 21), (30, 11)], "#B7FF45")

    elif name == "export":
        _rounded(painter, 5, 29, 38, 14, 5, "#087F91")
        _rounded(painter, 10, 27, 28, 10, 3, "#DAF8FB")
        _shape(painter, [(20, 5), (28, 5), (28, 22), (36, 22),
                         (24, 34), (12, 22), (20, 22)], "#18B5C4")
        _line(painter, [(24, 9), (24, 23)], "#C7FCFC", 2)

    elif name == "assembly":
        _rounded(painter, 3, 7, 36, 31, 7, "#ECE7FF")
        _line(painter, [(14, 15), (8, 22), (14, 29)], "#6E49BE", 3.5)
        _line(painter, [(28, 15), (34, 22), (28, 29)], "#6E49BE", 3.5)
        _line(painter, [(23, 14), (19, 30)], "#9675D8", 3)
        _rounded(painter, 24, 29, 22, 14, 5, "#0A9DB7")
        _line(painter, [(28, 36), (41, 36)], "#FFFFFF", 2.6)
        _line(painter, [(36, 32), (41, 36), (36, 40)], "#FFFFFF", 2.6)

    elif name == "terminal":
        _rounded(painter, 4, 8, 40, 32, 6, "#173D7A")
        _rounded(painter, 7, 11, 34, 26, 4, "#102840")
        _line(painter, [(13, 18), (19, 24), (13, 30)], "#B7FF45", 3)
        _line(painter, [(24, 30), (34, 30)], "#67DCE8", 3)


def compiler_icon(name: str, size: int = 36) -> QIcon:
    """Return a 3x-resolution compiler action icon at ``size`` logical pixels.

    A muted, translucent copy is explicitly registered for disabled buttons so
    Qt does not replace the artwork with inconsistent platform-specific effects.
    The returned QIcon can be shared freely between widgets.
    """
    if name not in _ICON_NAMES:
        raise ValueError(f"Unknown compiler icon: {name!r}")
    if not isinstance(size, int) or size < 1:
        raise ValueError("Icon size must be a positive integer")
    icon = QIcon()
    for mode in (QIcon.Normal, QIcon.Disabled):
        pixmap = QPixmap(size * 3, size * 3)
        pixmap.setDevicePixelRatio(3.0)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(size / 48.0, size / 48.0)
        if mode == QIcon.Disabled:
            painter.setOpacity(0.36)
        _draw(painter, name)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon
