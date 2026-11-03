# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Loads the bundled .tara example programs from src/examples/progs, grouped by
category (Basic / Intermediate / Advanced / Display / Games), and exposes them to
the editor's 'Select Program' dropdown."""

from pathlib import Path

from src.paths import PROGS_DIR

EXAMPLE_CATEGORIES = ("Basic", "Intermediate", "Advanced", "Display", "Games")
_FALLBACK_CATEGORY = "Basic"


def _display_name(path):
    return path.stem.replace('_', ' ').title()


def _category_for_path(path, progs):
    try:
        rel = path.relative_to(progs)
    except ValueError:
        return _FALLBACK_CATEGORY

    if len(rel.parts) > 1 and rel.parts[0] in EXAMPLE_CATEGORIES:
        return rel.parts[0]
    return _FALLBACK_CATEGORY


def load_example_groups():
    groups = {category: {} for category in EXAMPLE_CATEGORIES}
    progs = Path(PROGS_DIR)
    if not progs.exists():
        return groups
    for path in sorted(progs.rglob('*.tara')):
        category = _category_for_path(path, progs)
        groups.setdefault(category, {})[_display_name(path)] = path.read_text(
            encoding='utf-8', errors='replace'
        )
    return groups


def load_examples():
    examples = {}
    for programs in load_example_groups().values():
        examples.update(programs)
    return examples
