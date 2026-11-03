# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Source positions and error messages.

Every token carries a Pos. An error prints the offending line with a caret
under it, exactly like a familiar C compiler:

    prog.c:7: int x = 100000;
                      ^ TARA16: integer constant does not fit in 16 bits
"""


class Pos:
    """Where a token came from: a file, a line number, an offset in the text."""
    __slots__ = ('file', 'line', 'off')

    def __init__(self, file, line, off):
        self.file = file          # SourceFile
        self.line = line          # 1-based
        self.off = off            # offset of the token in file.text

    def __repr__(self):
        return f'{self.file.name}:{self.line}'


class SourceFile:
    """One source file, kept whole so that errors can quote a line."""
    __slots__ = ('name', 'text')

    def __init__(self, name, text):
        self.name = name
        self.text = text

    def line_text(self, off):
        """The line containing offset `off`, and the column within it."""
        start = self.text.rfind('\n', 0, off) + 1
        end = self.text.find('\n', off)
        if end < 0:
            end = len(self.text)
        return self.text[start:end], off - start


class CompileError(Exception):
    """A user-visible compilation error, already formatted."""


def error_at(pos, msg):
    """Raise a compilation error, pointing at a place in the source."""
    if pos is None:
        raise CompileError(f'tara16cc: {msg}')
    line, col = pos.file.line_text(pos.off)
    head = f'{pos.file.name}:{pos.line}: '
    caret = ' ' * (len(head) + col) + '^ ' + msg
    raise CompileError(f'{head}{line}\n{caret}')


def error(msg):
    """Raise a compilation error with no position to point at."""
    raise CompileError(f'tara16cc: {msg}')
