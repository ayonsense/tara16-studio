# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — The assembly editor: the code widget, its line-number gutter, the syntax highlighter and the surrounding editor panel + toolbar.

Classes:
  AsmHighlighter -- QSyntaxHighlighter for TARA assembly: colours mnemonics, registers, numbers, labels and comments in the code editor.
  LineNumberArea -- Thin gutter widget that paints line numbers alongside the code editor.
  CodeEditor -- QPlainTextEdit subclass for the assembly editor: line numbers, current-line highlight, auto-indent and completion.
  EditorPanel -- The left pane: the assembly editor, its toolbar (program dropdown, open/save/delete/rename, ISA, power) and the assembler-error area.
"""

import os, re
from pathlib import Path

from PyQt5.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, pyqtSignal, QSize, QRect,
)
from PyQt5.QtGui import (
    QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QIcon, QFontMetrics, QTextOption,
)
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGroupBox, QHBoxLayout, QInputDialog, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QGraphicsOpacityEffect, QStyle, QTextEdit, QVBoxLayout, QWidget,
)

from src.examples.examples import EXAMPLE_CATEGORIES
from src.paths import PROGS_DIR
from src.usage.examples import bundled_example, validate_example
from src.simulation.cpu import OP_NAME
from src.ui.isa_dialog import ISADialog
from src.ui.theme import C, MONO_SM, UI_SETTINGS, save_ui_setting

from src.ui.panels.common import DELETE_ICON_PATH, EDITOR_TOOL_BUTTON_SIZE, EDITOR_TOOL_ICON_SIZE, EXAMPLE_PROGRAMS, EXAMPLE_PROGRAM_GROUPS, NEW_PROGRAM_LABEL, PROGRAM_KIND_ACTION, PROGRAM_KIND_EXAMPLE, PROGRAM_KIND_HEADER, PROGRAM_KIND_ROLE, PROGRAM_NAME_ROLE, RENAME_ICON_PATH, _power_icon, _style_editor_icon_button, _style_program_combo


class AsmHighlighter(QSyntaxHighlighter):
    """QSyntaxHighlighter for TARA assembly: colours mnemonics, registers, numbers, labels and comments in the code editor."""
    def __init__(self, doc):
        super().__init__(doc)
        self.rules = []

        def add(pattern, color, bold=False, italic=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:   fmt.setFontWeight(700)
            if italic: fmt.setFontItalic(True)
            self.rules.append((re.compile(pattern, re.IGNORECASE), fmt))

        mnems = '|'.join(sorted(OP_NAME.values(), key=len, reverse=True))
        add(r'\b(?:' + mnems + r')\b', C['accent'], bold=True)
        add(r'\b[Rr][0-7]\b', '#855D32', bold=True)
        add(r'\b0x[0-9a-fA-F]+\b', '#356B58')
        add(r'\b\d+\b', '#356B58')
        add(r';.*$', C['dim'], italic=True)
        add(r'^\s*\w+\s*:', '#5E5276', bold=True)

    def highlightBlock(self, text):
        for pat, fmt in self.rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class LineNumberArea(QWidget):
    """Thin gutter widget that paints line numbers alongside the code editor."""
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.editor.toggle_breakpoint_at_y(event.pos().y())
            return
        super().mousePressEvent(event)


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit subclass for the assembly editor: line numbers, current-line highlight, auto-indent and completion."""
    breakpoints_changed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.breakpoints = set()
        self._execution_line = None
        self._font_size = UI_SETTINGS["editor_font_size"]
        self._floating_font_controls = None
        self.line_number_area = LineNumberArea(self)
        self._configure_editor_style()
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def _editor_font(self, size=None):
        font = QFont('Menlo')
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(size or self._font_size)
        return font

    def _configure_editor_style(self):
        font = self._editor_font()
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(' ') * 4)

        option = self.document().defaultTextOption()
        option.setFlags(option.flags() | QTextOption.ShowTabsAndSpaces)
        self.document().setDefaultTextOption(option)
        self.document().setDocumentMargin(8)
        self._apply_editor_stylesheet()

    def _apply_editor_stylesheet(self):
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background: #FFFFFF;
                border: 1px solid {C['border']};
                border-radius: 4px;
                color: {C['text']};
                font-family: 'Menlo', 'Fira Code', 'Consolas', monospace;
                font-size: {self._font_size}px;
                selection-background-color: #EBD9C4;
                selection-color: {C['text']};
            }}
        """)

    def set_floating_font_controls(self, widget):
        self._floating_font_controls = widget
        self._position_floating_controls()

    def set_floating_font_button(self, button):
        self.set_floating_font_controls(button)

    def _apply_font_size(self):
        font = self._editor_font()
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(' ') * 4)
        self._apply_editor_stylesheet()
        self.update_line_number_area_width(0)
        self.line_number_area.update()
        self._position_floating_controls()
        self.viewport().update()

    def set_font_size(self, size):
        self._font_size = max(10, min(28, int(size)))
        save_ui_setting("editor_font_size", self._font_size)
        self._apply_font_size()

    def adjust_font_size(self, delta):
        self.set_font_size(self._font_size + delta)

    def increase_font_size(self):
        self.adjust_font_size(1)

    def decrease_font_size(self):
        self.adjust_font_size(-1)

    def font_size(self):
        return self._font_size

    def _position_floating_controls(self):
        if self._floating_font_controls is None:
            return
        margin = 8
        size = self._floating_font_controls.sizeHint()
        width = max(76, size.width())
        height = max(32, size.height())
        viewport_rect = self.viewport().geometry()
        self._floating_font_controls.setGeometry(
            max(viewport_rect.left() + margin, viewport_rect.right() - width - margin + 1),
            viewport_rect.top() + margin,
            width,
            height,
        )
        self._floating_font_controls.raise_()

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance('9') * max(2, digits)

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        self._position_floating_controls()
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
        self._position_floating_controls()

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor('#FFFFFF'))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(C['border']))
        painter.drawLine(self.line_number_area.width() - 1, event.rect().top(),
                         self.line_number_area.width() - 1, event.rect().bottom())

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        gutter_font_size = max(9, self._font_size - 1)
        painter.setFont(self._editor_font(gutter_font_size))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                is_current = block_number == self.textCursor().blockNumber()
                is_execution = self._execution_line == block_number + 1
                has_breakpoint = (block_number + 1) in self.breakpoints
                if is_execution:
                    painter.fillRect(0, top, self.line_number_area.width(), self.fontMetrics().height(), QColor('#FFE8B8'))
                elif is_current:
                    painter.fillRect(0, top, self.line_number_area.width(), self.fontMetrics().height(), QColor('#FBF5ED'))
                if has_breakpoint:
                    h = self.fontMetrics().height()
                    badge_size = min(max(16, self.line_number_area.width() - 4), h + 1)
                    badge_x = self.line_number_area.width() - badge_size - 2
                    badge_y = top + max(0, (h - badge_size) // 2)
                    painter.setBrush(QColor(C['accent']))
                    painter.setPen(QColor(C['accent']))
                    painter.drawEllipse(badge_x, badge_y, badge_size, badge_size)
                    painter.setPen(QColor('#FFFFFF'))
                    painter.setFont(QFont('Menlo', 8, weight=800))
                    painter.drawText(
                        badge_x, badge_y, badge_size, badge_size,
                        Qt.AlignCenter, number)
                    painter.setFont(self._editor_font(gutter_font_size))
                else:
                    painter.setPen(QColor(C['accent2'] if is_execution else C['accent'] if is_current else C['dim']))
                    painter.drawText(
                        0, top, self.line_number_area.width() - 3,
                        self.fontMetrics().height(), Qt.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def _line_at_y(self, y):
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= self.viewport().height():
            if block.isVisible() and top <= y <= bottom:
                return block_number + 1
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1
        return None

    def toggle_breakpoint_at_y(self, y):
        line = self._line_at_y(y)
        if line is None:
            return
        if line in self.breakpoints:
            self.breakpoints.remove(line)
        else:
            self.breakpoints.add(line)
        self.line_number_area.update()
        self.breakpoints_changed.emit(set(self.breakpoints))

    def clear_breakpoints(self):
        if not self.breakpoints:
            return
        self.breakpoints.clear()
        self.line_number_area.update()
        self.breakpoints_changed.emit(set())

    def get_breakpoints(self):
        return set(self.breakpoints)

    def set_execution_line(self, line):
        self._execution_line = line if isinstance(line, int) and line > 0 else None
        if self._execution_line is not None:
            self._scroll_line_into_view(self._execution_line)
        self.highlight_current_line()
        self.line_number_area.update()

    def _scroll_line_into_view(self, line):
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return
        rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
        margin = self.fontMetrics().height() * 2
        if margin <= rect.top() and rect.bottom() <= self.viewport().height() - margin:
            return
        scroll = self.verticalScrollBar()
        visible_lines = max(1, self.viewport().height() // max(1, self.fontMetrics().height()))
        scroll.setValue(max(scroll.minimum(), min(scroll.maximum(), line - 1 - visible_lines // 2)))

    def highlight_current_line(self):
        selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor('#FBF5ED'))
            selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        if self._execution_line is not None:
            block = self.document().findBlockByNumber(self._execution_line - 1)
            if block.isValid():
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(QColor('#FFE8B8'))
                selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
                selection.cursor = QTextCursor(block)
                selection.cursor.clearSelection()
                selections.append(selection)
        self.setExtraSelections(selections)


class EditorPanel(QGroupBox):
    """The left pane: the assembly editor, its toolbar (program dropdown, open/save/delete/rename, ISA, power) and the assembler-error area."""
    sig_breakpoints_changed = pyqtSignal(object)
    sig_power_off = pyqtSignal()
    sig_status = pyqtSignal(str)
    usage_event = pyqtSignal(str, object)

    def __init__(self):
        super().__init__("")
        self.current_file_path = None
        self.current_program_name = ""
        self._usage_example = None
        self._usage_example_revision = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self.example_combo = QComboBox()
        self.example_combo.setMinimumHeight(50)
        self.example_combo.setMinimumWidth(220)
        self.example_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.example_combo.setFont(QFont('Segoe UI', 18, weight=800))
        _style_program_combo(self.example_combo)
        self.example_combo.view().setMinimumWidth(340)
        self._rebuild_program_combo()
        self.example_combo.activated[int].connect(self._program_selected)
        toolbar.addWidget(self.example_combo)

        self.upload_btn = QPushButton()
        self.upload_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self._style_editor_icon_button(self.upload_btn)
        self.upload_btn.setToolTip("Load a .tara or .asm assembly file from disk")
        self.upload_btn.clicked.connect(self._open_file)
        self._install_press_feedback(self.upload_btn)
        toolbar.addWidget(self.upload_btn)

        self.save_program_btn = QPushButton()
        self.save_program_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self._style_editor_icon_button(self.save_program_btn)
        self.save_program_btn.setToolTip("Save the current editor contents")
        self.save_program_btn.clicked.connect(self._save_program)
        self._install_press_feedback(self.save_program_btn)
        toolbar.addWidget(self.save_program_btn)

        self.delete_program_btn = QPushButton()
        if os.path.exists(DELETE_ICON_PATH):
            self.delete_program_btn.setIcon(QIcon(DELETE_ICON_PATH))
        self._style_delete_icon_button(self.delete_program_btn)
        self.delete_program_btn.setToolTip("Delete the current program")
        self.delete_program_btn.clicked.connect(self._delete_program)
        self._install_press_feedback(self.delete_program_btn)
        toolbar.addWidget(self.delete_program_btn)

        self.rename_program_btn = QPushButton()
        if os.path.exists(RENAME_ICON_PATH):
            self.rename_program_btn.setIcon(QIcon(RENAME_ICON_PATH))
        self._style_editor_icon_button(self.rename_program_btn)
        self.rename_program_btn.setToolTip("Rename the current program")
        self.rename_program_btn.clicked.connect(self._rename_program)
        self._install_press_feedback(self.rename_program_btn)
        toolbar.addWidget(self.rename_program_btn)

        self.isa_btn = QPushButton("ISA")
        self.isa_btn.setMinimumSize(74, EDITOR_TOOL_BUTTON_SIZE.height())
        self.isa_btn.setCursor(Qt.PointingHandCursor)
        self.isa_btn.setFont(QFont('Segoe UI', 18, weight=800))
        _style_editor_icon_button(self.isa_btn)
        self.isa_btn.setFixedWidth(74)
        self.isa_btn.setToolTip("Show TARA instruction set reference")
        self.isa_btn.clicked.connect(self._show_isa)
        self._install_press_feedback(self.isa_btn)
        toolbar.addWidget(self.isa_btn)

        self.power_btn = QPushButton()
        self.power_btn.setIcon(_power_icon())
        self.power_btn.setIconSize(EDITOR_TOOL_ICON_SIZE)
        self.power_btn.setToolTip("Exit simulator")
        self.power_btn.setFixedSize(EDITOR_TOOL_BUTTON_SIZE)
        self.power_btn.setStyleSheet(f"""
            QPushButton {{
                background:#7F1D1D;
                color:white;
                border:1px solid #7F1D1D;
                border-radius:8px;
                font-size:24px;
                font-weight:bold;
                padding:0;
            }}
            QPushButton:hover {{
                background:#991B1B;
                color:white;
                border-color:#991B1B;
            }}
            QPushButton:pressed {{
                background:#5F1414;
                color:white;
            }}
        """ + self._tooltip_style())
        self.power_btn.clicked.connect(self.sig_power_off)
        self._install_press_feedback(self.power_btn)
        toolbar.addWidget(self.power_btn)
        layout.addLayout(toolbar)

        self.editor = CodeEditor()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setPlaceholderText(
            "; Enter TARA assembly here\n; Use semicolons for comments\n; Labels end with :\n\nLIL R1, 42\nHLT")
        layout.addWidget(self.editor)

        self.editor_font_controls = QFrame(self.editor)
        self.editor_font_controls.setObjectName("editor_font_controls")
        self.editor_font_controls.setStyleSheet(
            f"QFrame#editor_font_controls {{ background:rgba(255,255,255,235);"
            f"border:1px solid {C['border']};border-radius:17px; }}"
        )
        controls_layout = QHBoxLayout(self.editor_font_controls)
        controls_layout.setContentsMargins(3, 2, 3, 2)
        controls_layout.setSpacing(2)
        self.editor_font_dec_btn = QPushButton("A-", self.editor_font_controls)
        self.editor_font_inc_btn = QPushButton("A+", self.editor_font_controls)
        for btn in (self.editor_font_dec_btn, self.editor_font_inc_btn):
            self._style_floating_editor_button(btn)
            self._install_press_feedback(btn)
            controls_layout.addWidget(btn)
        self.editor.set_floating_font_controls(self.editor_font_controls)

        self.editor.breakpoints_changed.connect(self.sig_breakpoints_changed)
        self.editor_font_dec_btn.clicked.connect(lambda: self._adjust_editor_font(-1))
        self.editor_font_inc_btn.clicked.connect(lambda: self._adjust_editor_font(1))
        self._update_editor_font_tooltips()

        self._hl = AsmHighlighter(self.editor.document())

        # Error display
        self.error_box = QTextEdit()
        self.error_box.setReadOnly(True)
        self.error_box.setMaximumHeight(42)
        self.error_box.setFont(MONO_SM)
        self.error_box.setPlaceholderText("Assembly errors will appear here")
        self.error_box.setStyleSheet(f"color:{C['danger']};font-size:11px;")
        layout.addWidget(self.error_box)

    def _tooltip_style(self):
        return (
            "QToolTip {"
            "background:#FFFFFF;"
            f"color:{C['title']};"
            f"border:1px solid {C['border']};"
            "border-radius:6px;"
            "padding:5px 7px;"
            "font-size:12px;"
            "font-weight:600;"
            "}"
        )

    def _style_editor_icon_button(self, button):
        _style_editor_icon_button(button)

    def _style_font_text_button(self, button):
        button.setFixedSize(36, 32)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background:#FFFFFF;border:1px solid {C['border']};"
            f"color:{C['title']};border-radius:7px;padding:2px;font-weight:800; }}"
            f"QPushButton:hover {{ border-color:{C['accent']}; background:{C['panel2']}; }}"
            "QPushButton:pressed { background:#EBD9C4; padding-top:5px; }"
            + self._tooltip_style()
        )

    def _style_delete_icon_button(self, button):
        button.setFixedSize(EDITOR_TOOL_BUTTON_SIZE)
        button.setIconSize(EDITOR_TOOL_ICON_SIZE)
        button.setFont(QFont('Segoe UI', 18, weight=800))
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background:#FFFFFF;border:1px solid {C['border']};"
            f"color:{C['accent']};border-radius:8px;padding:6px 8px 8px 8px;"
            "font-size:18px;font-weight:800; }"
            f"QPushButton:hover {{ background:#FBF0EC;border-color:{C['accent']};color:#991B1B; }}"
            "QPushButton:pressed { background:#FFE1E1; padding-top:8px; padding-bottom:6px; }"
            + self._tooltip_style()
        )

    def _style_floating_editor_button(self, button):
        button.setFixedSize(34, 32)
        button.setIconSize(QSize(20, 20))
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,235);border:1px solid {C['border']};"
            f"color:{C['title']};border-radius:16px;padding:2px;font-weight:800; }}"
            f"QPushButton:hover {{ border-color:{C['accent']}; background:{C['panel2']}; }}"
            "QPushButton:pressed { background:#EBD9C4; padding-top:5px; padding-left:4px; }"
            + self._tooltip_style()
        )

    def _install_press_feedback(self, button):
        effect = QGraphicsOpacityEffect(button)
        effect.setOpacity(1.0)
        button.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", button)
        anim.setDuration(160)
        anim.setStartValue(0.58)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        button.pressed.connect(lambda: self._play_press_feedback(effect, anim))
        button._press_feedback_anim = anim

    def _play_press_feedback(self, effect, anim):
        anim.stop()
        effect.setOpacity(0.58)
        anim.start()

    def _adjust_editor_font(self, delta):
        self.editor.adjust_font_size(delta)
        self._update_editor_font_tooltips()
        self.sig_status.emit(f"Editor font size: {self.editor.font_size()} px")

    def _update_editor_font_tooltips(self):
        size = self.editor.font_size()
        self.editor_font_dec_btn.setToolTip(f"Decrease editor font size ({size} px)")
        self.editor_font_inc_btn.setToolTip(f"Increase editor font size ({size} px)")
        self.editor_font_dec_btn.setEnabled(size > 10)
        self.editor_font_inc_btn.setEnabled(size < 28)

    def _add_program_combo_item(self, label, kind, program_name=None):
        self.example_combo.addItem(label)
        idx = self.example_combo.count() - 1
        self.example_combo.setItemData(idx, kind, PROGRAM_KIND_ROLE)
        if program_name:
            self.example_combo.setItemData(idx, program_name, PROGRAM_NAME_ROLE)
        return idx

    def _add_program_category_header(self, category):
        idx = self._add_program_combo_item(category, PROGRAM_KIND_HEADER)
        item = self.example_combo.model().item(idx)
        if item is not None:
            item.setEnabled(False)
            item.setForeground(QColor(C['accent']))
            item.setBackground(QColor(C['panel2']))
            item.setFont(QFont('Segoe UI', 16, weight=900))
        return idx

    def _rebuild_program_combo(self, current_program=None):
        previous = current_program or self.current_program_name
        self.example_combo.blockSignals(True)
        self.example_combo.clear()
        self._add_program_combo_item("Select Program", "placeholder")
        self._add_program_combo_item(NEW_PROGRAM_LABEL, PROGRAM_KIND_ACTION)

        for category in EXAMPLE_CATEGORIES:
            programs = EXAMPLE_PROGRAM_GROUPS.get(category, {})
            if not programs:
                continue
            self._add_program_category_header(category)
            for name in programs:
                self._add_program_combo_item(f"  {name}", PROGRAM_KIND_EXAMPLE, name)

        self._select_program_name(previous)
        self.example_combo.blockSignals(False)

    def _select_program_name(self, name):
        idx = self._program_combo_index(name)
        self.example_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _program_combo_index(self, name):
        if not name:
            return -1
        for idx in range(self.example_combo.count()):
            if self.example_combo.itemData(idx, PROGRAM_NAME_ROLE) == name:
                return idx
        return -1

    def _category_for_program_path(self, path):
        if not path:
            return EXAMPLE_CATEGORIES[0]
        try:
            rel = Path(path).resolve().relative_to(Path(PROGS_DIR).resolve())
        except ValueError:
            return EXAMPLE_CATEGORIES[0]
        if len(rel.parts) > 1 and rel.parts[0] in EXAMPLE_CATEGORIES:
            return rel.parts[0]
        return EXAMPLE_CATEGORIES[0]

    def _remove_program_record(self, name):
        EXAMPLE_PROGRAMS.pop(name, None)
        for programs in EXAMPLE_PROGRAM_GROUPS.values():
            programs.pop(name, None)

    def _set_program_record(self, name, source, path=None):
        self._remove_program_record(name)
        category = self._category_for_program_path(path)
        EXAMPLE_PROGRAM_GROUPS.setdefault(category, {})[name] = source
        EXAMPLE_PROGRAMS[name] = source

    def _program_selected(self, index):
        kind = self.example_combo.itemData(index, PROGRAM_KIND_ROLE)
        if kind == PROGRAM_KIND_ACTION:
            self._new_program()
        elif kind == PROGRAM_KIND_EXAMPLE:
            name = self.example_combo.itemData(index, PROGRAM_NAME_ROLE)
            self._load_program(name)

    def _program_path_for_name(self, name):
        for path in sorted(Path(PROGS_DIR).rglob('*.tara')):
            if path.stem.replace('_', ' ').title() == name:
                return str(path)
        return None

    def _set_current_program(self, name, path=None):
        self.current_program_name = name
        self.current_file_path = path
        self.set_usage_example(bundled_example(path, "assembly"))
        self.editor.setToolTip(f"Loaded file: {os.path.basename(path)}" if path else "")

    def set_usage_example(self, context):
        self._usage_example = validate_example(context)
        self._usage_example_revision = self.editor.document().revision()

    def usage_example_context(self):
        if not self._usage_example:
            return None
        context = dict(self._usage_example)
        context["example_modified"] = context["example_modified"] or (
            self.editor.document().revision() != self._usage_example_revision)
        return context

    def _load_program(self, name):
        self.editor.setPlainText(EXAMPLE_PROGRAMS[name])
        self.editor.clear_breakpoints()
        self._set_current_program(name, self._program_path_for_name(name))
        if self._usage_example:
            self.usage_event.emit("example_loaded", self.usage_example_context())

    def _new_program(self):
        name, ok = QInputDialog.getText(self, "New Program", "Program name:")
        if not ok:
            self.example_combo.setCurrentIndex(0)
            return

        name = name.strip()
        if not name:
            self.example_combo.setCurrentIndex(0)
            return

        stem = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_').lower()
        if not stem:
            stem = "new_program"
        path = Path(PROGS_DIR) / EXAMPLE_CATEGORIES[0] / f"{stem}.tara"
        if path.exists():
            QMessageBox.warning(self, "New Program", f"{path.name} already exists.")
            self.example_combo.setCurrentIndex(0)
            return

        display_name = path.stem.replace('_', ' ').title()
        self.editor.setPlainText("")
        self.editor.clear_breakpoints()
        self._set_program_record(display_name, "", str(path))
        self._rebuild_program_combo(display_name)
        self._set_current_program(display_name, str(path))
        self.sig_status.emit(f"New program {path.name} created. Click Save to write it.")

    def _save_program(self):
        from PyQt5.QtWidgets import QFileDialog
        path = self.current_file_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Assembly File",
                os.path.join(PROGS_DIR, EXAMPLE_CATEGORIES[0], "new_program.tara"),
                "TARA Assembly (*.tara *.asm *.s *.txt);;All files (*)"
            )
            if not path:
                return

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.get_source())
            display_name = Path(path).stem.replace('_', ' ').title()
            self._set_program_record(display_name, self.get_source(), path)
            self._rebuild_program_combo(display_name)
            self._set_current_program(display_name, path)
            self.sig_status.emit(f"Program saved to {os.path.basename(path)}.")
        except Exception as e:
            QMessageBox.critical(self, "Save Program", f"Could not save program:\n{e}")

    def _delete_program(self):
        if not self.current_file_path:
            QMessageBox.information(self, "Delete Program", "Select or open a program before deleting.")
            return

        path = Path(self.current_file_path)
        name = self.current_program_name or path.stem.replace('_', ' ').title()
        if path.exists():
            detail = f"Delete {path.name}?\n\nThis will remove:\n{path}"
        else:
            detail = f"Remove the unsaved program {name} from the editor?"

        choice = QMessageBox.question(
            self,
            "Delete Program",
            detail,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            self.sig_status.emit("Delete cancelled.")
            return

        try:
            if path.exists():
                path.unlink()
            self._remove_program_record(name)
            self._rebuild_program_combo("")
            self.editor.setPlainText("")
            self.editor.clear_breakpoints()
            self._set_current_program("", None)
            self.sig_status.emit(f"Deleted {path.name}.")
        except Exception as e:
            QMessageBox.critical(self, "Delete Program", f"Could not delete program:\n{e}")

    def _rename_program(self):
        if not self.current_file_path:
            QMessageBox.information(self, "Rename Program", "Select or open a program before renaming.")
            return

        old_path = Path(self.current_file_path)
        old_name = self.current_program_name or old_path.stem.replace('_', ' ').title()
        new_name, ok = QInputDialog.getText(self, "Rename Program", "New program name:", text=old_name)
        if not ok:
            return

        new_name = new_name.strip()
        if not new_name:
            return

        new_stem = re.sub(r'[^A-Za-z0-9_-]+', '_', new_name).strip('_').lower()
        if not new_stem:
            QMessageBox.warning(self, "Rename Program", "Enter a valid program name.")
            return

        suffix = old_path.suffix or ".tara"
        new_path = old_path.with_name(f"{new_stem}{suffix}")
        if new_path != old_path and new_path.exists():
            QMessageBox.warning(self, "Rename Program", f"{new_path.name} already exists.")
            return

        try:
            if old_path.exists() and new_path != old_path:
                old_path.rename(new_path)

            display_name = new_path.stem.replace('_', ' ').title()
            self._remove_program_record(old_name)
            self._set_program_record(display_name, self.get_source(), str(new_path))
            self._rebuild_program_combo(display_name)
            self._set_current_program(display_name, str(new_path))
            self.sig_status.emit(f"Renamed program to {new_path.name}.")
        except Exception as e:
            QMessageBox.critical(self, "Rename Program", f"Could not rename program:\n{e}")

    def _open_file(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Assembly File", "",
            "TARA Assembly (*.tara *.asm *.s *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                src = f.read()
            self.editor.setPlainText(src)
            self.editor.clear_breakpoints()
            self.example_combo.setCurrentIndex(0)
            self._set_current_program(Path(path).stem.replace('_', ' ').title(), path)
            if self._usage_example:
                self.usage_event.emit("example_loaded", self.usage_example_context())
            self.sig_status.emit(f"Opened {os.path.basename(path)}.")
        except Exception as e:
            self.error_box.setStyleSheet(
                f"color:{C['danger']};background:{C['panel']};"
                f"border:1px solid {C['danger']};font-size:11px;")
            self.error_box.setPlainText(f"⚠ Could not open file: {e}")

    def _show_isa(self):
        dlg = ISADialog(self)
        dlg.exec_()

    def get_source(self):
        return self.editor.toPlainText()

    def get_breakpoints(self):
        return self.editor.get_breakpoints()

    def highlight_execution_line(self, line):
        self.editor.set_execution_line(line)

    def show_errors(self, errors):
        if errors:
            self.error_box.setMaximumHeight(80)
            self.error_box.setStyleSheet(f"color:{C['danger']};background:{C['panel']};border:1px solid {C['danger']};font-size:11px;")
            self.error_box.setPlainText('\n'.join(str(e) for e in errors))
        else:
            self.error_box.setMaximumHeight(34)
            self.error_box.setStyleSheet(f"color:{C['accent2']};background:{C['panel']};border:1px solid {C['border']};font-size:11px;")
            self.error_box.setPlainText("✓ Assembly successful")
