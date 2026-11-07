# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""TARA simulator UI — The register-file panel (R0-R7, PC, flags).

Classes:
  RegisterPanel -- Right-hand panel showing R0-R7 (plus PC and flags) as live cards; highlights registers that changed on the last step.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

from src.ui.assets import _panel_title
from src.ui.theme import C, UI_SETTINGS

from src.ui.panels.common import REG_ACCENTS, REG_NAMES


class RegisterPanel(QGroupBox):
    """Right-hand panel showing R0-R7 (plus PC and flags) as live cards; highlights registers that changed on the last step."""
    collapsed_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__("")
        self._font_size = UI_SETTINGS["register_font_size"]
        self._collapsed = False
        self._prev = [0]*8
        layout = QGridLayout(self)
        layout.setSpacing(7)
        layout.setContentsMargins(6, 2, 6, 8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(_panel_title("Register File"))
        header.addStretch()
        self.collapse_btn = QPushButton("-")
        self.collapse_btn.setFixedSize(30, 24)
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.setToolTip("Collapse register file")
        self.collapse_btn.setStyleSheet(
            f"QPushButton {{ background:#FFFFFF;border:1px solid {C['border']};"
            f"color:{C['accent']};border-radius:6px;padding:0px;font-size:18px;font-weight:800; }}"
            f"QPushButton:hover {{ border-color:{C['accent']}; background:{C['panel2']}; }}"
            "QPushButton:pressed { background:#EBD9C4; }"
        )
        self.collapse_btn.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.collapse_btn)
        layout.addLayout(header, 0, 0, 1, 4)

        self.rows = []
        for i in range(8):
            card = QFrame()
            card.setObjectName("reg_card")
            card.setMinimumHeight(58)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            card.setToolTip(f"{REG_NAMES[i]} value")
            card.setStyleSheet(self._card_style(i, changed=False))
            shadow = QGraphicsDropShadowEffect(card)
            shadow.setBlurRadius(14)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(78, 16, 25, 31))
            card.setGraphicsEffect(shadow)

            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(8, 5, 8, 5)
            card_lay.setSpacing(2)

            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setSpacing(8)

            name = QLabel(REG_NAMES[i])
            name.setObjectName("reg_badge")
            name.setFixedSize(28, 28)
            name.setAlignment(Qt.AlignCenter)
            name.setStyleSheet(
                f"color:#FFFFFF; background-color:{REG_ACCENTS[i]};"
                "border-radius:14px;"
            )
            top.addWidget(name)

            hex_v = QLabel('0x0000')
            hex_v.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            hex_v.setStyleSheet(f"color:{C['text']};background:transparent;")
            top.addWidget(hex_v)
            top.addStretch()
            card_lay.addLayout(top)

            dec_v = QLabel('u=0  s=0')
            dec_v.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            dec_v.setStyleSheet(f"color:{C['dim']};background:transparent;")
            card_lay.addWidget(dec_v)

            layout.addWidget(card, i // 4 + 1, i % 4)
            self.rows.append((card, name, hex_v, dec_v))

        for col in range(4):
            layout.setColumnStretch(col, 1)
        self._apply_font_size()

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return

        self._collapsed = collapsed
        for card, _name, _hex_v, _dec_v in self.rows:
            card.setVisible(not collapsed)
        self.collapse_btn.setText("+" if collapsed else "-")
        self.collapse_btn.setToolTip(
            "Expand register file" if collapsed else "Collapse register file"
        )
        self._apply_height_limits()
        self.collapsed_changed.emit(collapsed)

    def _apply_height_limits(self):
        if self._collapsed:
            self.setMinimumHeight(38)
            self.setMaximumHeight(38)
        else:
            dec_size = max(14, min(19, self._font_size - 5))
            card_height = max(58, 28 + 2 + dec_size + 10)
            expanded_height = 2 * card_height + 7 + 26 + 12
            self.setMinimumHeight(expanded_height)
            self.setMaximumHeight(expanded_height + 12)

    def _apply_font_size(self):
        hex_size = max(16, min(22, self._font_size - 3))
        dec_size = max(14, min(19, self._font_size - 5))
        self._apply_height_limits()
        for card, name, hex_v, dec_v in self.rows:
            card.setMinimumHeight(max(58, 28 + 2 + dec_size + 10))
            name_font = QFont('Helvetica Neue')
            name_font.setPixelSize(12)
            name_font.setWeight(800)
            hex_font = QFont('Menlo')
            hex_font.setStyleHint(QFont.Monospace)
            hex_font.setPixelSize(hex_size)
            hex_font.setWeight(800)
            dec_font = QFont('Menlo')
            dec_font.setStyleHint(QFont.Monospace)
            dec_font.setPixelSize(dec_size)

            name.setFont(name_font)
            hex_v.setFont(hex_font)
            dec_v.setFont(dec_font)
            hex_v.setStyleSheet(
                f"color:{C['text']};background:transparent;"
                f"font-family:'Menlo', monospace;font-size:{hex_size}px;font-weight:800;"
            )
            dec_v.setStyleSheet(
                f"color:{C['dim']};background:transparent;"
                f"font-family:'Menlo', monospace;font-size:{dec_size}px;"
            )

    def _card_style(self, index, changed=False):
        background = '#F7EBD9' if changed else C['panel']
        border = C['accent2'] if changed else C['border']
        return f"""
            QFrame#reg_card {{
                background: {background};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """

    def update_regs(self, regs):
        for i, v in enumerate(regs):
            card, name_lbl, hex_v, dec_v = self.rows[i]
            signed = v - 0x10000 if v & 0x8000 else v
            changed = v != self._prev[i]
            card.setStyleSheet(self._card_style(i, changed=changed))

            hex_v.setText(f'0x{v:04X}')
            dec_v.setText(f'u={v}  s={signed}')
            dec_size = max(14, min(19, self._font_size - 5))
            dec_v.setStyleSheet(
                f"color:{REG_ACCENTS[i] if changed else C['dim']};"
                "background:transparent;"
                f"font-family:'Menlo', monospace;font-size:{dec_size}px;"
            )
            card.setToolTip(
                f"{REG_NAMES[i]}\n"
                f"Unsigned: {v}\n"
                f"Signed: {signed}\n"
                f"Hex: 0x{v:04X}"
            )
        self._prev = list(regs)
