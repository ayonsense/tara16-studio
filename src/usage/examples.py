# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Translate bundled program paths into a fixed, public analytics catalog.

Only catalog IDs leave the app. New student files, even files added inside an
examples directory, cannot introduce new names into event properties.
"""

from pathlib import Path
from src.compiler.catalog import EXAMPLES
from src.paths import PROGS_DIR

_ASSEMBLY_IDS = frozenset({
    'Advanced/binary_search',
    'Advanced/bubble_sort',
    'Advanced/factorial_recursive',
    'Advanced/insertion_sort',
    'Advanced/matrix_multiplication',
    'Advanced/selection_sort',
    'Basic/count_set_bits',
    'Basic/factorial',
    'Basic/fibonacci',
    'Basic/power_of_two',
    'Basic/sum_1_to_n',
    'Display/bouncing_ball',
    'Display/draw_checkerboard',
    'Display/draw_line',
    'Display/draw_rectangle',
    'Display/draw_spiral',
    'Display/draw_triangle',
    'Games/flappy_bird',
    'Games/ping_pong',
    'Games/racing',
    'Games/snake',
    'Intermediate/collatz_steps',
    'Intermediate/first_n_primes',
    'Intermediate/greatest_common_divisor',
    'Intermediate/linear_search',
    'Intermediate/prime_test',
    'Intermediate/reverse_array',
})
_C_IDS = frozenset(example.category + "/" + example.id for example in EXAMPLES)
CATALOG = {"assembly": _ASSEMBLY_IDS, "c": _C_IDS}
_ROOTS = {"assembly": Path(PROGS_DIR).resolve(),
          "c": Path(__file__).resolve().parents[1] / "compiler" / "examples"}
EXAMPLE_FIELDS = frozenset({"example_id", "example_language", "example_category", "example_modified"})


def validate_example(properties):
    if not isinstance(properties, dict) or set(properties) != EXAMPLE_FIELDS:
        return None
    language, identifier = properties["example_language"], properties["example_id"]
    if (not isinstance(language, str) or language not in CATALOG
            or not isinstance(identifier, str) or identifier not in CATALOG[language]
            or properties["example_category"] != identifier.split("/", 1)[0]
            or not isinstance(properties["example_modified"], bool)):
        return None
    return dict(properties)


def bundled_example(path, language, *, modified=False):
    if not path or language not in _ROOTS:
        return None
    try:
        relative = Path(path).resolve().relative_to(_ROOTS[language])
        suffix = ".c" if language == "c" else ".tara"
        if relative.suffix != suffix:
            return None
        identifier = relative.with_suffix("").as_posix()
        return validate_example({"example_id": identifier, "example_language": language,
            "example_category": relative.parts[0], "example_modified": bool(modified)})
    except (OSError, ValueError, RuntimeError):
        return None
