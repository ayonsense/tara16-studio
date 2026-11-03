# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Centralised look-and-feel for the whole UI.

Defines the colour palette (C), the monospace fonts, the global Qt stylesheet,
and the load/save of persisted UI settings (font sizes, window prefs) to disk so
choices survive between sessions."""

import json
import os

from PyQt5.QtGui import QFont

from src.paths import UI_SETTINGS_PATH


DEFAULT_UI_SETTINGS = {
    "base_font_size": 14,
    "editor_font_size": 15,
    "listing_font_size": 15,
    "memory_font_size": 15,
    "isa_font_size": 16,
    "history_log_font_size": 14,
    "register_font_size": 20,
}


def _clamp_int(value, minimum, maximum, fallback):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = fallback
    return max(minimum, min(maximum, value))


def load_ui_settings():
    settings = dict(DEFAULT_UI_SETTINGS)
    try:
        with open(UI_SETTINGS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            settings.update(raw)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    settings["base_font_size"] = _clamp_int(settings.get("base_font_size"), 10, 22, DEFAULT_UI_SETTINGS["base_font_size"])
    settings["editor_font_size"] = _clamp_int(settings.get("editor_font_size"), 10, 28, DEFAULT_UI_SETTINGS["editor_font_size"])
    settings["listing_font_size"] = _clamp_int(settings.get("listing_font_size"), 9, 40, DEFAULT_UI_SETTINGS["listing_font_size"])
    settings["memory_font_size"] = _clamp_int(settings.get("memory_font_size"), 9, 24, DEFAULT_UI_SETTINGS["memory_font_size"])
    settings["isa_font_size"] = _clamp_int(settings.get("isa_font_size"), 11, 30, DEFAULT_UI_SETTINGS["isa_font_size"])
    settings["history_log_font_size"] = _clamp_int(settings.get("history_log_font_size"), 9, 30, DEFAULT_UI_SETTINGS["history_log_font_size"])
    settings["register_font_size"] = _clamp_int(settings.get("register_font_size"), 11, 32, DEFAULT_UI_SETTINGS["register_font_size"])
    return settings


def save_ui_setting(key, value):
    settings = load_ui_settings()
    if key not in DEFAULT_UI_SETTINGS:
        return settings
    settings[key] = _clamp_int(value, 8, 32, DEFAULT_UI_SETTINGS[key])
    os.makedirs(os.path.dirname(UI_SETTINGS_PATH), exist_ok=True)
    with open(UI_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    UI_SETTINGS.update(settings)
    return settings


UI_SETTINGS = load_ui_settings()

# One palette for the application shell, editors, and FPGA workspace.
C = {
    'bg':           '#F7F4EF',
    'panel':        '#FFFFFF',
    'panel2':       '#F4EBE2',
    'border':       '#E4D7CB',
    'accent':       '#7A1E2B',
    'accent2':      '#A6792E',
    'coffee':       '#B28A73',
    'accent_hover': '#641624',
    'accent_press': '#4E1019',
    'hover':        '#F0E2D4',
    'selected':     '#EBD9C4',
    'warning':      '#926626',
    'danger':       '#B23C3C',
    'title':        '#7A1E2B',
    'text':         '#2B2320',
    'dim':          '#76685E',
    'highlight':    '#7A1E2B',
    'row_alt':      '#FAF7F3',
    'pc_row':       '#EBD9C4',
    'changed':      '#F6E8C8',
    'gold_soft':    '#F6E8C8',
    # Compatibility names for existing panels; all use warm neutral surfaces.
    'teal_soft':    '#F3EEE6',
    'navy_soft':    '#F4E8E4',
    'editor_gutter':'#FAF7F3',
}

GLOBAL_STYLE = f"""
QMainWindow, QWidget {{
    background-color: {C['bg']};
    color: {C['text']};
    font-family: 'Helvetica Neue', 'Segoe UI', sans-serif;
    font-size: {UI_SETTINGS['base_font_size']}px;
}}
QGroupBox {{
    border: 1px solid {C['border']};
    border-radius: 10px;
    margin-top: 0px;
    padding: 8px;
    font-weight: 600;
    color: {C['accent']};
    background: {C['panel']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QLabel, QCheckBox {{
    background-color: transparent;
}}
QPushButton {{
    background-color: {C['panel2']};
    border: 1px solid {C['border']};
    border-radius: 7px;
    padding: 6px 14px;
    color: {C['text']};
    font-size: {UI_SETTINGS['base_font_size']}px;
}}
QPushButton:hover {{
    border-color: {C['accent']};
    color: {C['accent']};
    background-color: {C['hover']};
}}
QPushButton:pressed {{
    background-color: {C['highlight']};
    color: white;
}}
QPushButton:disabled {{
    color: {C['dim']};
    border-color: {C['border']};
}}
QPushButton#btn_assemble,
QPushButton#btn_step,
QPushButton#btn_run,
QPushButton#btn_reset,
QPushButton#btn_save_state,
QPushButton#btn_boot_state {{
    background-color: #FFFFFF;
    border: 1px solid {C['border']};
    color: {C['accent']};
    font-weight: 800;
    font-size: 18px;
    border-radius: 8px;
    padding: 6px 10px 8px 10px;
}}
QPushButton#btn_assemble:hover,
QPushButton#btn_step:hover,
QPushButton#btn_run:hover,
QPushButton#btn_reset:hover,
QPushButton#btn_save_state:hover,
QPushButton#btn_boot_state:hover {{
    background-color: {C['hover']};
    border-color: {C['accent2']};
    color: {C['accent']};
}}
QPushButton#btn_assemble:pressed,
QPushButton#btn_step:pressed,
QPushButton#btn_run:pressed,
QPushButton#btn_reset:pressed,
QPushButton#btn_save_state:pressed,
QPushButton#btn_boot_state:pressed {{
    background-color: {C['selected']};
    padding-top: 8px;
    padding-bottom: 6px;
}}
QPushButton#btn_run[running="true"] {{
    background-color: #FFFFFF;
    border-color: #F1A8A8;
    color: #B51F1F;
    font-weight: 800;
}}
QPushButton#btn_run[running="true"]:hover {{
    background-color: #FFF1F1;
    border-color: #E57D7D;
    color: #B51F1F;
}}
QPlainTextEdit, QTextEdit {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    color: {C['text']};
    selection-background-color: {C['highlight']};
    selection-color: white;
}}
QTableWidget {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    gridline-color: {C['border']};
    color: {C['text']};
    selection-background-color: {C['highlight']};
    selection-color: white;
    outline: none;
}}
QTableWidget::item {{
    padding: 2px 6px;
    border: none;
}}
QHeaderView::section {{
    background-color: {C['panel2']};
    color: {C['dim']};
    border: none;
    border-right: 1px solid {C['border']};
    border-bottom: 1px solid {C['border']};
    padding: 4px 6px;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QScrollBar:vertical {{
    background: {C['panel2']};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: #C7B6A7;
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C['panel2']};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: #C7B6A7;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: 6px;
    background-color: {C['panel']};
}}
QTabBar::tab {{
    background: {C['panel2']};
    color: {C['accent']};
    border: 1px solid {C['border']};
    border-bottom: 2px solid {C['border']};
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    padding: 7px 14px;
    margin-right: 3px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {C['accent']};
    border-color: {C['border']};
    border-bottom-color: {C['accent']};
    background: {C['panel']};
    font-weight: 700;
}}
QTabBar::tab:hover:!selected {{
    background: {C['hover']};
}}
QLabel#lbl_pc {{
    color: {C['accent']};
    font-family: 'Menlo', 'Fira Code', 'Consolas', monospace;
    font-size: 18px;
    font-weight: bold;
}}
QLabel#lbl_cycles {{
    color: {C['dim']};
    font-size: 12px;
}}
QSpinBox, QComboBox {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    color: {C['text']};
    padding: 3px 8px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    color: {C['text']};
    selection-background-color: {C['highlight']};
    selection-color: white;
}}
QSlider::groove:horizontal {{
    height: 8px;
    background: {C['panel2']};
    border: 1px solid {C['border']};
    border-radius: 4px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C['accent2']}, stop:1 {C['accent']});
    border-radius: 4px;
}}
QSlider::add-page:horizontal {{
    background: #FFFFFF;
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    width: 20px;
    height: 20px;
    margin: -7px 0;
    border-radius: 10px;
    background: #FFFFFF;
    border: 2px solid {C['accent']};
}}
QSlider::handle:horizontal:hover {{
    border-color: {C['accent2']};
}}
QLineEdit {{
    background-color: {C['panel']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    color: {C['text']};
    padding: 3px 8px;
}}
QStatusBar {{
    background-color: {C['panel']};
    color: {C['dim']};
    border-top: 1px solid {C['border']};
    font-size: 12px;
}}
QToolTip {{
    background: {C['panel']}; color: {C['text']};
    border: 1px solid {C['border']}; padding: 6px 8px;
    font-size: 12px;
}}
QMenuBar, QMenu {{
    background: {C['panel']}; color: {C['text']};
    border: 1px solid {C['border']};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background: {C['panel2']}; color: {C['accent']};
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border-color: {C['accent2']};
}}
QSplitter::handle {{
    background-color: transparent;
    border: none;
    width: 6px;
    height: 6px;
}}
"""

MONO = QFont('Menlo', 11)
MONO.setStyleHint(QFont.Monospace)
MONO_SM = QFont('Menlo', 10)
MONO_SM.setStyleHint(QFont.Monospace)
