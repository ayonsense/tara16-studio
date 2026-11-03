# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Centralised filesystem paths.

Resolves where the app reads its assets and writes user files (machine-state
saves, CSV exports, UI settings): under the repo's local/ folder when run from
source, or under ~/.taracpu/ when the package is pip-installed."""

import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(APP_DIR)

# When installed via pip, src/ lives inside site-packages and the repo root
# does not contain run_sim.py.  User-writable files (saves, exports, settings)
# are redirected to ~/.taracpu/ so the package directory stays read-only.
_running_from_source = os.path.exists(os.path.join(_repo_root, "run_sim.py"))
CONFIG_DIR = (
    os.path.join(_repo_root, "local", "config")
    if _running_from_source
    else os.path.join(os.path.expanduser("~"), ".taracpu")
)

LOGO_DIR = os.path.join(APP_DIR, "assets", "logo")
PROGS_DIR = os.path.join(APP_DIR, "examples", "progs")
MEMORY_DUMP_DIR = os.path.join(CONFIG_DIR, "memory")
CPU_STATE_DUMP_DIR = os.path.join(CONFIG_DIR, "cpu_state")
DEFAULT_MEMORY_DUMP_PATH = os.path.join(MEMORY_DUMP_DIR, "memory_dump.csv")
DEFAULT_CPU_STATE_PATH = os.path.join(CPU_STATE_DUMP_DIR, "tara_machine_state.json")
UI_SETTINGS_PATH = os.path.join(CONFIG_DIR, "ui_settings.json")
APP_ICON_PATH = os.path.join(LOGO_DIR, "logo2_cropped.png")
BRAND_TEXT_LOGO_PATH = os.path.join(LOGO_DIR, "logo2_text.png")


def ensure_config_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(MEMORY_DUMP_DIR, exist_ok=True)
    os.makedirs(CPU_STATE_DUMP_DIR, exist_ok=True)
