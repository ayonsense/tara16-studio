# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — Shared constants and helper functions used by several panels (icon paths, example-program tables, colour-map loaders, the heat-map data roles and the small font-button styler)."""

import os

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import (
    QColor, QFont, QPainter, QIcon, QPen, QPixmap,
)

from src.examples.examples import load_example_groups
from src.paths import APP_DIR
from src.ui.theme import C


EXAMPLE_PROGRAM_GROUPS = load_example_groups()
EXAMPLE_PROGRAMS = {
    name: source
    for programs in EXAMPLE_PROGRAM_GROUPS.values()
    for name, source in programs.items()
}
NEW_PROGRAM_LABEL = "New File..."
PROGRAM_KIND_ROLE = Qt.UserRole
PROGRAM_NAME_ROLE = Qt.UserRole + 1
PROGRAM_KIND_ACTION = "action"
PROGRAM_KIND_EXAMPLE = "example"
PROGRAM_KIND_HEADER = "header"
EDITOR_TOOL_BUTTON_SIZE = QSize(56, 50)
EDITOR_TOOL_ICON_SIZE = QSize(28, 28)
DELETE_ICON_PATH = os.path.join(APP_DIR, "assets", "delete.jpeg")
RENAME_ICON_PATH = os.path.join(APP_DIR, "assets", "rename.png")
EDITOR_FONT_ICON_PATH = os.path.join(APP_DIR, "assets", "editor_font.png")
DISPLAY_PIXEL_COLORS = ['#1C1C1C', '#FFB000']  # Classic Amber: off/on
DEFAULT_MEMORY_CMAP = 'TARA'


def _power_icon(color="#FFFFFF"):
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), 4)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(24, 6, 24, 21)
    painter.drawArc(8, 9, 32, 32, 140 * 16, 260 * 16)
    painter.end()

    return QIcon(pixmap)

def _load_matplotlib_cmap_getter():
    try:
        import matplotlib
        from matplotlib.colors import LinearSegmentedColormap

        tara_cmap = LinearSegmentedColormap.from_list(
            DEFAULT_MEMORY_CMAP,
            [(0.0, C['bg']), (0.35, C['border']),
             (0.65, C['coffee']), (1.0, C['accent'])],
            N=256,
        )
        if hasattr(matplotlib, 'colormaps'):
            getter = lambda name: matplotlib.colormaps[name]
        else:
            from matplotlib import cm
            getter = cm.get_cmap

        def get_cmap(name):
            if name.casefold() == DEFAULT_MEMORY_CMAP.casefold():
                return tara_cmap
            try:
                return getter(name)
            except (KeyError, ValueError):
                # Older Matplotlib releases publish this same white-to-black
                # map under its earlier name only.
                if name == 'gist_yerg':
                    return getter('gist_yarg')
                raise

        return get_cmap
    except Exception:
        return None


MPL_GET_CMAP = _load_matplotlib_cmap_getter()


def _load_matplotlib_cmap_names():
    try:
        import matplotlib
        if hasattr(matplotlib, 'colormaps'):
            return [DEFAULT_MEMORY_CMAP] + sorted(matplotlib.colormaps)
        import matplotlib.cm as cm
        return [DEFAULT_MEMORY_CMAP] + sorted(cm.cmap_d)
    except Exception:
        return []


MPL_CMAP_NAMES = _load_matplotlib_cmap_names()

HEATMAP_BG_ROLE = Qt.UserRole + 1
HEATMAP_FG_ROLE = Qt.UserRole + 2


def _style_editor_icon_button(button):
    """Use the same file-action styling in the C and Assembly toolbars."""
    button.setFixedSize(EDITOR_TOOL_BUTTON_SIZE)
    button.setIconSize(EDITOR_TOOL_ICON_SIZE)
    font = QFont()
    font.setPixelSize(17)
    font.setBold(True)
    button.setFont(font)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(f"""
        QPushButton {{ background:{C['panel']}; border:1px solid {C['border']};
            color:{C['accent']}; border-radius:8px; padding:6px 8px; font-size:17px; font-weight:700; }}
        QPushButton:hover {{ background:{C['panel2']}; border-color:{C['accent2']}; }}
        QPushButton:pressed {{ background:#EBD9C4; padding-top:8px; padding-bottom:4px; }}
        QPushButton:disabled {{ color:{C['dim']}; border-color:{C['border']}; background:{C['bg']}; }}
        QToolTip {{ background:{C['panel']}; color:{C['text']}; border:1px solid {C['border']};
            padding:6px 8px; font-size:12px; }}
    """)


def _style_program_combo(combo):
    """Share the warm program-selector surface across both code editors."""
    combo.setMinimumHeight(50)
    combo.setStyleSheet(f"""
        QComboBox {{ background:{C['panel2']}; border:1px solid {C['border']};
            color:{C['accent']}; border-radius:8px; padding:6px 12px;
            font-size:17px; font-weight:700; }}
        QComboBox:hover {{ background:#F0E3D5; border-color:{C['accent2']}; }}
        QComboBox:focus {{ border-color:{C['accent']}; }}
        QComboBox::drop-down {{ border:none; width:26px; }}
        QComboBox QAbstractItemView {{ background:{C['panel']}; color:{C['text']};
            border:1px solid {C['border']}; selection-background-color:{C['accent']};
            selection-color:white; font-size:15px; outline:none; }}
    """)


def _apply_font_button_style(button):
    """Shared style for A-/A+ font-size buttons used in listing and memory panels."""
    button.setFixedSize(34, 26)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton {{ background:#FFFFFF;border:1px solid {C['border']};"
        f"color:{C['title']};border-radius:6px;padding:1px;font-weight:800; }}"
        f"QPushButton:hover {{ border-color:{C['accent']}; background:{C['panel2']}; }}"
        "QPushButton:pressed { background:#EBD9C4; padding-top:3px; }"
    )




# ─── Syntax highlighter ────────────────────────────────────────────────────────

# ─── Register panel ────────────────────────────────────────────────────────────
REG_NAMES = ['R0','R1','R2','R3','R4','R5','R6','R7']
REG_ACCENTS = [C['accent']] * len(REG_NAMES)



# ─── Listing / machine code panel ─────────────────────────────────────────────


# ─── Inline cell editor overlay ───────────────────────────────────────────────


# ─── Memory Tools dialog (Random Fill + CSV Import + CSV Export) ───────────────


# ─── Memory panel ──────────────────────────────────────────────────────────────


# ─── Memory-mapped display panel ──────────────────────────────────────────────








# ─── Clock / control panel ─────────────────────────────────────────────────────


# ─── Editor panel ──────────────────────────────────────────────────────────────






# ─── History/log panel ─────────────────────────────────────────────────────────
