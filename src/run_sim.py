#!/usr/bin/env python3
# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.

"""
TARA CPU Simulator launcher.
Run: python3 run_sim.py
"""

import os

from src.ui.app import main


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
