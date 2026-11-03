# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""
FPGA Memory Tool — a panel embedded as the second top-level tab of the TARA
simulator. It can talk to the TARA processor running on a real FPGA over the
USB-UART (mem_monitor), or to the simulator's own TaraCPU memory through a
virtual link for hardware-free debugging. Both modes expose the same
read/write/visualize and assemble-and-run workflow.

It can also configure the board itself: after a cold boot the fabric is blank,
so the Board Setup dialog loads a Vivado ``.bit`` onto the Basys 3 over
JTAG (via ``src/ui/bitstream.py``) to bring the CPU — and this monitor — up on
a machine that has no Vivado installed.

Protocol (115200 8N1), byte address A (even), word count C, big-endian words:
  Ping : b'P'                          -> 0xA5
  Read : b'R' + A(2) + C(2)            -> C words (2C bytes)
  Write: b'W' + A(2) + C(2) + 2C data  -> b'K'
  Hold : b'H'    Run/release: b'G'
"""
import os, struct, random

# pyserial is optional: the rest of the simulator must still run without it.
try:
    import serial
    import serial.tools.list_ports as list_ports
    _HAVE_SERIAL = True
except Exception:                       # pragma: no cover
    _HAVE_SERIAL = False

from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox, QTableWidget,
    QTableWidgetItem, QHBoxLayout, QVBoxLayout, QFileDialog, QInputDialog,
    QHeaderView, QStyle, QFrame, QAbstractItemView, QMessageBox, QDialog,
    QTextBrowser, QDialogButtonBox, QGraphicsDropShadowEffect, QStyledItemDelegate,
    QRadioButton, QButtonGroup, QShortcut, QMenuBar)
from PyQt5.QtCore import Qt, QTimer, QSettings, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QBrush, QKeySequence

from src.usage.examples import bundled_example, validate_example
from src.paths import PROGS_DIR
from src.assembler.asm import assemble
from src.ui import bitstream as bs
from src.ui.theme import C

MEM_BYTES, MEM_WORDS, FB_BASE = 2048, 1024, 0x600

# The FPGA tool and the rest of Studio use the same warm palette.
ACCENT, ACCENT2 = C['accent'], C['accent2']
ACCENT_HOVER, ACCENT_PRESS, GOLD_HOVER = C['accent_hover'], C['accent_press'], "#8C6322"
BG, PANEL, PANEL2, BORDER, TEXT, DIM = (C[key] for key in ('bg', 'panel', 'panel2', 'border', 'text', 'dim'))
CHANGED, GOLD, OKC, DANGER = C['changed'], C['gold_soft'], "#326345", C['danger']
DANGER_LITE, DANGER_LITE_H, LABEL = "#B86262", "#9F5050", C['text']

STYLE = f"""
QWidget#fpgaRoot {{ background:{BG}; color:{TEXT};
    font-family:'Helvetica Neue','Segoe UI',Arial,sans-serif; font-size:16px; }}
#fpgaRoot QLabel {{ background:transparent; color:{LABEL}; font-size:14px; font-weight:600; }}
#fpgaRoot QLabel#title {{ font-size:28px; font-weight:800; color:{ACCENT}; }}
#fpgaRoot QLabel#subtitle {{ font-size:14px; font-weight:500; color:{DIM}; }}
#fpgaRoot QFrame#card {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:14px; }}
#fpgaRoot QFrame#divider {{ background:{BORDER}; max-height:1px; border:none; }}
#fpgaRoot QMenuBar {{ background:{PANEL}; color:{LABEL}; border:1px solid {BORDER};
    border-radius:8px; padding:2px 5px; font-size:14px; font-weight:600; }}
#fpgaRoot QMenuBar::item {{ background:transparent; padding:5px 12px; border-radius:5px; }}
#fpgaRoot QMenuBar::item:selected {{ background:{PANEL2}; color:{ACCENT}; }}
#fpgaRoot QMenu {{ background:{PANEL}; color:{TEXT}; border:1px solid {BORDER};
    padding:5px; font-size:14px; }}
#fpgaRoot QMenu::item {{ padding:7px 26px 7px 12px; border-radius:5px; }}
#fpgaRoot QMenu::item:selected {{ background:{PANEL2}; color:{ACCENT}; }}
#fpgaRoot QRadioButton {{ background:transparent; color:{LABEL}; font-size:14px; font-weight:600; spacing:5px; }}
#fpgaRoot QRadioButton::indicator {{ width:15px; height:15px; border:1.6px solid {BORDER};
    border-radius:9px; background:{PANEL}; }}
#fpgaRoot QRadioButton::indicator:checked {{ background:{ACCENT}; border:1.6px solid {ACCENT}; }}
#fpgaRoot QPushButton {{ background:{ACCENT}; color:white; border:none; border-radius:9px;
    padding:6px 11px; font-size:14px; font-weight:600; }}
#fpgaRoot QPushButton:hover {{ background:{ACCENT_HOVER}; }}
#fpgaRoot QPushButton:pressed {{ background:{ACCENT_PRESS}; }}
#fpgaRoot QPushButton:disabled {{ background:#CBB9AE; }}
#fpgaRoot QPushButton#ghost {{ background:{PANEL}; color:{ACCENT}; border:1.5px solid {BORDER}; }}
#fpgaRoot QPushButton#ghost:hover {{ background:{PANEL2}; }}
#fpgaRoot QPushButton#run {{ background:{ACCENT2}; }}
#fpgaRoot QPushButton#run:hover {{ background:{GOLD_HOVER}; }}
#fpgaRoot QPushButton#danger {{ background:{DANGER_LITE}; }}
#fpgaRoot QPushButton#danger:hover {{ background:{DANGER_LITE_H}; }}
#fpgaRoot QPushButton#mini {{ background:{PANEL}; color:{ACCENT}; border:1.5px solid {BORDER};
    border-radius:8px; padding:4px 8px; font-size:14px; font-weight:800; min-width:14px; }}
#fpgaRoot QPushButton#mini:hover {{ background:{PANEL2}; }}
#fpgaRoot QLineEdit, #fpgaRoot QComboBox {{ background:{PANEL}; border:1.5px solid {BORDER};
    color:{TEXT}; border-radius:8px; padding:5px 8px; font-size:14px; }}
#fpgaRoot QLineEdit:focus, #fpgaRoot QComboBox:focus {{ border:1.5px solid {ACCENT2}; }}
#fpgaRoot QCheckBox {{ background:transparent; color:{LABEL}; font-size:14px; font-weight:600; spacing:6px; }}
#fpgaRoot QCheckBox::indicator {{ width:16px; height:16px; border:1.6px solid {BORDER};
    border-radius:5px; background:{PANEL}; }}
