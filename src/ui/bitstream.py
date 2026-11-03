# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""
Bitstream programming for the Basys 3 — without Vivado.

After a cold boot the Artix-7 fabric is blank, so the TARA processor (and with
it the UART memory monitor the FPGA tab talks to) does not exist yet. This
module configures the board straight from a Vivado-generated ``.bit`` file so a
laptop with no Xilinx toolchain installed can still bring the CPU up.

The actual JTAG work is done by **openFPGALoader**, an external tool that knows
the Basys 3 natively (``brew install openfpgaloader``):

    SRAM  (volatile)   openFPGALoader -b basys3 tara_top.bit
    Flash (persistent) openFPGALoader -b basys3 -f tara_top.bit
    Chain scan         openFPGALoader -b basys3 --detect

What lives here:
  * ``parse_bit_file``  — read the Vivado .bit header (design, part, timestamp)
    so the panel can show what is about to be loaded and refuse a bitstream
    built for the wrong device.
  * ``find_programmer`` — locate openFPGALoader (PATH, Homebrew, MacPorts, an
    explicit override remembered in QSettings, or $OPENFPGALOADER).
  * ``RunDialog``       — run one of those commands with live output, a progress
    bar driven by openFPGALoader's own percentage, and a Cancel button.
  * ``SetupDialog``     — shown when the tool is missing: explains the one-time
    install and can run Homebrew for the user or locate an existing binary.
"""
import os
import re
import shutil
import struct

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QProgressBar, QFileDialog, QApplication, QMessageBox)
from PyQt5.QtCore import Qt, QProcess, QSettings
from PyQt5.QtGui import QFont, QTextCursor

# ── Basys 3 = Digilent board carrying an Artix-7 XC7A35T-1CPG236C ──
BOARD = "basys3"
EXPECTED_PART = "7a35t"
SYNC_WORD = b"\xaa\x99\x55\x66"          # Xilinx configuration sync pattern

# The Homebrew formula is lower-case; the binary it installs is camel-case.
PROGRAMMER_NAMES = ("openFPGALoader", "openfpgaloader")
SEARCH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin",
               "/opt/homebrew/opt/openfpgaloader/bin",
               "/usr/local/opt/openfpgaloader/bin")
BREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
INSTALL_CMD = "brew install openfpgaloader"
PROGRAMMER_URL = "https://trabucayre.github.io/openFPGALoader/"

SETTINGS_ORG, SETTINGS_APP = "TARA-IITM", "MemoryMonitor"
SETTING_EXE = "openfpgaloader_path"
SETTING_BIT = "last_bitstream"

_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


class BitstreamError(ValueError):
    """Raised when a file is not a usable bitstream."""


# ─────────────────────────── .bit header parsing ───────────────────────────

def parse_bit_file(path):
    """Decode a Vivado ``.bit`` header.

    Layout: a 2-byte length + that many filler bytes, the marker 0x0001, then
    tagged fields ``a`` design, ``b`` part, ``c`` date, ``d`` time, and finally
    ``e`` + a 4-byte length introducing the raw configuration payload.

    Returns a dict with design/part/date/time/payload/size/raw. A headerless
    ``.bin`` is accepted with ``part=None`` so the caller can still program it,
    just without the device cross-check.
    """
    if not path:
        raise BitstreamError("no bitstream selected")
    if not os.path.isfile(path):
        raise BitstreamError("file not found")
    size = os.path.getsize(path)
    if size < 64:
        raise BitstreamError("file is too small to be a bitstream")

    with open(path, "rb") as f:
        head = f.read(4096)

    # Every 7-series configuration stream contains the sync word 0xAA995566,
    # right after the bus-width preamble. Checking it here means a mistyped
    # path or a stray file is caught in the panel rather than by a puzzling
    # openFPGALoader error with the board already half-touched.
    if SYNC_WORD not in head:
        raise BitstreamError("not an FPGA bitstream (Xilinx sync word missing)")

    info = {"path": path, "size": size, "design": None, "part": None,
            "date": None, "time": None, "payload": None, "raw": False}

    try:
        hlen = struct.unpack(">H", head[0:2])[0]
        pos = 2 + hlen + 2                       # filler + the 0x0001 marker
        fields = {}
        while pos < len(head):
            key = chr(head[pos]); pos += 1
            if key == "e":                        # payload length, then bits
                info["payload"] = struct.unpack(">I", head[pos:pos + 4])[0]
                break
            n = struct.unpack(">H", head[pos:pos + 2])[0]; pos += 2
            fields[key] = head[pos:pos + n].rstrip(b"\x00").decode("latin-1")
            pos += n
        if "a" not in fields or "b" not in fields:
            raise ValueError
    except Exception:
        # No Vivado header — a raw .bin still programs fine, we just cannot
        # tell which device it was built for.
        info["raw"] = True
        return info

    # The design field is "name;UserID=0x..;Version=.." — keep the readable bits.
    parts = fields["a"].split(";")
    info["design"] = parts[0]
    for extra in parts[1:]:
        if extra.lower().startswith("version="):
            info["vivado"] = extra.split("=", 1)[1]
    info["part"] = fields["b"]
    info["date"] = fields.get("c")
    info["time"] = fields.get("d")
    return info


def describe_bitstream(info):
    """One-line human summary for the panel's status strip."""
    if info.get("raw"):
        return f"raw image · {info['size'] / 1024:.0f} KB · no device header"
    bits = [info["design"] or "?", info["part"] or "?"]
    stamp = " ".join(x for x in (info.get("date"), info.get("time")) if x)
    if stamp:
        bits.append(stamp)
    if info.get("vivado"):
        bits.append(f"Vivado {info['vivado']}")
    bits.append(f"{info['size'] / 1024:.0f} KB")
    return "  ·  ".join(bits)


