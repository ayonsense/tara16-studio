# Copyright (C) 2026 Ayon Chakraborty, IIT Madras.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile an editor snapshot without changing the user's source files.

The bundled compiler runs in a child Python process, isolated from the GUI's
imports and mutable compiler state. All intermediate/output files live in a
temporary directory. Headers alongside the original source file are found
through the compiler's normal include search path.

The native ``.s`` output contains linker directives and pseudo-instructions;
it is *not* input for Studio's instruction-only assembler. The compiler also
exports ``.tara`` with resolved operands and an initializer for global data.
That is the output validated here and passed to the Assembly workspace.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Optional

from src.assembler.asm import assemble


STACK_TOP = 0x5FE
MIN_STACK_BYTES = 32
COMPILE_TIMEOUT_SECONDS = 30
APP_ROOT = Path(__file__).resolve().parents[2]


class CompilationError(Exception):
    """A source error, compiler failure, or timeout with displayable details."""

    def __init__(self, diagnostics: str):
        self.diagnostics = diagnostics
        super().__init__(diagnostics)


@dataclass(frozen=True)
class CompileResult:
    """In-memory outputs from one successful compile/link operation.

    ``studio_error`` blocks Assembly transfer only: a native image may fit
    while the extra ``.tara`` data initializer does not. Native artifacts
    remain available for export in that case. The 32-byte reserve matches
    the compiler driver's minimum; it cannot prove a program's peak stack
    use, particularly for recursion.
    """

    assembly: str
    native_assembly: str
    hex_text: str
    listing_text: str
    symbols_text: str
    diagnostics: str
    studio_error: Optional[str] = None

    @property
    def studio_compatible(self) -> bool:
        """Whether Studio can assemble the generated program within its limit."""
        return self.studio_error is None

    @property
    def image_size(self) -> int:
        """Native image size in bytes (the compiler emits one word per line)."""
        return 2 * len(self.hex_text.split())


def _studio_error(assembly: str) -> Optional[str]:
    """Validate the actual handoff, including appended data initialization."""
    words, _listing, errors, _labels = assemble(assembly)
    if errors:
        return "Generated Studio assembly could not be assembled:\n" + "\n".join(
            str(error) for error in errors
        )
    if not words:
        return "The compiler generated no Studio instructions."
    end = max(address + 2 for address, _word in words)
    limit = STACK_TOP - MIN_STACK_BYTES
    if end > limit:
        return (
            f"Studio assembly uses {end} bytes, including its data initializer; "
            f"at most {limit} bytes fit below the stack at 0x{STACK_TOP:03X} "
            f"with a {MIN_STACK_BYTES}-byte reserve. Export the native HEX "
            "image instead, or reduce the program/initialized data."
        )
    return None


def compile_source(
    source: str,
    source_path: Optional[str] = None,
    optimization: int = 2,
    use_mul: bool = True,
) -> CompileResult:
    """Compile one C editor snapshot and return all five generated artifacts.

    ``source_path`` names the original file for diagnostics and sibling
    ``#include`` resolution; its contents are never written or compiled.
    Unsaved documents may omit it. ``optimization`` accepts 0, 1, or 2;
    ``use_mul=False`` selects the software multiply runtime for TTL boards.

    Raise :class:`CompilationError` for compilation/link errors, missing
    outputs, invalid options, or the 30-second time limit. A source-level
    compilation failure never exposes outputs from a preceding build.
    """
    if not isinstance(source, str) or not source.strip():
        raise CompilationError("Enter a C program before compiling.")
    if type(optimization) is not int or optimization not in (0, 1, 2):
        raise CompilationError("Optimization must be 0, 1, or 2.")
    if not isinstance(use_mul, bool):
        raise CompilationError("The hardware multiply option must be true or false.")

    original = Path(source_path).expanduser().resolve() if source_path else None
    display_name = str(original) if original else "Untitled.c"
    # A fixed .c snapshot also accepts a user file whose suffix is uppercase.
    with tempfile.TemporaryDirectory(prefix="tara-studio-compile-") as work:
        snapshot = Path(work) / "source.c"
        output = Path(work) / "program"
        snapshot.write_text(source, encoding="utf-8")
        command = [
            sys.executable, "-m", "src.compiler.tara16cc", str(snapshot),
            "-o", str(output.with_suffix(".hex")), f"-O{optimization}",
        ]
        if original:
            command.extend(["-I", str(original.parent)])
        if not use_mul:
            command.append("-mno-mul")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(APP_ROOT), environment.get("PYTHONPATH")) if part
        )
        try:
            process = subprocess.run(
                command, cwd=str(APP_ROOT), env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=COMPILE_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CompilationError(
                f"Compilation exceeded {COMPILE_TIMEOUT_SECONDS} seconds. "
                "Reduce the source or check for recursive macro expansion."
            ) from error
        except OSError as error:
            raise CompilationError(f"Could not start the bundled compiler: {error}") from error

        diagnostics = "\n".join(
            part.strip() for part in (process.stdout, process.stderr) if part.strip()
        ).replace(str(snapshot), display_name)
        if process.returncode:
            raise CompilationError(diagnostics or f"Compiler exited with status {process.returncode}.")

        try:
            outputs = {
                suffix: output.with_suffix(suffix).read_text(encoding="utf-8")
                for suffix in (".tara", ".s", ".hex", ".lst", ".sym")
            }
        except (OSError, UnicodeError) as error:
            raise CompilationError(f"Could not read compiler output: {error}") from error

    studio_error = _studio_error(outputs[".tara"])
    return CompileResult(
        assembly=outputs[".tara"], native_assembly=outputs[".s"],
        hex_text=outputs[".hex"], listing_text=outputs[".lst"],
        symbols_text=outputs[".sym"], diagnostics=diagnostics,
        studio_error=studio_error,
    )
