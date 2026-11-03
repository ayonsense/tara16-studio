# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""tara16-cc: a C compiler for the TARA16 teaching CPU, in pure Python.

    from tara16cc import compile_text
    asm = compile_text('int main() { return 42; }')

The command line lives in tara16cc.driver; the stages are
lex -> pp -> parse -> codegen -> asm, one module each.
"""
__version__ = '0.1.0'


def compile_text(text, name='<string>', opt=None):
    """Compile C source text to TARA16 assembly (for experiments)."""
    import os
    import tempfile
    from .opt import Options
    from .driver import compile_file, INCLUDE
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'x.c')
        with open(path, 'w') as f:
            f.write(text)
        return compile_file(path, opt or Options(), [INCLUDE], [])
