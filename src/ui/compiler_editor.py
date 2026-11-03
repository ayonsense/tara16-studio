# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""White code surfaces with the shared Studio syntax palette.

``CSourceEditor`` reuses Studio's gutter, scrolling and font controls, while
keeping its colours and font size independent of the Assembly editor. The
source and generated outputs deliberately hide whitespace markers. Import
``style_output`` for plain output panes and retain each highlighter on
its owning panel, as with any Qt syntax highlighter.
"""

import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPalette, QSyntaxHighlighter,
    QTextCharFormat, QTextOption,
)
from PyQt5.QtWidgets import QPlainTextEdit, QTextEdit

from src.simulation.cpu import OP_NAME
from src.ui.panels.editor import CodeEditor
from src.ui.theme import C


# Shared by the authoring and output panes; no application-wide stylesheet or
# Assembly editor settings are modified here.
EDITOR_COLORS = {
    "background": "#FFFFFF",
    "foreground": C["text"],
    "border": C["border"],
    "line": "#FBF5ED",
    "gutter": "#FFFFFF",
    "gutter_text": C["dim"],
    "gutter_current": C["accent"],
    "keyword": C["accent"],
    "number": "#356B58",
    "string": "#356B58",
    "function": "#855D32",
    "preprocessor": "#5E5276",
    "comment": C["dim"],
    "selection": "#EBD9C4",
}


def _code_font(size):
    """Use a fixed-pitch face with native monospace fallbacks."""
    font = QFont("Menlo")
    font.setStyleHint(QFont.Monospace)
    font.setFixedPitch(True)
    font.setPixelSize(size)
    font.setWeight(QFont.Normal)
    return font


def _editor_stylesheet(size):
    return f"""
        QPlainTextEdit {{
            background: {EDITOR_COLORS['background']};
            color: {EDITOR_COLORS['foreground']};
            border: 1px solid {EDITOR_COLORS['border']};
            border-radius: 5px;
            font-family: 'Menlo', 'Fira Code', 'Consolas', monospace;
            font-size: {size}px;
            font-weight: 400;
            selection-background-color: {EDITOR_COLORS['selection']};
            selection-color: {EDITOR_COLORS['foreground']};
        }}
        QScrollBar:vertical {{
            background: {C['panel2']}; width: 11px; margin: 1px;
            border: none;
        }}
        QScrollBar:horizontal {{
            background: {C['panel2']}; height: 11px; margin: 1px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: #C9B6A5; min-height: 28px; border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: #C9B6A5; min-width: 28px; border-radius: 4px;
        }}
        QScrollBar::handle:hover {{ background: {C['accent2']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            height: 0px; width: 0px; border: none;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        QAbstractScrollArea::corner {{ background: {C['panel2']}; border: none; }}
    """


def _hide_whitespace(editor):
    """Keep indentation clean even if the shared editor displays whitespace."""
    option = editor.document().defaultTextOption()
    visible_whitespace = (
        QTextOption.ShowTabsAndSpaces | QTextOption.ShowLineAndParagraphSeparators
    )
    option.setFlags(option.flags() & ~visible_whitespace)
    editor.document().setDefaultTextOption(option)


def _set_editor_palette(editor):
    # A palette also covers the cursor, placeholders and inactive selections,
    # which are not consistently styled by native Qt themes through CSS alone.
    palette = editor.palette()
    palette.setColor(QPalette.Base, QColor(EDITOR_COLORS["background"]))
    palette.setColor(QPalette.Text, QColor(EDITOR_COLORS["foreground"]))
    palette.setColor(QPalette.Highlight, QColor(EDITOR_COLORS["selection"]))
    palette.setColor(QPalette.HighlightedText, QColor(EDITOR_COLORS["foreground"]))
    palette.setColor(QPalette.PlaceholderText, QColor(EDITOR_COLORS["comment"]))
    editor.setPalette(palette)


def style_output(editor):
    """Style an existing QPlainTextEdit output pane without changing its text."""
    font = _code_font(14)
    editor.setFont(font)
    editor.document().setDefaultFont(font)
    editor.setTabStopDistance(QFontMetrics(font).horizontalAdvance(" ") * 4)
    editor.document().setDocumentMargin(12)
    editor.setLineWrapMode(QPlainTextEdit.NoWrap)
    editor.setStyleSheet(_editor_stylesheet(14))
    _hide_whitespace(editor)
    _set_editor_palette(editor)


def _format(color, *, italic=False):
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    fmt.setFontWeight(QFont.DemiBold)
    fmt.setFontItalic(italic)
    return fmt


class CHighlighter(QSyntaxHighlighter):
    """Highlight C, protecting quoted text from comment-marker recognition."""

    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        # Order is intentional: language keywords override function-call
        # matches (for example ``if (...)``), then strings/comments override all.
        for pattern, color in (
            (r"\b[A-Za-z_]\w*(?=\s*\()", EDITOR_COLORS["function"]),
            (r"\b(?:auto|break|case|char|const|continue|default|do|else|enum|extern|"
             r"for|if|int|long|register|return|short|signed|sizeof|static|struct|"
             r"switch|typedef|union|unsigned|void|volatile|while)\b",
             EDITOR_COLORS["keyword"]),
            (r"\b(?:0[xX][0-9a-fA-F]+|[0-9]+)\b", EDITOR_COLORS["number"]),
            (r"^\s*#\s*\w+", EDITOR_COLORS["preprocessor"]),
        ):
            self.rules.append((re.compile(pattern), _format(color)))
        self.string_format = _format(EDITOR_COLORS["string"])
        self.comment_format = _format(EDITOR_COLORS["comment"], italic=True)
        self.tokens = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//.*|/\*''')

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
        self.setCurrentBlockState(0)
        position = 0
        if self.previousBlockState() == 1:
            end = text.find("*/")
            if end < 0:
                self.setFormat(0, len(text), self.comment_format)
                self.setCurrentBlockState(1)
                return
            position = end + 2
            self.setFormat(0, position, self.comment_format)
        while position < len(text):
            match = self.tokens.search(text, position)
            if match is None:
                break
            token = match.group()
            start = match.start()
            if token == "/*":
                end = text.find("*/", match.end())
                if end < 0:
                    self.setFormat(start, len(text) - start, self.comment_format)
                    self.setCurrentBlockState(1)
                    break
                position = end + 2
                self.setFormat(start, position - start, self.comment_format)
            else:
                position = match.end()
                fmt = self.comment_format if token.startswith("//") else self.string_format
                self.setFormat(start, position - start, fmt)


class AssemblyOutputHighlighter(QSyntaxHighlighter):
    """Colour generated assembly using the shared white editor palette."""

    def __init__(self, document):
        super().__init__(document)
        mnemonics = "|".join(re.escape(op) for op in sorted(OP_NAME.values(), key=len, reverse=True))
        self.rules = [
            (re.compile(pattern, re.IGNORECASE), _format(color, italic=italic))
            for pattern, color, italic in (
                (r"\b(?:" + mnemonics + r")\b", EDITOR_COLORS["keyword"], False),
                (r"\bR[0-7]\b", EDITOR_COLORS["function"], False),
                (r"\b(?:0x[0-9a-f]+|\d+)\b", EDITOR_COLORS["number"], False),
                (r"^\s*[.\w]+\s*:", EDITOR_COLORS["preprocessor"], False),
                (r";.*$", EDITOR_COLORS["comment"], True),
            )
        ]

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class CSourceEditor(CodeEditor):
    """White C editor with a line-number gutter and no assembly breakpoints.

    CodeEditor invokes several overridable methods from its constructor. These
    overrides therefore use module constants and fields already initialized by
    CodeEditor, rather than attributes added after ``super().__init__()``.
    """

    def _editor_font(self, size=None):
        return _code_font(self._font_size if size is None else size)

    def _configure_editor_style(self):
        self._font_size = 17
        font = self._editor_font()
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(" ") * 4)
        self.document().setDocumentMargin(12)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setCursorWidth(2)
        _hide_whitespace(self)
        _set_editor_palette(self)
        self._apply_editor_stylesheet()

    def _apply_editor_stylesheet(self):
        self.setStyleSheet(_editor_stylesheet(self._font_size))

    def set_font_size(self, size):
        # The C IDE starts at an accessible size and zooms independently; do
        # not persist this value into Assembly's shared editor_font_size key.
        self._font_size = max(10, min(28, int(size)))
        self._apply_font_size()

    def toggle_breakpoint_at_y(self, _y):
        """C source is compiled, not directly executed by Studio's simulator."""

    def line_number_area_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor(EDITOR_COLORS["gutter"]))
        painter.setFont(self._editor_font(max(10, self._font_size - 2)))
        block = self.firstVisibleBlock()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = int(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                is_current = block.blockNumber() == self.textCursor().blockNumber()
                if is_current:
                    painter.fillRect(0, top, self.line_number_area.width(), height,
                                     QColor(EDITOR_COLORS["line"]))
                painter.setPen(QColor(EDITOR_COLORS[
                    "gutter_current" if is_current else "gutter_text"]))
                painter.drawText(0, top, self.line_number_area.width() - 8,
                                 self.fontMetrics().height(), Qt.AlignRight,
                                 str(block.blockNumber() + 1))
            top += height
            block = block.next()
        painter.setPen(QColor(EDITOR_COLORS["border"]))
        right = self.line_number_area.width() - 1
        painter.drawLine(right, event.rect().top(), right, event.rect().bottom())

    def highlight_current_line(self):
        selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(EDITOR_COLORS["line"]))
            selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)
        self.line_number_area.update()

    def keyPressEvent(self, event):
        # Bypass assembly-specific completion while retaining indentation for C.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not self.textCursor().hasSelection():
            cursor = self.textCursor()
            before = cursor.block().text()[:cursor.positionInBlock()]
            indent = re.match(r"[ \t]*", before).group()
            if before.rstrip().endswith("{"):
                indent += "    "
            QPlainTextEdit.keyPressEvent(self, event)
            self.insertPlainText(indent)
            return
        QPlainTextEdit.keyPressEvent(self, event)
