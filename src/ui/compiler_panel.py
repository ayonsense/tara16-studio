# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""C authoring, background compilation and explicit assembly handoff for Studio.

The panel owns an editable source document, but never executes a program or
writes to the FPGA. Each compile uses a source/options snapshot and revision;
editing while a worker runs discards its eventual result. Bundled examples are
opened as new documents so Save cannot overwrite the packaged originals.
"""

from pathlib import Path

from PyQt5.QtCore import QEvent, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QShortcut, QSizePolicy, QSplitter, QStyle,
    QTabWidget, QVBoxLayout, QWidget,
)

from src.compiler import CompilationError, compile_source
from src.compiler.catalog import EXAMPLES, load_example_groups
from src.usage.examples import bundled_example
from src.compiler.tara16cc import __version__ as COMPILER_VERSION
from src.ui.assets import _panel_title
from src.ui.compiler_editor import CHighlighter, CSourceEditor, AssemblyOutputHighlighter, style_output
from src.ui.panels.common import RENAME_ICON_PATH, _style_editor_icon_button, _style_program_combo
from src.ui.theme import C, MONO_SM


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "compiler" / "examples"
EXAMPLE_ROLE = Qt.UserRole + 1

STARTER_SOURCE = """// Write C for the TARA16 CPU.
int main(void) {
    return 42;
}
"""
OUTPUTS = (
    ("Studio assembly", "assembly", ".tara", "TARA assembly (*.tara)"),
    ("Native assembly", "native_assembly", ".s", "Native assembly (*.s)"),
    ("Hex", "hex_text", ".hex", "Hex image (*.hex)"),
    ("Listing", "listing_text", ".lst", "Assembly listing (*.lst)"),
    ("Symbols", "symbols_text", ".sym", "Symbol table (*.sym)"),
)


class CompilationWorker(QThread):
    """Run the bundled compiler outside the GUI thread, reporting plain data."""

    succeeded = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, revision, source, source_path, optimization, use_mul, parent=None):
        super().__init__(parent)
        self.revision = revision
        self.source = source
        self.source_path = source_path
        self.optimization = optimization
        self.use_mul = use_mul

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            result = compile_source(
                self.source, source_path=self.source_path,
                optimization=self.optimization, use_mul=self.use_mul,
            )
            if not self.isInterruptionRequested():
                self.succeeded.emit(self.revision, result)
        except CompilationError as error:
            if not self.isInterruptionRequested():
                self.failed.emit(self.revision, str(error))
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(self.revision, f"Compiler could not complete: {error}")


class CompilerPanel(QWidget):
    """Compile C and expose reviewed outputs; ``assembly_ready`` requests handoff.

    The window must call ``confirm_close()`` and ``shutdown()`` before accepting
    a close event. A False shutdown result keeps the panel alive until its
    bounded compiler process completes; a running QThread is never terminated.
    """

    assembly_ready = pyqtSignal(str)
    usage_event = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path = None
        self._source_path = None
        self._document_name = "Untitled.c"
        self._revision = 0
        self._result = None
        self._worker = None
        self._selected_example = None
        self._example_revision = None
        self._build_usage_context = None
        self._result_usage_context = None
        self._build_ui()
        self._replace_source(STARTER_SOURCE, "Untitled.c")
        self._install_shortcuts()

    def _action_button(self, text, icon_name, tooltip, callback, primary=False, compact=False):
        """Use one shared palette, reserving solid maroon for the main action."""
        background = C["accent"] if primary else C["panel"]
        border = C["accent"] if primary else C["border"]
        foreground = "#FFFFFF" if primary else C["accent"]
        hover = "#641624" if primary else C["panel2"]
        button = QPushButton(text)
        native_icons = {
            "new": QStyle.SP_FileIcon, "open": QStyle.SP_DirOpenIcon,
            "save": QStyle.SP_DialogSaveButton, "export": QStyle.SP_DialogSaveButton,
        }
        if icon_name in native_icons:
            button.setIcon(self.style().standardIcon(native_icons[icon_name]))
        elif icon_name == "save_as":
            button.setIcon(QIcon(RENAME_ICON_PATH))
        icon_size = 20 if compact else 34
        button.setIconSize(QSize(icon_size, icon_size))
        if compact:
            button.setFixedHeight(32)
            button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        else:
            button.setMinimumHeight(52)
        button.setCursor(Qt.PointingHandCursor)
        button.setAccessibleName(text or tooltip)
        button.setToolTip(tooltip)
        if not text:
            button.setFixedSize(54, 52)
        button.setStyleSheet(f"""
            QPushButton {{ background:{background}; border:1px solid {border};
                color:{foreground}; border-radius:8px; padding:{'3px 9px' if compact else '5px 10px'};
                font-size:{13 if compact else 18}px; font-weight:800; }}
            QPushButton:hover {{ background:{hover}; border-color:{foreground}; }}
            QPushButton:pressed {{ background:{border}; padding-top:{4 if compact else 7}px;
                padding-bottom:{2 if compact else 3}px; }}
            QPushButton:disabled {{ background:{C['panel2']}; color:{C['dim']}; border-color:{C['border']}; }}
            QToolTip {{ background:white; color:{C['text']}; border:1px solid {C['border']};
                padding:6px; font-size:13px; }}
        """)
        button.clicked.connect(callback)
        return button

    def _build_ui(self):
        """Keep compilation in one row above the source/output workspace.

        Colours and file actions follow the shared Studio theme. Splitters keep the source, output and
        diagnostics usable when the user changes their preferred proportions.
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(7)
        source_card = QGroupBox("")
        source_layout = QVBoxLayout(source_card)
        source_layout.setContentsMargins(8, 8, 8, 8)
        source_layout.setSpacing(6)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.example_combo = QComboBox()
        self.example_combo.setMinimumWidth(140)
        self.example_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        _style_program_combo(self.example_combo)
        self.example_combo.setToolTip("27 C programs, grouped like the Assembly examples")
        self.example_combo.setMaxVisibleItems(20)
        self.example_combo.view().setMinimumWidth(380)
        self._populate_example_combo()
        self.example_combo.activated[int].connect(self._load_example)
        toolbar.addWidget(self.example_combo, 1)
        self.new_button = self._action_button("", "new", "New C program", self.new_file)
        self.open_button = self._action_button("", "open", "Open C source", self.open_file)
        self.save_button = self._action_button("", "save", "Save C source", self.save_file)
        self.save_as_button = self._action_button("", "save_as", "Save C source as…", self.save_file_as)
        for button in (self.new_button, self.open_button, self.save_button, self.save_as_button):
            _style_editor_icon_button(button)
            toolbar.addWidget(button)
        source_layout.addLayout(toolbar)

        self.editor = CSourceEditor()
        self.editor.setMinimumSize(200, 130)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._c_highlighter = CHighlighter(self.editor.document())
        self.editor.textChanged.connect(self._invalidate)
        self.editor.document().modificationChanged.connect(self._update_document_tooltip)
        source_layout.addWidget(self.editor, 1)
        self.editor_font_controls = QFrame(self.editor)
        self.editor_font_controls.setObjectName("compilerFontControls")
        self.editor_font_controls.setStyleSheet(
            f"QFrame#compilerFontControls {{background:{C['panel']};border:1px solid {C['border']};border-radius:16px;}}")
        font_layout = QHBoxLayout(self.editor_font_controls)
        font_layout.setContentsMargins(3, 2, 3, 2)
        font_layout.setSpacing(2)
        self.editor_font_dec_btn = QPushButton("A−", self.editor_font_controls)
        self.editor_font_inc_btn = QPushButton("A+", self.editor_font_controls)
        for button, delta in ((self.editor_font_dec_btn, -1), (self.editor_font_inc_btn, 1)):
            button.setFixedSize(34, 28)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip("Smaller C source text" if delta < 0 else "Larger C source text")
            button.setAccessibleName(button.toolTip())
            button.setStyleSheet(
                f"QPushButton {{background:{C['panel']};color:{C['accent']};border:none;"
                "border-radius:12px;padding:0;font-size:13px;font-weight:700;}"
                f"QPushButton:hover {{background:{C['panel2']};}}"
                "QPushButton:pressed {background:#EBD9C4;}")
            button.clicked.connect(lambda _checked=False, step=delta: self.editor.adjust_font_size(step))
            font_layout.addWidget(button)
        self.editor.set_floating_font_controls(self.editor_font_controls)
        self.splitter.addWidget(source_card)

        self.compiler_controls = QFrame()
        self.compiler_controls.setObjectName("compilerControls")
        self.compiler_controls.setStyleSheet(
            f"QFrame#compilerControls {{background:white;border:1px solid {C['border']};border-radius:8px;}}")
        self.compiler_controls.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        control_layout = QHBoxLayout(self.compiler_controls)
        control_layout.setContentsMargins(10, 6, 10, 6)
        control_layout.setSpacing(8)
        optimization_label = QLabel("Optimization")
        optimization_label.setStyleSheet("font-size:13px;")
        control_layout.addWidget(optimization_label)
        self.optimization_combo = QComboBox()
        for level in range(3):
            self.optimization_combo.addItem(f"O{level}", level)
        self.optimization_combo.setCurrentIndex(2)
        self.optimization_combo.setFixedSize(72, 32)
        self.optimization_combo.setStyleSheet(f"QComboBox {{background:{C['panel2']};color:{C['accent']};"
                                              f"border:1px solid {C['border']};border-radius:6px;"
                                              "padding:3px 10px;font-size:15px;font-weight:800;}")
        self.optimization_combo.setToolTip("O0: unoptimized · O1/O2: compiler optimization passes")
        self.optimization_combo.currentIndexChanged.connect(self._invalidate)
        control_layout.addWidget(self.optimization_combo)
        control_layout.addSpacing(4)
        self.mul_checkbox = QCheckBox("Hardware MUL")
        self.mul_checkbox.setChecked(True)
        self.mul_checkbox.setMinimumWidth(132)
        self.mul_checkbox.setStyleSheet(f"QCheckBox {{color:{C['text']};font-weight:600;font-size:13px;}}")
        self.mul_checkbox.setToolTip("Use TARA's hardware multiply instruction; uncheck for software multiplication.")
        self.mul_checkbox.toggled.connect(self._invalidate)
        control_layout.addWidget(self.mul_checkbox)
        control_layout.addSpacing(4)
        self.compile_button = self._action_button(
            "Compile C", "compile", "Compile the current C source (Ctrl/Cmd+Return)", self.compile, primary=True, compact=True)
        self.send_button = self._action_button(
            "Send to Assembly", "assembly", "Send the compiled program to TARA16 Assembly", self.send_to_assembly, compact=True)
        for button in (self.compile_button, self.send_button):
            control_layout.addWidget(button)
        control_layout.addStretch()
        self.compiler_version_label = QLabel(f"C compiler v{COMPILER_VERSION}")
        self.compiler_version_label.setToolTip("Bundled tara16-cc compiler version")
        self.compiler_version_label.setStyleSheet(f"color:{C['dim']};font-size:11px;")
        control_layout.addWidget(self.compiler_version_label)
        self.status_badge = QLabel("READY")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setMinimumWidth(80)
        control_layout.addWidget(self.status_badge)
        layout.addWidget(self.compiler_controls)

        right = QSplitter(Qt.Vertical)
        right.setChildrenCollapsible(False)
        right.setHandleWidth(7)
        output_card = QGroupBox("")
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(10, 10, 10, 8)
        output_layout.setSpacing(8)
        self.output_tabs = QTabWidget()
        self.output_tabs.setObjectName("compilerOutputTabs")
        self.output_tabs.setMinimumWidth(300)
        self.output_tabs.setUsesScrollButtons(True)
        self.output_tabs.setStyleSheet(f"""
            QTabWidget#compilerOutputTabs::pane {{border:none;background:transparent;}}
            QTabBar::tab {{min-width:40px;background:{C['panel2']};color:{C['accent']};border:1px solid {C['border']};
                border-bottom:2px solid transparent;padding:8px 10px;font-size:13px;font-weight:700;}}
            QTabBar::tab:selected {{background:white;color:{C['accent']};border-bottom:2px solid {C['accent']};}}
            QTabBar::tab:hover:!selected {{background:#EBD9C4;color:#641624;}}
        """)
        self.output_editors = {}
        short_titles = ("Assembly", "Native", "Hex", "Listing", "Symbols")
        for short_title, (title, attribute, suffix, _file_filter) in zip(short_titles, OUTPUTS):
            output = QPlainTextEdit()
            output.setReadOnly(True)
            style_output(output)
            output.setLineWrapMode(QPlainTextEdit.NoWrap)
            # Native scroll-beyond-end keeps the last output lines readable
            # above the floating action without taking space from the IDE.
            output.setCenterOnScroll(True)
            output.setPlaceholderText("Compile your C program to view the generated output.")
            output.viewport().installEventFilter(self)
            output.updateRequest.connect(self._position_export_button)
            # A full-width gap separates the tab strip from the code surface.
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 12, 0, 0)
            page_layout.setSpacing(0)
            page_layout.addWidget(output)
            self.output_tabs.addTab(page, short_title)
            self.output_tabs.setTabToolTip(self.output_tabs.count() - 1, f"{title} ({suffix})")
            self.output_editors[attribute] = output
        self._assembly_highlighter = AssemblyOutputHighlighter(self.output_editors["assembly"].document())
        self._native_highlighter = AssemblyOutputHighlighter(self.output_editors["native_assembly"].document())
        output_layout.addWidget(self.output_tabs, 1)
        self.export_button = self._action_button("Export .tara…", "export",
            "Save the selected compiler output to a file", self.export_output, compact=True)
        self.output_tabs.currentChanged.connect(self._update_actions)
        right.addWidget(output_card)

        diagnostics_card = QGroupBox("")
        diagnostics_layout = QVBoxLayout(diagnostics_card)
        diagnostics_layout.setContentsMargins(10, 8, 10, 8)
        diagnostics_layout.setSpacing(6)
        diagnostics_header = QHBoxLayout()
        diagnostics_header.addWidget(_panel_title("Build Messages"))
        diagnostics_header.addStretch()
        self.copy_messages_button = self._action_button("Copy", None,
            "Copy the build status and all compiler messages", self.copy_build_messages, compact=True)
        self.copy_messages_button.setAccessibleName("Copy build messages")
        diagnostics_header.addWidget(self.copy_messages_button)
        diagnostics_layout.addLayout(diagnostics_header)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.status_label.setFocusPolicy(Qt.StrongFocus)
        self.status_label.setStyleSheet(f"color:{C['dim']};font-size:12px;")
        diagnostics_layout.addWidget(self.status_label)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.diagnostics.setFont(MONO_SM)
        self.diagnostics.setMinimumHeight(56)
        self.diagnostics.setStyleSheet(f"QPlainTextEdit {{background:#FBF8F4;color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:6px;padding:4px;font-family:Menlo;"
            "font-size:12px;selection-background-color:#EBD9C4;selection-color:#2B2320;}")
        self.diagnostics.setPlaceholderText("Compiler messages and errors will appear here.")
        diagnostics_layout.addWidget(self.diagnostics, 1)
        right.addWidget(diagnostics_card)
        right.setSizes([530, 160])
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 0)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([720, 650])
        layout.addWidget(self.splitter, 1)
        self._set_status("Choose an example or write C, then click Compile C.")
        self._update_actions()

    def _set_status(self, message, state="ready"):
        """Pair concise messages with the same state-badge pattern as CPU Control."""
        label, foreground, background = {
            "ready": ("READY", C["accent"], C["panel2"]),
            "busy": ("COMPILING", "#855D32", "#FBF1DB"),
            "success": ("BUILT", "#4D6852", "#EFF3ED"),
            "error": ("ERROR", C["danger"], "#FBEDEB"),
            "warning": ("CHECK SIZE", "#855D32", "#FBF1DB"),
        }[state]
        self.status_label.setText(message)
        self.status_badge.setText(label)
        self.status_badge.setStyleSheet(f"background:{background};color:{foreground};"
            "border-radius:8px;padding:4px 9px;font-size:11px;font-weight:800;")

    def _populate_example_combo(self):
        """Mirror Assembly's grouped selector, with nonselectable headings."""
        self.example_combo.clear()
        self.example_combo.addItem(f"Select C Program ({len(EXAMPLES)})", None)
        for category, examples in load_example_groups().items():
            self.example_combo.addItem(f"{category}  ({len(examples)})", None)
            heading = self.example_combo.model().item(self.example_combo.count() - 1)
            heading.setEnabled(False)
            heading.setForeground(QColor(C["accent"]))
            heading.setBackground(QColor(C["panel2"]))
            font = QFont()
            font.setPixelSize(15)
            font.setBold(True)
            heading.setFont(font)
            for example in examples:
                self.example_combo.addItem(f"  {example.title}", str(example.path))
                index = self.example_combo.count() - 1
                self.example_combo.setItemData(index, example, EXAMPLE_ROLE)
                self.example_combo.setItemData(index,
                    example.description + "\n\n" + example.expected_result, Qt.ToolTipRole)

    def _install_shortcuts(self):
        self._shortcuts = []
        for sequence, callback in (
            (QKeySequence.New, self.new_file), (QKeySequence.Open, self.open_file),
            (QKeySequence.Save, self.save_file), (QKeySequence.SaveAs, self.save_file_as),
            (QKeySequence("Ctrl+Return"), self.compile),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _update_document_tooltip(self, *_args):
        marker = " *" if self.editor.document().isModified() else ""
        self.editor.setAccessibleName("C source: " + self._document_name + marker)
        location = str(self._file_path or self._source_path or "Unsaved C source")
        self.editor.setToolTip(self._document_name + marker + "\n" + location)

    def _invalidate(self, *_args):
        """Invalidate snapshots immediately, including a build still in flight."""
        self._revision += 1
        self._result = None
        self._result_usage_context = None
        for editor in getattr(self, "output_editors", {}).values():
            editor.clear()
        if hasattr(self, "status_label"):
            if self._worker is not None:
                self._set_status("Source changed. Compile again when this build finishes.", "busy")
            else:
                self._set_status("Ready to compile the current C source.")
        if hasattr(self, "diagnostics"):
            self.diagnostics.clear()
        if hasattr(self, "send_button"):
            self._update_actions()

    def _update_actions(self, *_args):
        current = OUTPUTS[max(0, self.output_tabs.currentIndex())]
        if hasattr(self, "export_button"):
            self.export_button.setText(f"Export {current[2]}…")
            self.export_button.setAccessibleName(f"Export {current[2]}")
            self.export_button.setEnabled(
                self._result is not None and bool(getattr(self._result, current[1], "")))
            self._position_export_button()
        if hasattr(self, "send_button"):
            self.send_button.setEnabled(
                self._result is not None and bool(self._result.assembly)
                and not getattr(self._result, "studio_error", None))

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            if any(watched is editor.viewport() for editor in self.output_editors.values()):
                # Native scrollbars may settle after the viewport's resize.
                QTimer.singleShot(0, self._position_export_button)
        return super().eventFilter(watched, event)

    def _position_export_button(self, *_args):
        """Keep one Export action inside the active editor, clear of scrollbars."""
        if not hasattr(self, "export_button"):
            return
        current = OUTPUTS[max(0, self.output_tabs.currentIndex())]
        output = self.output_editors[current[1]]
        viewport = output.viewport()
        if self.export_button.parentWidget() is not viewport:
            self.export_button.setParent(viewport)
        self.export_button.adjustSize()
        margin = 10
        self.export_button.move(
            max(margin, viewport.width() - self.export_button.width() - margin),
            max(margin, viewport.height() - self.export_button.height() - margin),
        )
        self.export_button.show()
        self.export_button.raise_()

    def _replace_source(self, source, name, file_path=None, source_path=None):
        self._selected_example = None
        self._file_path = Path(file_path) if file_path else None
        self._source_path = str(source_path or file_path) if (source_path or file_path) else None
        self._document_name = name
        self.editor.setPlainText(source)
        self.editor.document().setModified(False)
        self._update_document_tooltip()
        self.editor.setFocus()

    def confirm_close(self):
        """Ask to save edited source before replacing it or closing Studio."""
        if not self.editor.document().isModified():
            return True
        choice = QMessageBox.question(
            self, "Unsaved C source", f"Save changes to {self._document_name}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Cancel:
            return False
        return self.save_file() if choice == QMessageBox.Save else True

    def new_file(self):
        if self.confirm_close():
            self.example_combo.setCurrentIndex(0)
            self._replace_source(STARTER_SOURCE, "Untitled.c")

    def open_file(self):
        if not self.confirm_close():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open C source", str(self._file_path.parent) if self._file_path else "",
            "C source (*.c *.h);;All files (*)")
        if not path:
            return
        try:
            source = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self, "Cannot open C source", str(error))
            return
        self.example_combo.setCurrentIndex(0)
        self._replace_source(source, Path(path).name, file_path=path)
        if bundled_example(path, "c"):
            self._selected_example = next((example for example in EXAMPLES
                if example.path.resolve() == Path(path).resolve()), None)
            self._example_revision = self.editor.document().revision()
            self.usage_event.emit("example_loaded", self.usage_example_context())

    def _load_example(self, index):
        example = self.example_combo.itemData(index, EXAMPLE_ROLE)
        if example is None:
            return
        if not self.confirm_close():
            self._restore_example_selection()
            return
        try:
            source = example.path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self, "Cannot open example", str(error))
            self._restore_example_selection()
            return
        self._replace_source(source, example.path.name, source_path=str(example.path))
        self._selected_example = example
        self._example_revision = self.editor.document().revision()
        self.usage_event.emit("example_loaded", self.usage_example_context())
        self.example_combo.setCurrentIndex(index)
        self._set_status(f"{example.category}: {example.title}. Compile at O2; Save creates your own copy.")

    def _restore_example_selection(self):
        for index in range(self.example_combo.count()):
            if self._selected_example is not None and self.example_combo.itemData(index, EXAMPLE_ROLE) == self._selected_example:
                self.example_combo.setCurrentIndex(index)
                return
        self.example_combo.setCurrentIndex(0)

    def save_file(self):
        return self._write_source(self._file_path) if self._file_path else self.save_file_as()

    def save_file_as(self):
        suggestion = str(self._file_path) if self._file_path else self._document_name
        path, _ = QFileDialog.getSaveFileName(self, "Save C source", suggestion, "C source (*.c);;All files (*)")
        if not path:
            return False
        destination = self._destination_with_suffix(path, ".c")
        return self._write_source(destination) if destination is not None else False

    def _destination_with_suffix(self, path, suffix):
        """Confirm an existing destination that the native dialog did not see.

        The save dialog confirms the entered path. When adding a default suffix
        changes that path, its overwrite check must be performed once more.
        """
        destination = Path(path)
        if destination.suffix:
            return destination
        destination = destination.with_suffix(suffix)
        if destination.exists():
            answer = QMessageBox.question(
                self, "Replace existing file?", f"{destination.name} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return None
        return destination

    def _write_source(self, destination):
        try:
            Path(destination).write_text(self.editor.toPlainText(), encoding="utf-8")
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self, "Cannot save C source", str(error))
            return False
        changed_path = self._source_path != str(destination)
        self._file_path = Path(destination)
        self._source_path = str(destination)
        self._document_name = self._file_path.name
        self.editor.document().setModified(False)
        self._update_document_tooltip()
        if changed_path:
            # Relative include resolution may change when a document moves.
            self._invalidate()
        return True

    def usage_example_context(self):
        if self._selected_example is None:
            return None
        return bundled_example(self._selected_example.path, "c",
            modified=self.editor.document().revision() != self._example_revision)

    def compiled_example_context(self):
        return dict(self._result_usage_context) if self._result_usage_context else None

    def compile(self):
        if self._worker is not None:
            return
        self._build_usage_context = self.usage_example_context()
        self.usage_event.emit("compile_started", self._build_usage_context)
        self._invalidate()
        self._set_status("Compiling C and generating TARA16 output…", "busy")
        self.compile_button.setEnabled(False)
        self._worker = CompilationWorker(
            self._revision, self.editor.toPlainText(), self._source_path,
            self.optimization_combo.currentData(), self.mul_checkbox.isChecked(), self,
        )
        self._worker.succeeded.connect(self._compile_succeeded)
        self._worker.failed.connect(self._compile_failed)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _compile_succeeded(self, revision, result):
        self.usage_event.emit("compile_succeeded", self._build_usage_context)
        if revision != self._revision:
            return
        self._result = result
        self._result_usage_context = self._build_usage_context
        for _title, attribute, _suffix, _filter in OUTPUTS:
            self.output_editors[attribute].setPlainText(getattr(result, attribute, "") or "")
        diagnostics = result.diagnostics
        if not isinstance(diagnostics, str):
            diagnostics = "\n".join(str(item) for item in diagnostics) if diagnostics else ""
        studio_error = getattr(result, "studio_error", None)
        if studio_error:
            diagnostics += f"\nStudio assembly unavailable: {studio_error}"
            self._set_status("Native output built. Assembly transfer needs attention below.", "warning")
        else:
            self._set_status("Build succeeded. The program is ready for TARA16 Assembly.", "success")
        self.diagnostics.setPlainText(diagnostics.strip() or "Compilation completed without diagnostics.")
        self._update_actions()

    def _compile_failed(self, revision, message):
        self.usage_event.emit("compile_failed", self._build_usage_context)
        if revision != self._revision:
            return
        self._set_status("Build failed. Check the compiler messages below.", "error")
        self.diagnostics.setPlainText(message)
        self._update_actions()

    def _worker_finished(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            if worker.isInterruptionRequested():
                self._set_status("Compilation stopped. Ready to close or compile again.")
            worker.deleteLater()
        self.compile_button.setEnabled(True)

    def send_to_assembly(self):
        """Only emit the current successful snapshot; the host controls switching."""
        if (self._result is not None and self._result.assembly
                and not getattr(self._result, "studio_error", None)):
            self.assembly_ready.emit(self._result.assembly)

    def copy_build_messages(self):
        """Copy the complete build report without changing its visible status."""
        parts = (self.status_label.text(), self.diagnostics.toPlainText())
        QApplication.clipboard().setText("\n\n".join(part for part in parts if part))

    def export_output(self):
        if self._result is None:
            return
        title, attribute, suffix, file_filter = OUTPUTS[self.output_tabs.currentIndex()]
        content = getattr(self._result, attribute, "")
        if not content:
            return
        name = Path(self._document_name).stem + suffix
        suggestion = str(self._file_path.parent / name) if self._file_path else name
        path, _ = QFileDialog.getSaveFileName(self, f"Export {title.lower()}", suggestion, file_filter)
        if not path:
            return
        destination = self._destination_with_suffix(path, suffix)
        if destination is None:
            return
        try:
            destination.write_text(content, encoding="utf-8")
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self, "Cannot export output", str(error))
            return
        self._set_status(f"Exported {destination.name}.", "success")

    def shutdown(self, timeout_ms=1500):
        """Return False while compilation is finishing; never destroy a live thread.

        Cancellation suppresses result publication. The backend subprocess has
        its own timeout, so the window can safely remain open until it finishes.
        The caller must ignore its close event when this method returns False.
        """
        if self._worker is None:
            return True
        self._worker.requestInterruption()
        return self._worker.wait(max(0, int(timeout_ms)))
