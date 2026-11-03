# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""The tree the parser builds and the code generator walks.

There is no separate intermediate representation: this typed tree *is* the
IR. One class with a `kind` string keeps the code short and the printouts
readable (`python3 -m tara16cc --dump-ast prog.c`).

Expression kinds
    NUM VAR MEMBER DEREF ADDR ASSIGN CAST COMMA COND FUNCALL STMT_EXPR
    ADD SUB MUL DIV MOD SHL SHR BITAND BITOR BITXOR
    EQ NE LT LE NOT BITNOT NEG LOGAND LOGOR MEMZERO NULL_EXPR
Statement kinds
    BLOCK IF FOR DO SWITCH CASE RETURN GOTO LABEL EXPR_STMT ASM
"""


class Node:
    """One piece of a program: an operator, a statement, a constant, a name."""
    __slots__ = ('kind', 'ty', 'tok', 'lhs', 'rhs', 'cond', 'then', 'els',
                 'init', 'inc', 'body', 'args', 'var', 'member', 'val',
                 'label', 'unique_label', 'brk_label', 'cont_label',
                 'case_next', 'default_case', 'begin', 'end', 'ret_buffer',
                 'asm_str', 'func_ty', 'tick', 'tick2')

    def __init__(self, kind, tok=None, ty=None):
        self.kind = kind
        self.ty = ty
        self.tok = tok
        self.lhs = self.rhs = self.cond = self.then = self.els = None
        self.init = self.inc = None
        self.body = None            # list of Node (BLOCK, STMT_EXPR)
        self.args = None            # list of Node (FUNCALL)
        self.var = None             # Obj (VAR, MEMZERO)
        self.member = None          # Member (MEMBER)
        self.val = 0                # NUM
        self.label = None           # source label (GOTO/LABEL)
        self.unique_label = None    # assembly label
        self.brk_label = self.cont_label = None
        self.case_next = None       # list of CASE nodes (SWITCH)
        self.default_case = None
        self.begin = self.end = 0   # case value range
        self.ret_buffer = None      # Obj: buffer for a struct-returning call
        self.asm_str = None
        self.func_ty = None         # FUNCALL: the function's type
        self.tick = 0               # the full expression's place in time
        self.tick2 = 0              # (FOR: tick = cond, tick2 = inc)

    def __repr__(self):
        return f'<{self.kind}>'


class Obj:
    """A variable or a function."""
    __slots__ = ('name', 'ty', 'tok', 'is_local', 'is_function', 'is_definition',
                 'is_static', 'is_tls', 'is_live', 'align', 'init_data', 'rel',
                 'params', 'locals', 'body', 'slot', 'reg', 'weight',
                 'addr_taken', 'argidx', 'ind_stub', 'is_inline',
                 'is_root', 'refs', 'loop_depth', 'live_lo', 'live_hi')

    def __init__(self, name, ty, is_local=False):
        self.name = name
        self.ty = ty
        self.tok = None
        self.is_local = is_local
        self.is_function = False
        self.is_definition = False
        self.is_static = False
        self.is_tls = False
        self.is_live = False   # set by the parser's sweep over the roots
        self.is_root = False   # reachable from outside this file
        self.refs = []         # functions this function names
        self.is_inline = False
        self.align = ty.align if ty else 1
        self.init_data = None       # bytes for an initialized global
        self.rel = []               # [(offset, label, addend)] in init_data
        self.params = []            # functions
        self.locals = []
        self.body = None
        self.slot = 0               # locals: byte offset in the frame
        self.reg = -1               # locals: register home, or -1
        self.weight = 0             # locals: how often it is used
        self.addr_taken = False
        self.argidx = -1            # parameters: 0, 1, 2, ...
        self.ind_stub = False       # functions: address taken -> needs a stub
        self.loop_depth = 0         # locals: how many loops the declaration is in
        self.live_lo = 0            # locals: first and last tick the value
        self.live_hi = 0            #         must survive (codegen/func.py)

    def __repr__(self):
        return f'<Obj {self.name}>'
