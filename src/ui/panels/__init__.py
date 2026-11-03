# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI panels.

This package was split out of the former single-file panels.py. Each panel
now lives in a small domain module; importing from src.ui.panels keeps
working exactly as before via the re-exports below.
"""

from src.ui.panels.registers import RegisterPanel
from src.ui.panels.listing import ListingPanel
from src.ui.panels.memory import HeatmapCellDelegate, CellEditor, MemoryPanel
from src.ui.panels.mem_tools import MemToolsDialog
from src.ui.panels.display import DisplayRasterWidget, DisplayColorDialog, DisplayImportDialog, DisplayPanel
from src.ui.panels.control import ControlPanel
from src.ui.panels.editor import AsmHighlighter, LineNumberArea, CodeEditor, EditorPanel
from src.ui.panels.history import HistoryPanel

__all__ = [
    "AsmHighlighter",
    "CellEditor",
    "CodeEditor",
    "ControlPanel",
    "DisplayColorDialog",
    "DisplayImportDialog",
    "DisplayPanel",
    "DisplayRasterWidget",
    "EditorPanel",
    "HeatmapCellDelegate",
    "HistoryPanel",
    "LineNumberArea",
    "ListingPanel",
    "MemToolsDialog",
    "MemoryPanel",
    "RegisterPanel",
]