#fpgaRoot QCheckBox::indicator:hover {{ border:1.6px solid {ACCENT2}; }}
#fpgaRoot QCheckBox::indicator:checked {{ background:{ACCENT}; border:1.6px solid {ACCENT}; }}
#fpgaRoot QHeaderView::section {{ background:{PANEL2}; color:{ACCENT}; padding:8px 4px;
    border:none; font-weight:700; font-size:14px; }}
#fpgaRoot QTableWidget {{ background:{PANEL}; gridline-color:#ECE2D8;
    border:1px solid {BORDER}; border-radius:12px; }}
#fpgaRoot QTableWidget::item:selected {{ background:#EBD9C4; color:{TEXT}; }}
/* used by the bitstream programming / setup dialogs, which reuse this sheet */
#fpgaRoot QProgressBar {{ background:{PANEL2}; border:1.5px solid {BORDER}; border-radius:8px;
    text-align:center; color:{TEXT}; font-size:13px; font-weight:700; min-height:18px; }}
#fpgaRoot QProgressBar::chunk {{ background:{ACCENT2}; border-radius:6px; }}
#fpgaRoot QPlainTextEdit {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:10px;
    color:{TEXT}; padding:6px; }}
"""

# inferno-style heat-map ramp (dependency-free)
_INFERNO = [(0,0,4),(40,11,84),(101,21,110),(159,42,99),(212,72,66),
            (245,125,21),(250,193,39),(252,255,164)]
def heat_color(v):
    t = max(0.0, min(1.0, v/255.0))*(len(_INFERNO)-1); i = int(t); f = t-i
    if i >= len(_INFERNO)-1: r,g,b = _INFERNO[-1]
    else:
        c0,c1 = _INFERNO[i],_INFERNO[i+1]
        r = c0[0]+(c1[0]-c0[0])*f; g = c0[1]+(c1[1]-c0[1])*f; b = c0[2]+(c1[2]-c0[2])*f
    return QColor(int(r),int(g),int(b))
def contrast_color(qc):
    return QColor("#FFFFFF") if 0.299*qc.red()+0.587*qc.green()+0.114*qc.blue() < 140 else QColor("#101010")


def clamp_even_addr(addr):
    return max(0, min(MEM_BYTES - 2, int(addr))) & ~1


def remaining_words(addr):
    addr = clamp_even_addr(addr)
    return max(0, (MEM_BYTES - addr) // 2)


def assemble_tara(path):
    with open(path) as f:
        words, listing, errors, labels = assemble(f.read())
    if errors:
        raise ValueError("; ".join(str(e) for e in errors[:5]))
    return [w for _a, w in words]


class TaraLink:
    CHUNK = 64
    def __init__(self): self.ser = None
    def open(self, port, baud=115200):
        self.close(); self.ser = serial.Serial(port, baud, timeout=3.0, write_timeout=3.0)
    def close(self):
        if self.ser and self.ser.is_open: self.ser.close()
        self.ser = None
    @property
    def is_open(self): return self.ser is not None and self.ser.is_open
    def ping(self):
        self.ser.reset_input_buffer(); self.ser.write(b'P'); return self.ser.read(1) == b'\xA5'
    def _read_chunk(self, addr, n):
        self.ser.reset_input_buffer(); self.ser.write(b'R'+struct.pack('>HH', clamp_even_addr(addr), n))
        data = self.ser.read(2*n)
        if len(data) != 2*n: raise IOError(f"short read @0x{addr:03X}: got {len(data)}/{2*n} bytes")
        return data
    def read_words(self, addr, n):
        addr = clamp_even_addr(addr); n = max(0, min(n, remaining_words(addr))); out, off = b'', 0
        while off < n:
            k = min(self.CHUNK, n-off); out += self._read_chunk(addr+off*2, k); off += k
        return [(out[2*i] << 8) | out[2*i+1] for i in range(n)]
    def _write_chunk(self, addr, words):
        p = b'W'+struct.pack('>HH', clamp_even_addr(addr), len(words))
        p += b''.join(struct.pack('>H', w & 0xFFFF) for w in words)
        self.ser.write(p); return self.ser.read(1) == b'K'
    def write_words(self, addr, words):
        addr = clamp_even_addr(addr); words = list(words)[:remaining_words(addr)]; off, ok = 0, True
        while off < len(words):
            k = min(self.CHUNK, len(words)-off)
            ok = self._write_chunk(addr+off*2, words[off:off+k]) and ok; off += k
        return ok
    def hold(self): self.ser.write(b'H')
    def go(self):   self.ser.write(b'G')


class SimulatorMemoryLink:
    """Memory-link backend that presents the live TaraCPU memory through the
    same word-oriented API as the FPGA UART monitor."""
    CHUNK = 64

    def __init__(self, cpu=None, memory_changed=None):
        self.cpu = cpu
        self.memory_changed = memory_changed
        self._open = False

    def open(self, _port=None, _baud=115200):
        if self.cpu is None:
            raise RuntimeError("simulator CPU is not available")
        self._open = True

    def close(self):
        self._open = False

    @property
    def is_open(self):
        return self._open and self.cpu is not None

    def ping(self):
        return self.cpu is not None

    def read_words(self, addr, n):
        if not self.is_open:
            raise IOError("simulator memory link is not connected")
        addr = clamp_even_addr(addr)
        n = max(0, min(n, remaining_words(addr)))
        return [self.cpu.read_word(addr + i * 2) for i in range(n)]

    def write_words(self, addr, words):
        if not self.is_open:
            raise IOError("simulator memory link is not connected")
        addr = clamp_even_addr(addr)
        words = list(words)[:remaining_words(addr)]
        for i, w in enumerate(words):
            self.cpu.write_word(addr + i * 2, w)
        if self.memory_changed:
            data = bytearray()
            for w in words:
                data.extend([(w >> 8) & 0xFF, w & 0xFF])
            self.memory_changed(addr, bytes(data))
        return True

    def hold(self):
        return None

    def go(self):
        return None


def _shadow(w):
    e = QGraphicsDropShadowEffect(w); e.setBlurRadius(22); e.setOffset(0, 4)
    e.setColor(QColor(70, 40, 30, 38)); w.setGraphicsEffect(e); return w


class _CellDelegate(QStyledItemDelegate):
    """Paint each cell's background ourselves so the heat-map and the changed /
    framebuffer tints survive the app-wide stylesheet. (A global QSS rule for
    'QTableWidget::item { background }' otherwise overrides setBackground(), which
    is why the simulator's own memory grid also uses a delegate.)"""
    def paint(self, painter, option, index):
        painter.save()
        # Keep text inside its own cell.  Without an explicit clip the custom
        # delegate can paint a wide value over neighbouring byte columns.
        painter.setClipRect(option.rect)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#EBD9C4"))
        else:
            bg = index.data(Qt.BackgroundRole)
            painter.fillRect(option.rect, bg if isinstance(bg, QBrush) else QColor(PANEL))
        fg = index.data(Qt.ForegroundRole)
        painter.setPen(fg.color() if isinstance(fg, QBrush) else QColor(TEXT))
        painter.setFont(option.font)
        a = index.data(Qt.TextAlignmentRole)
        a = int(a) if a is not None else int(Qt.AlignVCenter | Qt.AlignLeft)
        painter.drawText(option.rect.adjusted(5, 0, -5, 0), a, str(index.data(Qt.DisplayRole) or ""))
        painter.restore()


class FpgaMonitorPanel(QWidget):
    """Second top-level tab: read/write/visualize target memory and load programs."""
    connection_changed = pyqtSignal(bool)   # emitted True on connect, False on disconnect
    usage_event = pyqtSignal(str, object)

    def __init__(
        self,
        parent=None,
        simulator_cpu=None,
        on_simulator_memory_changed=None,
        on_simulator_program_loaded=None,
    ):
        super().__init__(parent)
        self.setObjectName("fpgaRoot")
        self.serial_link = TaraLink()
        self.sim_link = SimulatorMemoryLink(simulator_cpu, on_simulator_memory_changed)
        self.link = self.serial_link
        self._on_simulator_program_loaded = on_simulator_program_loaded
        self.prev = {}
        self.cell_pt = 16
        self.settings = QSettings("TARA-IITM", "MemoryMonitor")
        self._build()
        self.setStyleSheet(STYLE)
        if not _HAVE_SERIAL:
            self._status("Simulator Memory available; install pyserial for FPGA USB.", ok=True)
        else:
            self._refresh_ports()

    # ---- small helpers ----
    def _ic(self, sp): return self.style().standardIcon(sp)
    def _btn(self, text, sp=None, kind=None, slot=None):
        b = QPushButton(text)
        if sp is not None: b.setIcon(self._ic(sp))
        if kind: b.setObjectName(kind)
        if slot: b.clicked.connect(slot)
        return b
    def _card(self):
        f = QFrame(); f.setObjectName("card"); _shadow(f)
        lay = QHBoxLayout(f); lay.setContentsMargins(12, 7, 12, 7); lay.setSpacing(8)
        return f, lay

    # ---- layout ----
    def _build(self):
        V = QVBoxLayout(self); V.setContentsMargins(14, 12, 14, 10); V.setSpacing(8)

        menu_bar = QMenuBar(self)
        menu_bar.setNativeMenuBar(False)
        setup_action = menu_bar.addAction("Board Setup")
        setup_action.setToolTip("Detect or configure the FPGA and program SRAM or SPI flash")
        setup_action.triggered.connect(self._show_board_setup)
        connect_action = menu_bar.addAction("Connect Memory")
        connect_action.setToolTip("Connect the memory tools to FPGA USB or Simulator Memory")
        connect_action.triggered.connect(self._show_connection_dialog)
        help_action = menu_bar.addAction("Help")
        help_action.triggered.connect(self._show_help)
        V.setMenuBar(menu_bar)
        self.menu_bar = menu_bar

        head = QHBoxLayout()
        tcol = QVBoxLayout(); tcol.setSpacing(1)
        t = QLabel("FPGA Memory Tool"); t.setObjectName("title")
        s = QLabel("Memory inspection and program control. Use Board Setup and Connect Memory above when needed.")
        s.setObjectName("subtitle")
        tcol.addWidget(t); tcol.addWidget(s); head.addLayout(tcol); head.addStretch(1)
        V.addLayout(head)
        div = QFrame(); div.setObjectName("divider"); div.setFixedHeight(1); V.addWidget(div)

        self._build_connection_dialog()
        self._build_board_setup_dialog()

        # ── Memory bundle: Read toolbar + grid + Write toolbar (full-screen toggle) ──
        self._mem_fs_win = None
        self.mem_bundle = QFrame(); self.mem_bundle.setObjectName("membundle")
        mb = QVBoxLayout(self.mem_bundle); mb.setContentsMargins(0, 0, 0, 0); mb.setSpacing(8)

        # Read toolbar — sits directly above the grid
        c2, l2 = self._card()
        l2.addWidget(QLabel("Start")); self.start = QLineEdit("0x000"); self.start.setFixedWidth(70); l2.addWidget(self.start)
        l2.addWidget(QLabel("Bytes")); self.count = QLineEdit(str(MEM_BYTES)); self.count.setFixedWidth(54); l2.addWidget(self.count)
        l2.addWidget(self._btn("Read", QStyle.SP_ArrowDown, None, self.do_read))
        l2.addSpacing(10)
        # Hex / Dec display format for the byte cells
        # NB: styling QCheckBox/QRadioButton ::indicator can make their sizeHint
        # ignore the text on macOS, so set explicit minimum widths to stop the
        # next control overlapping the label.
        self.fmt_hex = QRadioButton("Hex"); self.fmt_dec = QRadioButton("Dec"); self.fmt_hex.setChecked(True)
        self.fmt_hex.setMinimumWidth(52); self.fmt_dec.setMinimumWidth(52)
        _fg = QButtonGroup(self); _fg.addButton(self.fmt_hex); _fg.addButton(self.fmt_dec)
        self.fmt_hex.toggled.connect(self._fmt_changed)
        l2.addWidget(self.fmt_hex); l2.addWidget(self.fmt_dec)
        l2.addSpacing(10)
        self.heat = QCheckBox("Heatmap"); self.heat.setChecked(True)
        self.heat.setMinimumWidth(98)
        self.heat.stateChanged.connect(self.do_read); l2.addWidget(self.heat)
        self.auto = QCheckBox("Poll")          # enabled by default at the end of _build
        self.auto.setMinimumWidth(62)
        self.auto.setToolTip("Re-read the range continuously (live view)")
        self.auto.stateChanged.connect(self._toggle_auto); l2.addWidget(self.auto)
        self.interval = QLineEdit("500"); self.interval.setFixedWidth(50)
        self.interval.setToolTip("Poll interval (ms)"); l2.addWidget(self.interval); l2.addWidget(QLabel("ms"))
        l2.addStretch(1)
        bm = self._btn("A−", None, "mini", lambda: self._font_step(-1)); bm.setToolTip("Smaller grid font")
        bp = self._btn("A+", None, "mini", lambda: self._font_step(+1)); bp.setToolTip("Larger grid font")
        l2.addWidget(bm); l2.addWidget(bp); l2.addSpacing(8)
        self.btn_zoom = self._btn("⛶", None, "ghost", self._toggle_mem_fullscreen)
        self.btn_zoom.setToolTip("Full screen (Esc to exit)")
        l2.addWidget(self.btn_zoom)
        mb.addWidget(c2)

        cols = ["Addr"] + [f"{i:X}" for i in range(16)] + ["ASCII"]
        self.tbl = QTableWidget(0, len(cols)); self.tbl.setHorizontalHeaderLabels(cols)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.cellDoubleClicked.connect(self._poke)
        hdr = self.tbl.horizontalHeader()
        hdr.setMinimumSectionSize(16)                                  # allow narrow cells
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)      # Addr
        for i in range(1, 17): hdr.setSectionResizeMode(i, QHeaderView.Fixed)  # compact bytes
        hdr.setSectionResizeMode(17, QHeaderView.Interactive)         # ASCII: drag to resize
        hdr.setStretchLastSection(False)
        self.tbl.setColumnWidth(17, 210)
        self.tbl.setItemDelegate(_CellDelegate(self.tbl))   # so heat-map / tints paint
        self._apply_font(); mb.addWidget(self.tbl, 1)

        # Write toolbar — sits directly below the grid
        c3, l3 = self._card()
        l3.addWidget(QLabel("Fill")); self.w_addr = QLineEdit("0x000"); self.w_addr.setFixedWidth(70); l3.addWidget(self.w_addr)
        l3.addWidget(QLabel("Bytes")); self.w_n = QLineEdit("32"); self.w_n.setFixedWidth(48); l3.addWidget(self.w_n)
        l3.addWidget(QLabel("=")); self.w_val = QLineEdit("0x0000"); self.w_val.setFixedWidth(70); l3.addWidget(self.w_val)
        self.rand = QCheckBox("random"); self.rand.setMinimumWidth(80); l3.addWidget(self.rand)
        l3.addSpacing(10)
        l3.addWidget(self._btn("Write", QStyle.SP_DialogSaveButton, None, self.do_fill))
        l3.addStretch(1)
        mb.addWidget(c3)

        V.addWidget(self.mem_bundle, 1)

        c4, l4 = self._card()
        l4.addWidget(QLabel("Program (.tara)")); self.prog = QLineEdit(); l4.addWidget(self.prog, 1)
        l4.addWidget(self._btn("Browse", QStyle.SP_DirOpenIcon, "ghost", self._browse))
        l4.addWidget(self._btn("Load && Run", QStyle.SP_MediaPlay, "run", self.load_run))
        V.addWidget(c4)

        # references the full-screen toggle needs to pop the bundle out and back
        self._root_layout = V
        self._after_bundle = c4

        self.timer = QTimer(self); self.timer.timeout.connect(self.do_read)
        last = self.settings.value("last_prog", "")
        if last and os.path.exists(last): self.prog.setText(last)

        # Poll on by default (now that self.timer / self.interval exist). do_read
        # returns early until connected, so this is harmless before Connect.
        self.auto.setChecked(True)

    # ---- target connection dialog ----
    def _build_connection_dialog(self):
        """Build the menu-launched target and serial connection controls."""
        dlg = QDialog(self)
        dlg.setObjectName("fpgaRoot")
        dlg.setWindowTitle("Connect Memory")
        dlg.setMinimumSize(660, 340)
        dlg.resize(720, 360)
        dlg.setStyleSheet(STYLE)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        title = QLabel("Connect Memory")
        title.setObjectName("title")
        outer.addWidget(title)
        intro = QLabel(
            "Choose whether the memory tools operate on the physical FPGA or the "
            "local simulator. The connection remains active after this window is closed.")
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        card = QFrame(); card.setObjectName("card"); _shadow(card)
        controls = QVBoxLayout(card)
        controls.setContentsMargins(16, 14, 16, 14)
        controls.setSpacing(10)

        target_row = QHBoxLayout(); target_row.setSpacing(10)
        target_row.addWidget(QLabel("Memory target"))
        self.mode_fpga = QRadioButton("FPGA USB")
        self.mode_sim = QRadioButton("Simulator Memory")
        self.mode_fpga.setMinimumWidth(88)
        self.mode_sim.setMinimumWidth(150)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_fpga)
        self.mode_group.addButton(self.mode_sim)
        self.mode_fpga.setChecked(True)
        if not _HAVE_SERIAL:
            self.mode_fpga.setEnabled(False)
            self.mode_sim.setChecked(True)
        self.mode_fpga.toggled.connect(self._connection_mode_changed)
        target_row.addWidget(self.mode_fpga)
        target_row.addWidget(self.mode_sim)
        target_row.addStretch(1)
        controls.addLayout(target_row)

        div = QFrame(); div.setObjectName("divider"); div.setFixedHeight(1)
        controls.addWidget(div)

        port_row = QHBoxLayout(); port_row.setSpacing(8)
        port_row.addWidget(QLabel("Serial port"))
        self.port = QComboBox(); self.port.setMinimumWidth(260); port_row.addWidget(self.port, 1)
        self.btn_rescan = self._btn("Rescan", QStyle.SP_BrowserReload, "ghost", self._refresh_ports)
        port_row.addWidget(self.btn_rescan)
        controls.addLayout(port_row)

        action_row = QHBoxLayout(); action_row.setSpacing(8)
        action_row.addWidget(QLabel("Status"))
        self.status = QLabel("disconnected")
        self.status.setStyleSheet(f"color:{DIM};font-weight:700;")
        action_row.addWidget(self.status)
        action_row.addStretch(1)
        self.btn_conn = self._btn("Connect", QStyle.SP_DialogYesButton, None, self._connect)
        action_row.addWidget(self.btn_conn)
        controls.addLayout(action_row)
        outer.addWidget(card)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)

        self.connection_dialog = dlg
        self._connection_mode_changed(emit=False)

    def _show_connection_dialog(self):
        """Open the reusable modeless target connection dialog."""
        if _HAVE_SERIAL and not self._using_simulator():
            self._refresh_ports()
        self.connection_dialog.show()
        self.connection_dialog.raise_()
        self.connection_dialog.activateWindow()

    # ---- one-time board setup: configure the FPGA without Vivado ----
    def _build_board_setup_dialog(self):
        """Build the menu-launched dialog for detection and bitstream programming."""
        dlg = QDialog(self)
        dlg.setObjectName("fpgaRoot")
        dlg.setWindowTitle("FPGA Board Setup")
        dlg.setMinimumSize(760, 390)
        dlg.resize(820, 410)
        dlg.setStyleSheet(STYLE)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        title = QLabel("FPGA Board Setup")
        title.setObjectName("title")
        outer.addWidget(title)
        intro = QLabel(
            "Use these controls when changing hardware or preparing a board after power-up. "
            "Normal memory inspection and TARA program loading stay in the main window.")
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        card = QFrame(); card.setObjectName("card"); _shadow(card)
        setup = QVBoxLayout(card)
        setup.setContentsMargins(16, 14, 16, 14)
        setup.setSpacing(9)

        setup.addWidget(QLabel("TARA hardware bitstream"))
        path_row = QHBoxLayout(); path_row.setSpacing(8)
        self.bit_path = QLineEdit()
        self.bit_path.setPlaceholderText("tara_top.bit — the synthesised TARA processor")
        self.bit_path.textChanged.connect(self._bit_refresh_info)
        path_row.addWidget(self.bit_path, 1)
        path_row.addWidget(self._btn("Browse…", QStyle.SP_DirOpenIcon, "ghost", self._bit_browse))
        setup.addLayout(path_row)

        self.bit_info = QLabel()
        self.bit_info.setObjectName("subtitle")
        self.bit_info.setWordWrap(True)
        setup.addWidget(self.bit_info)

        div = QFrame(); div.setObjectName("divider"); div.setFixedHeight(1)
        setup.addWidget(div)

        target_row = QHBoxLayout(); target_row.setSpacing(8)
        target_row.addWidget(QLabel("Program destination"))
        self.bit_target = QComboBox(); self.bit_target.setMinimumWidth(200)
        self.bit_target.addItem("FPGA SRAM (volatile)")
        self.bit_target.addItem("SPI flash (persistent)")
        self.bit_target.setToolTip(
            "SRAM: configures the fabric now, ~2 s, cleared by a power cycle.\n"
            "SPI flash: ~1 min, the board then boots TARA by itself every cold start.")
        self.bit_target.currentIndexChanged.connect(self._bit_refresh_info)
        target_row.addWidget(self.bit_target)
        target_row.addStretch(1)
        self.btn_detect = self._btn("Detect", QStyle.SP_ComputerIcon, "ghost", self._bit_detect)
        self.btn_detect.setToolTip("Scan the JTAG chain to check the board is visible")
        target_row.addWidget(self.btn_detect)
        self.btn_program = self._btn("Program FPGA", QStyle.SP_DialogApplyButton, "run", self._program_fpga)
        target_row.addWidget(self.btn_program)
        setup.addLayout(target_row)
        outer.addWidget(card)

        note = QLabel(
            "Tip: use SRAM for normal development. Use SPI flash only when the design "
            "should survive power cycles; set the Basys 3 JP1 mode jumper to SPI/QSPI.")
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        outer.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)

        self.bit_path.setText(bs.default_bitstream(self.settings))
        self._bit_refresh_info()
        self.board_setup_dialog = dlg

    def _show_board_setup(self):
        """Open the reusable modeless setup dialog from the FPGA menu."""
        self._bit_refresh_info()
        self.board_setup_dialog.show()
        self.board_setup_dialog.raise_()
        self.board_setup_dialog.activateWindow()

    def _bit_refresh_info(self):
        """Keep the sub-line honest: what will be sent, and whether we can send it."""
        path = self.bit_path.text().strip()
        if not path:
            exe = bs.find_programmer(self.settings)
            self.bit_info.setText(
                "Choose the .bit built by Vivado, then Program to bring the CPU up after a cold boot."
                if exe else
                "Choose a .bit — programming needs openFPGALoader (click Program to set it up).")
            return
        try:
            info = bs.parse_bit_file(path)
        except bs.BitstreamError as e:
            self.bit_info.setText(f"⚠ {e}")
            return
        text = bs.describe_bitstream(info)
        if not bs.part_matches_board(info):
            text += f"   ⚠ built for {info['part']}, not the Basys 3's {bs.EXPECTED_PART}"
        self.bit_info.setText(text)

    def _bit_browse(self):
        start = os.path.dirname(self.bit_path.text().strip()) or os.path.expanduser("~")
        p, _ = QFileDialog.getOpenFileName(self, "Choose a bitstream", start,
                                           "FPGA bitstream (*.bit *.bin);;All files (*)")
        if p:
            self.bit_path.setText(p)
            self.settings.setValue(bs.SETTING_BIT, p)

    def _programmer(self):
        """Resolve openFPGALoader, offering the one-time setup if it is missing."""
        exe = bs.find_programmer(self.settings)
        if exe:
            return exe
        dlg = bs.SetupDialog(self, STYLE)
        dlg.exec_()
        return dlg.exe

    def _bit_detect(self):
        exe = self._programmer()
        if not exe:
            self._status("openFPGALoader not installed", ok=False); return
        self.usage_event.emit("fpga_detect", None)
        with self._board_released():
            dlg = bs.RunDialog(
                self, "Detect FPGA", bs.detect_command(exe),
                blurb="Scanning the JTAG chain for the Basys 3.",
                style=STYLE, success_note="board detected")
            dlg.exec_()
        self._status("board detected on JTAG" if dlg.ok else "board not detected — check USB / power switch",
                     ok=bool(dlg.ok))

    def _program_fpga(self):
        path = self.bit_path.text().strip()
        if not path:
            self._status("choose a .bit file", ok=False); return
        try:
            info = bs.parse_bit_file(path)
        except bs.BitstreamError as e:
            self._status(f"bitstream error: {e}", ok=False)
            QMessageBox.warning(self, "Bitstream error", str(e)); return

        if not bs.part_matches_board(info):
            if QMessageBox.warning(
                self, "Wrong device?",
                f"This bitstream was built for <b>{info['part']}</b>, but the Basys 3 "
                f"carries an <b>xc{bs.EXPECTED_PART}</b>. Configuration will most likely fail."
                "<br><br>Send it anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return

        flash = self.bit_target.currentIndex() == 1
        if flash and QMessageBox.question(
            self, "Write SPI flash?",
            "Writing the Basys 3's flash takes about a minute and the board will then "
            "boot this design on every power-up.<br><br>For a one-off demo run, "
            "<b>FPGA SRAM</b> is faster and leaves the flash untouched.<br><br>Write flash?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return

        exe = self._programmer()
        if not exe:
            self._status("openFPGALoader not installed", ok=False); return
        self.settings.setValue(bs.SETTING_BIT, path)

        target = "SPI flash" if flash else "FPGA SRAM"
        self.usage_event.emit("fpga_program_started", None)
        with self._board_released():
            dlg = bs.RunDialog(
                self, f"Programming the Basys 3 — {target}",
                bs.program_command(exe, path, flash=flash),
                blurb=f"Sending <b>{os.path.basename(path)}</b> to {target} over JTAG. "
                      "Leave the board powered and connected.",
                style=STYLE,
                success_note=("flash written — press PROG or power-cycle the board to boot it"
                              if flash else "FPGA configured — the TARA processor is running"))
            dlg.exec_()

        if not dlg.ok:
            self.usage_event.emit("fpga_program_failed", None)
            self._status("programming failed — see the log", ok=False); return
        self.usage_event.emit("fpga_program_succeeded", None)
        if flash:
            self._status("SPI flash written — press PROG (or power-cycle) to boot TARA")
            QMessageBox.information(
                self, "Flash written",
                "The bitstream is in the board's flash. Press the <b>PROG</b> button "
                "(or power-cycle the Basys 3) to load it, then Connect.")
            return

        # SRAM: the CPU is alive now — get the memory monitor talking to it again.
        name = os.path.basename(path)
        if self._using_simulator():
            self._status(f"FPGA configured with {name} — open Connect Memory and choose FPGA USB")
            return
        self._status(f"FPGA configured with {name}")
        self._refresh_ports()
        QTimer.singleShot(800, self._reconnect_after_program)

    def _reconnect_after_program(self):
        """Re-open the UART once the freshly configured design has come up."""
        if self._using_simulator() or self.link.is_open or not self.port.currentText():
            return
        self._connect()

    def _board_released(self):
        """Context manager: drop the UART and pause polling around a JTAG operation.

        The programmer claims the FT2232's JTAG channel while our serial port
        sits on the second channel; closing ours keeps the two out of each
        other's way and avoids a flood of read errors while the fabric resets.
        The buttons are disabled for the duration so a second run cannot start
        on top of the first.
        """
        panel = self

        class _Released:
            def __enter__(self):
                self.was_connected = panel.serial_link.is_open
                self.was_polling = panel.timer.isActive()
                if self.was_polling:
                    panel.timer.stop()
                if self.was_connected:
                    panel.serial_link.close()
                    panel.btn_conn.setText("Connect")
                    panel.btn_conn.setIcon(panel._ic(QStyle.SP_DialogYesButton))
                    panel._conn_style(False)
                    panel.connection_changed.emit(False)
                panel.btn_program.setEnabled(False)
                panel.btn_detect.setEnabled(False)
                return self.was_connected

            def __exit__(self, *exc):
                panel.btn_program.setEnabled(True)
                panel.btn_detect.setEnabled(True)
                if self.was_polling:
                    panel._toggle_auto()
                return False

        return _Released()

    # ---- full-screen memory panel ----
    def _toggle_mem_fullscreen(self):
        """Pop the Read / memory-grid / Write bundle out into a full-screen window,
        or dock it back into the tab. The zoom button (and Esc) toggle it back."""
        if self._mem_fs_win is None:
            # pop out → full screen
            self._root_layout.removeWidget(self.mem_bundle)
            win = QWidget()
            win.setObjectName("fpgaRoot")                 # reuse the panel background
            win.setWindowTitle("TARA Studio — FPGA Memory (full screen)")
            win.setStyleSheet(STYLE)
            wl = QVBoxLayout(win); wl.setContentsMargins(18, 16, 18, 16)
            wl.addWidget(self.mem_bundle)
            QShortcut(QKeySequence(Qt.Key_Escape), win, activated=self._toggle_mem_fullscreen)
            self._mem_fs_win = win
            self.btn_zoom.setText("🗗  Exit full screen")
            self._set_memory_columns_expanded(True)
            win.showFullScreen()
        else:
            # dock back into the tab, just before the program-load card
            win = self._mem_fs_win
            win.layout().removeWidget(self.mem_bundle)
            idx = self._root_layout.indexOf(self._after_bundle)
            self._root_layout.insertWidget(idx, self.mem_bundle, 1)
            self.btn_zoom.setText("⛶")
            self._mem_fs_win = None
            self._set_memory_columns_expanded(False)
            win.close(); win.deleteLater()

    # ---- font ----
    def _set_memory_columns_expanded(self, expanded):
        """Let byte cells share the extra width available in full-screen mode."""
        hdr = self.tbl.horizontalHeader()
        hdr.setMinimumSectionSize(max(36, self.cell_pt + 18) if expanded else 16)
        mode = QHeaderView.Stretch if expanded else QHeaderView.Fixed
        for i in range(1, 17):
            hdr.setSectionResizeMode(i, mode)
        if not expanded:
            self._apply_font()

    def _apply_font(self):
        f = QFont("Menlo"); f.setStyleHint(QFont.Monospace); f.setPointSize(self.cell_pt)
        self.tbl.setFont(f)
        self.tbl.verticalHeader().setDefaultSectionSize(int(self.cell_pt*1.9))
        hf = QFont(); hf.setPointSize(max(11, self.cell_pt-3)); hf.setBold(True)
        self.tbl.horizontalHeader().setFont(hf)
        # compact byte-cell width (same font); a bit wider for 3-digit decimals
        wide = hasattr(self, "fmt_dec") and self.fmt_dec.isChecked()
        bw = max(24, self.cell_pt + (20 if wide else 12))
        for i in range(1, 17):
            self.tbl.setColumnWidth(i, bw)
    def _font_step(self, d): self.cell_pt = max(9, min(40, self.cell_pt+d)); self._apply_font()
    def _fmt_changed(self):  self._apply_font(); self.do_read()

    # ---- ports / connect ----
    def _using_simulator(self):
        return hasattr(self, "mode_sim") and self.mode_sim.isChecked()

    def is_virtual_connection(self):
        return self._using_simulator() and self.link.is_open

    def _connection_label(self):
        return "Simulator Memory" if self._using_simulator() else self.port.currentText()

    def _select_link(self):
        self.link = self.sim_link if self._using_simulator() else self.serial_link

    def _connection_mode_changed(self, _checked=None, emit=True):
        old_link = self.link
        if old_link.is_open:
            old_link.close()
            if emit:
                self.connection_changed.emit(False)
        self._select_link()
        use_sim = self._using_simulator()
        self.port.setEnabled(not use_sim and _HAVE_SERIAL)
        self.btn_rescan.setEnabled(not use_sim and _HAVE_SERIAL)
        self.btn_conn.setText("Connect")
        self.btn_conn.setIcon(self._ic(QStyle.SP_DialogYesButton))
        self._conn_style(False)
        if use_sim:
            self._status("simulator memory selected")
        else:
            self._status("disconnected", ok=False)

    def _refresh_ports(self):
        if not _HAVE_SERIAL or self._using_simulator(): return
        preferred = (self.port.currentText()
                     or self.settings.value("last_serial_port", "") or "")
        ports = list(list_ports.comports())

        # Put the Basys 3 UART ahead of unrelated system ports.  Digilent's
        # FT2232 exposes two macOS endpoints; channel B (suffix 1) is UART while
        # channel A (suffix 0) is used for JTAG.
        def port_rank(p):
            desc = f"{getattr(p, 'description', '')} {getattr(p, 'manufacturer', '')}".lower()
            digilent = "digilent" in desc or (
                getattr(p, "vid", None) == 0x0403 and getattr(p, "pid", None) == 0x6010)
            uart_hint = digilent and str(p.device).endswith("1")
            return (0 if uart_hint else 1 if digilent else 2, str(p.device))

        ports.sort(key=port_rank)
        self.port.clear()
        self.port.addItems([p.device for p in ports])
        if preferred:
            i = self.port.findText(preferred)
            if i >= 0: self.port.setCurrentIndex(i)
    def _status(self, txt, ok=True):
        self.status.setText(txt); self.status.setStyleSheet(f"color:{OKC if ok else DANGER};font-weight:700;")
    def _conn_style(self, connected):
        self.btn_conn.setObjectName("danger" if connected else "")
        self.btn_conn.style().unpolish(self.btn_conn); self.btn_conn.style().polish(self.btn_conn)
    def _connect(self):
        if self.link.is_open:
            self.link.close(); self.btn_conn.setText("Connect")
            self.btn_conn.setIcon(self._ic(QStyle.SP_DialogYesButton)); self._conn_style(False)
            self._status("simulator memory selected" if self._using_simulator() else "disconnected",
                         ok=self._using_simulator())
            self.connection_changed.emit(False); return
        if self._using_simulator():
            try:
                self.link.open()
                if not self.link.ping():
                    self.link.close()
                    self._status("simulator CPU unavailable", ok=False)
                    self.connection_changed.emit(False); return
                self.btn_conn.setText("Disconnect")
                self.btn_conn.setIcon(self._ic(QStyle.SP_DialogCloseButton))
                self._conn_style(True); self._status("connected: simulator memory")
                self.usage_event.emit("simulator_connect", None)
                self.connection_changed.emit(True); self.do_read()
            except Exception as e:
                self._status(f"connect failed: {e}", ok=False); self.connection_changed.emit(False)
            return
        if not _HAVE_SERIAL:
            self._status("pyserial not installed", ok=False); return
        if not self.port.currentText():
            self._status("no serial ports found", ok=False); return
        try:
            selected_port = self.port.currentText()
            self.link.open(selected_port)
            if not self.link.ping():
                self.link.close()
                self._status("no response (check baud / bitstream / UART port)", ok=False)
                self.connection_changed.emit(False); return
            self.settings.setValue("last_serial_port", selected_port)
            self.btn_conn.setText("Disconnect"); self.btn_conn.setIcon(self._ic(QStyle.SP_DialogCloseButton))
            self._conn_style(True); self._status(f"connected: {selected_port}")
            self.usage_event.emit("fpga_connect", None)
            self.connection_changed.emit(True); self.do_read()
        except Exception as e:
            self._status(f"open failed: {e}", ok=False); self.connection_changed.emit(False)

    @staticmethod
    def _hex(s, d=0):
        s = s.strip()
        try: return int(s, 0) if s.lower().startswith(("0x", "0b")) else int(s, 16)
        except ValueError: return d
    @staticmethod
    def _int(s, d=0):
        try: return int(s.strip(), 0)
        except ValueError: return d

    # ---- read / display ----
    def do_read(self):
        if not self.link.is_open:
            self._status("not connected", ok=False); return
        addr = clamp_even_addr(self._hex(self.start.text()))
        nbytes = max(2, min(self._int(self.count.text(), MEM_BYTES), MEM_BYTES - addr))
        n = (nbytes + 1) // 2
        try: words = self.link.read_words(addr, n)
        except Exception as e: self._status(f"read error: {e}", ok=False); return
        data = []
        for w in words: data += [(w >> 8) & 0xFF, w & 0xFF]
        data = data[:nbytes]
        heat = self.heat.isChecked(); hexfmt = self.fmt_hex.isChecked()
        rows = (len(data)+15)//16; self.tbl.setRowCount(rows)
        for r in range(rows):
            base = addr + r*16
            ai = QTableWidgetItem(f"0x{base:03X}"); ai.setForeground(QBrush(QColor(ACCENT)))
            ai.setTextAlignment(Qt.AlignCenter); self.tbl.setItem(r, 0, ai)
            asc = ""; row_fb = (FB_BASE <= base < MEM_BYTES)
            for i in range(16):
                k = r*16+i; it = QTableWidgetItem(""); it.setTextAlignment(Qt.AlignCenter)
                if k < len(data):
                    b = data[k]; ba = addr+k; it.setText(f"{b:02X}" if hexfmt else f"{b:d}")
                    if heat:
                        bg = heat_color(b); it.setBackground(QBrush(bg)); it.setForeground(QBrush(contrast_color(bg)))
                    elif self.prev.get(ba) not in (None, b): it.setBackground(QBrush(QColor(CHANGED)))
                    elif row_fb: it.setBackground(QBrush(QColor(GOLD)))
                    self.prev[ba] = b
                    asc += chr(b) if 32 <= b < 127 else "."
                self.tbl.setItem(r, i+1, it)
            self.tbl.setItem(r, 17, QTableWidgetItem(asc))
        self._status(f"read {len(data)} bytes @ 0x{addr:03X}" + ("  ·  heatmap" if heat else ""))

    # ---- writes ----
    def do_fill(self):
        if not self.link.is_open: self._status("not connected", ok=False); return
        addr = clamp_even_addr(self._hex(self.w_addr.text()))
        nbytes = max(2, min(self._int(self.w_n.text(), 2), MEM_BYTES - addr)); n = (nbytes + 1) // 2
        words = ([random.randint(0, 0xFFFF) for _ in range(n)] if self.rand.isChecked()
                 else [self._hex(self.w_val.text()) & 0xFFFF]*n)
        try: ok = self.link.write_words(addr, words)
        except Exception as e: self._status(f"write error: {e}", ok=False); return
        self._status(f"wrote {n*2} bytes @ 0x{addr:03X}" + ("" if ok else " (no ack)"), ok=ok); self.do_read()

    def _poke(self, row, col):
        if not (1 <= col <= 16) or not self.link.is_open: return
        base = self._hex(self.tbl.item(row, 0).text()); ba = base + (col-1)
        cur = self.tbl.item(row, col).text()
        if not cur: return
        new, okp = QInputDialog.getText(self, "Poke byte", f"New byte for 0x{ba:03X} (hex):", text=cur)
        if not okp: return
        try:
            nb = int(new, 16) & 0xFF; wa = ba & ~1; w = self.link.read_words(wa, 1)[0]
            w = (w & 0xFF00) | nb if (ba & 1) else (nb << 8) | (w & 0x00FF)
            self.link.write_words(wa, [w]); self.do_read(); self._status(f"poked 0x{ba:03X} = {nb:02X}")
        except Exception as e:
            self._status(f"poke failed: {e}", ok=False)

    # ---- assemble + load + run ----
    def _browse(self):
        start = self.settings.value("last_dir", "") or os.path.dirname(self.prog.text()) or PROGS_DIR
        p, _ = QFileDialog.getOpenFileName(self, "Choose a TARA program", start,
                                           "TARA assembly (*.tara);;All files (*)")
        if p:
            self.prog.setText(p)
            self.settings.setValue("last_dir", os.path.dirname(p)); self.settings.setValue("last_prog", p)
    def load_run(self):
        if not self.link.is_open: self._status("not connected", ok=False); return
        path = self.prog.text().strip()
        if not path: self._status("choose a .tara file", ok=False); return
        self.settings.setValue("last_dir", os.path.dirname(path)); self.settings.setValue("last_prog", path)
        assembly_started = False
        usage_context = bundled_example(path, "assembly")
        try:
            with open(path, encoding="utf-8") as f:
                source_text = f.read()
            self.usage_event.emit("assembly_started", usage_context)
            assembly_started = True
            words_raw, listing, errors, labels = assemble(source_text)
            if errors:
                raise ValueError("; ".join(str(e) for e in errors[:5]))
            words = [w for _a, w in words_raw]
        except Exception as e:
            if assembly_started:
                self.usage_event.emit("assembly_failed", usage_context)
            self._status(f"assemble error: {e}", ok=False); QMessageBox.warning(self, "Assemble error", str(e)); return
        if not words:
            self.usage_event.emit("assembly_failed", usage_context)
            self._status("empty program", ok=False); return
        self.usage_event.emit("assembly_succeeded", usage_context)
        self.load_words_and_run(words, source="file", source_text=source_text, listing=listing, usage_context=usage_context)

    def load_words_and_run(self, words, source="Simulator", source_text=None, listing=None, usage_context=None):
        """Hold the CPU, stream the machine words to 0x000, release it to run.
        Called both by the file-based Load && Run and by the Simulator tab."""
        if not self.link.is_open:
            self._status("not connected", ok=False); return False
        words = list(words)
        usage_context = validate_example(usage_context)
        if self._using_simulator() and self._on_simulator_program_loaded:
            ok = bool(self._on_simulator_program_loaded(
                words,
                source_text=source_text,
                listing=listing,
                source_label=source,
                usage_context=usage_context,
            ))
            self.do_read()
            tag = "" if source == "file" else f" from {source}"
            self._status(f"loaded {len(words)} instructions{tag} @0x000 & running in simulator",
                         ok=ok)
            if ok:
                self.usage_event.emit("simulator_run", usage_context)
            return ok
        try:
            self.link.hold(); ok = self.link.write_words(0x000, words); self.link.go()
        except Exception as e:
            self._status(f"load error: {e}", ok=False); return False
        self.do_read()
        tag = "" if source == "file" else f" from {source}"
        self._status(f"loaded {len(words)} instructions{tag} @0x000 & running"
                     + ("" if ok else " (write: no ack)"), ok=ok)
        if ok:
            self.usage_event.emit("simulator_run" if self._using_simulator() else "fpga_run", usage_context)
        return ok

    def _toggle_auto(self):
        if self.auto.isChecked(): self.timer.start(max(100, self._int(self.interval.text(), 500)))
        else: self.timer.stop()

    # ---- help ----
    def _show_help(self):
        html = f"""
        <h2 style='color:{ACCENT}'>FPGA Memory Tool</h2>
        <p style='color:{DIM}'>This tab connects either to the TARA processor running on a
        real FPGA over USB-UART, or to the simulator's own memory through <b>Simulator
        Memory</b>. Both targets use the same byte grid, write tools, polling and
        program-load controls.</p>
        <h3 style='color:{ACCENT2}'>Bitstream — after a cold boot</h3>
        <p>A freshly powered Basys 3 has an empty fabric: there is no TARA processor yet,
        so <b>Connect</b> will not find one. Open <b>Board Setup</b>, browse to the Vivado
        <code>.bit</code> and press <b>Program FPGA</b> to configure the board over JTAG —
        <i>no Vivado needed</i>. <b>Program destination</b> selects where it is loaded:</p>
        <ul>
        <li><b>FPGA SRAM (volatile)</b> — ~2 s, runs immediately, gone at the next power
        cycle. This is the normal demo path; the tool then re-opens the UART for you.</li>
        <li><b>SPI flash (persistent)</b> — ~1 min, after which the board boots TARA on
        its own every time it is switched on. Press <b>PROG</b> or power-cycle to start it.</li>
        </ul>
        <p>Programming is done by <b>openFPGALoader</b>; the first time you use it the tool
        offers to install it (<code>{bs.INSTALL_CMD}</code>) or to locate an existing copy.
        <b>Detect</b> scans the JTAG chain if you just want to check the board is seen.</p>
        <h3 style='color:{ACCENT2}'>Connect</h3>
        <p>Open <b>Connect Memory</b>. Choose <b>FPGA USB</b> for the board, pick the serial port and press
        <b>Connect</b> (the tool pings the FPGA). The FTDI bridge exposes two ports — use
        the <b>UART</b> one, not JTAG. Choose <b>Simulator Memory</b> when no board is
        available or when you want to debug the memory-tool workflow against the local CPU.</p>
        <h3 style='color:{ACCENT2}'>Read &amp; visualize</h3>
        <p>Enter a start address (hex) and a byte count, then <b>Read</b>. Memory shows as a
        byte grid (Addr | 0..F | ASCII). <b>Auto</b> re-reads live; changed bytes are tinted
        green and the framebuffer (0x600+) gold; <b>Heatmap</b> colours every byte by value.
        <b>A−/A+</b> resize the grid font.</p>
        <h3 style='color:{ACCENT2}'>Write &amp; run</h3>
        <p><b>Fill</b> writes that many bytes with a value or random data; double-click a cell
        to poke one byte. <b>Browse</b> a <code>.tara</code> file and <b>Load &amp;&amp; Run</b>: it
        assembles, holds the CPU, streams the code to 0x000, and starts it — no
        re-synthesis. Pause the CPU (sw[0]=0) before manual pokes; Load &amp;&amp; Run resets
        the CPU around its write for you.</p>
        """
        dlg = QDialog(self); dlg.setWindowTitle("Help — FPGA Memory Tool"); dlg.resize(620, 560)
        v = QVBoxLayout(dlg); tb = QTextBrowser(); tb.setHtml(html)
        tb.setStyleSheet(f"background:{PANEL};border:1px solid {BORDER};border-radius:8px;font-size:15px;padding:8px;")
        v.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.Close); bb.rejected.connect(dlg.reject); bb.accepted.connect(dlg.accept)
        v.addWidget(bb); dlg.exec_()