def part_matches_board(info):
    """True when the bitstream targets the Basys 3's XC7A35T.

    A bitstream built for another device will not configure, and on a shared lab
    board that is a confusing failure — so the panel asks before sending one.
    """
    part = (info.get("part") or "").lower()
    return (not part) or part.startswith(EXPECTED_PART)


# ─────────────────────────── programmer discovery ──────────────────────────

def find_programmer(settings=None):
    """Locate the openFPGALoader binary, or return None.

    Order: an explicit path the user picked once (QSettings), $OPENFPGALOADER,
    then PATH, then the usual Homebrew / MacPorts prefixes — a GUI launched
    from Finder does not inherit the shell PATH that has /opt/homebrew in it.
    """
    settings = settings or QSettings(SETTINGS_ORG, SETTINGS_APP)
    saved = settings.value(SETTING_EXE, "") or ""
    if saved and os.path.isfile(saved) and os.access(saved, os.X_OK):
        return saved

    env = os.environ.get("OPENFPGALOADER", "")
    if env and os.path.isfile(env) and os.access(env, os.X_OK):
        return env

    for name in PROGRAMMER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for d in SEARCH_DIRS:
        for name in PROGRAMMER_NAMES:
            cand = os.path.join(d, name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


def find_brew():
    found = shutil.which("brew")
    if found:
        return found
    for cand in BREW_PATHS:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def program_command(exe, bit_path, flash=False):
    """openFPGALoader argv for an SRAM load or a SPI-flash write."""
    cmd = [exe, "-b", BOARD]
    if flash:
        cmd.append("-f")            # --write-flash: survives power cycles
    cmd.append(bit_path)
    return cmd


def detect_command(exe):
    return [exe, "-b", BOARD, "--detect"]


def default_bitstream(settings=None):
    """Best guess at the TARA bitstream: the last one used, else the one the
    Verilog build writes inside this checkout."""
    settings = settings or QSettings(SETTINGS_ORG, SETTINGS_APP)
    last = settings.value(SETTING_BIT, "") or ""
    if last and os.path.isfile(last):
        return last
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))       # TARA16/
    for rel in (("verilog", "CPU", "build", "tara_top.bit"),
                ("verilog", "CPU", "build", "vivado_project", "taracpu.runs",
                 "impl_1", "tara_top.bit")):
        cand = os.path.join(root, *rel)
        if os.path.isfile(cand):
            return cand
    return ""


# ────────────────────────────── live-output dialog ─────────────────────────

