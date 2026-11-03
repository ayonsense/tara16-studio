# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Which ideas the compiler is allowed to use.

Every optimization in this compiler is a switch. `-O0` turns them all off,
which gives a plain, readable translation; `-O2` (the default) turns them
all on. Individual flags (`-fno-regvars`, `-fsteer`, ...) let you measure
one idea at a time, which is what the ablation study in the documentation
does — no patched sources needed.
"""


class Options:
    """Which ideas the code generator is allowed to use."""
    NAMES = ('regvars', 'steer', 'order', 'peephole', 'epilogues', 'savetrim',
             'cse', 'zero_page', 'compound_fix', 'live', 'inline')
    HELP = {
        'regvars': 'keep busy variables in registers',
        'steer': 'compute a result straight into its destination register',
        'order': 'evaluate the operand that needs more registers first',
        'peephole': 'clean up the finished instruction list',
        'epilogues': 'share one epilogue between functions that end alike',
        'savetrim': 'save only the registers a function really writes',
        'cse': "form a global's address once in a read-modify-write",
        'zero_page': 'place small globals below 0x100 (one-word addresses)',
        'compound_fix': '`x += e` without taking the address of x',
        'live': 'let variables that are never alive together share a register',
        'inline': 'copy small functions into the places that call them',
    }

    def __init__(self, level=2, mul=True, gc=True):
        self.set_level(level)
        self.mul = mul              # False with -mno-mul (the TTL board)
        self.gc = gc                # the linker drops unreachable chunks
        self.lines = False          # --lines: tag each instruction with its
        self.level = level          #          line of C

    def set_level(self, level):
        """Turn every idea on or off for -O0, -O1 or -O2."""
        on = level > 0
        for name in self.NAMES:
            setattr(self, name, on)
        self.level = level
        if level == 1:
            # -O1 leaves off the three ideas whose effect is hardest to follow
            # in the output: a shared epilogue sends a function's ending
            # somewhere else, the cached address of a global makes one
            # instruction stand for two, and inlining moves a function's
            # instructions into its callers, so the output no longer lines up
            # with the functions of the source.
            self.peephole = True
            self.epilogues = False
            self.cse = False
            self.inline = False

    def set(self, name, value):
        """Turn one idea on or off by name; False if there is no such idea."""
        if name not in self.NAMES:
            return False
        setattr(self, name, value)
        return True

    def __repr__(self):
        on = [n for n in self.NAMES if getattr(self, n)]
        return f'<Options -O{self.level} {" ".join(on)}>'