class RunDialog(QDialog):
    """Run one external command, streaming its output into a log pane.

    openFPGALoader reports progress by rewriting a line with a carriage return,
    so percentage lines replace the previous one instead of flooding the log,
    and also drive the progress bar.
    """

    def __init__(self, parent, title, command, blurb="", style="", success_note=""):
        super().__init__(parent)
        self.setObjectName("fpgaRoot")
        self.setWindowTitle(title)
        self.resize(720, 460)
        if style:
            self.setStyleSheet(style)

        self.command = list(command)
        self.success_note = success_note
        self.ok = None                    # None = still running / cancelled
        self._last_was_progress = False
        self._buf = ""

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(9)

        if blurb:
            lab = QLabel(blurb)
            lab.setWordWrap(True)
            v.addWidget(lab)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        v.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        f = QFont("Menlo")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(12)
        self.log.setFont(f)
        v.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.state = QLabel("starting…")
        self.state.setStyleSheet("font-weight:700;")
        row.addWidget(self.state)
        row.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("ghost")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_close)
        v.addLayout(row)

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)

        self._append("$ " + " ".join(self.command))
        self._append("")
        self.proc.start(self.command[0], self.command[1:])

    # -- output plumbing --
    def _append(self, text, progress=False):
        if progress and self._last_was_progress:
            doc = self.log.toPlainText().rsplit("\n", 1)[0]
            self.log.setPlainText(doc + "\n" + text)
        else:
            self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.End)
        self._last_was_progress = progress

    def _read(self):
        chunk = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._buf += chunk.replace("\r\n", "\n").replace("\r", "\n")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            if not line.strip():
                continue
            m = _PCT.search(line)
            if m:
                self.bar.setValue(int(float(m.group(1))))
            self._append(line.rstrip(), progress=bool(m))

    def _cancel(self):
        if self.proc.state() != QProcess.NotRunning:
            self._append("\n— cancelled —")
            self.proc.kill()
        self.reject()

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self.ok = False
            self._append(f"\nCould not start: {self.command[0]}")
            self.state.setText("failed to start")
            self.btn_cancel.setEnabled(False)
            self.btn_close.setEnabled(True)

    def _finished(self, code, _status):
        self.ok = (code == 0)
        self.bar.setValue(100 if self.ok else self.bar.value())
        if self.ok:
            self._append("\n✓ " + (self.success_note or "done"))
            self.state.setText("success")
            self.state.setStyleSheet("color:#178A1B;font-weight:700;")
        else:
            self._append(f"\n✗ exited with code {code}")
            self.state.setText(f"failed (exit {code})")
            self.state.setStyleSheet("color:#C0392B;font-weight:700;")
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.btn_close.setDefault(True)
        self.btn_close.setFocus()

    def closeEvent(self, ev):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
            self.proc.waitForFinished(1500)
        super().closeEvent(ev)


# ───────────────────────────── first-run setup ─────────────────────────────

class SetupDialog(QDialog):
    """Shown when openFPGALoader is not installed.

    Offers the one-time Homebrew install, or lets the user point at a copy they
    already have. ``exe`` holds the resolved path once either succeeds.
    """

    def __init__(self, parent, style=""):
        super().__init__(parent)
        self.setObjectName("fpgaRoot")
        self.setWindowTitle("Set up FPGA programming")
        self.resize(600, 300)
        if style:
            self.setStyleSheet(style)
        self.style_sheet = style
        self.exe = None

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        title = QLabel("openFPGALoader is required")
        title.setStyleSheet("font-size:19px;font-weight:800;color:#7A1E2B;")
        v.addWidget(title)

        body = QLabel(
            "Programming the Basys 3 over JTAG needs <b>openFPGALoader</b>, a small "
            "open-source tool that replaces the Vivado hardware manager. It is a "
            "one-time install and needs no Xilinx licence:"
            f"<p style='font-family:Menlo,monospace;font-size:14px'>{INSTALL_CMD}</p>"
            "If you do not have Homebrew, install it from <b>brew.sh</b> first, or "
            "build openFPGALoader yourself and use <b>Locate…</b> to point at the binary.")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        v.addWidget(body)
        v.addStretch(1)

        row = QHBoxLayout()
        b_copy = QPushButton("Copy command")
        b_copy.setObjectName("ghost")
        b_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(INSTALL_CMD))
        row.addWidget(b_copy)
        b_loc = QPushButton("Locate…")
        b_loc.setObjectName("ghost")
        b_loc.clicked.connect(self._locate)
        row.addWidget(b_loc)
        row.addStretch(1)
        b_close = QPushButton("Not now")
        b_close.setObjectName("ghost")
        b_close.clicked.connect(self.reject)
        row.addWidget(b_close)
        self.b_install = QPushButton("Install via Homebrew")
        self.b_install.clicked.connect(self._install)
        row.addWidget(self.b_install)
        v.addLayout(row)

        if not find_brew():
            self.b_install.setEnabled(False)
            self.b_install.setToolTip("Homebrew not found — install it from brew.sh")

    def _locate(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Locate the openFPGALoader binary", "/opt/homebrew/bin")
        if not p:
            return
        if not os.access(p, os.X_OK):
            QMessageBox.warning(self, "Not executable", f"{p} is not executable.")
            return
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(SETTING_EXE, p)
        self.exe = p
        self.accept()

    def _install(self):
        brew = find_brew()
        if not brew:
            return
        dlg = RunDialog(
            self, "Installing openFPGALoader", [brew, "install", "openfpgaloader"],
            blurb="Homebrew is downloading and installing openFPGALoader. "
                  "This usually takes a minute.",
            style=self.style_sheet, success_note="openFPGALoader installed")
        dlg.exec_()
        if dlg.ok:
            # Homebrew just created the binary, so ignore any stale saved path.
            QSettings(SETTINGS_ORG, SETTINGS_APP).remove(SETTING_EXE)
            self.exe = find_programmer()
            if self.exe:
                self.accept()
                return
        QMessageBox.warning(
            self, "Install incomplete",
            "openFPGALoader still could not be found. Try running\n\n"
            f"    {INSTALL_CMD}\n\nin a terminal, then use Locate… to select it.")
