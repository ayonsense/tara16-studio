# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Print the tree the code generator is given (`--dump-ast`).

The parser is the only stage that builds a data structure; everything before
it is a list of tokens and everything after it is a list of instructions. So
this is the one place where you can see the compiler's idea of a program, and
it is worth looking at before reading codegen/.

    tara16-cc prog.c --dump-ast          every function
    tara16-cc prog.c --dump-ast main     one function

What to look for, because the parser has already done real work:

  * `CAST` nodes the source never wrote: C's promotions, spelled out.
  * `ADD` under a pointer scaled by the element size (`ptr + i` is not `+`).
  * a `for` loop's four parts (`init`, `cond`, `inc`, `then`) separated.
  * `x += e` rewritten: as `ASSIGN(x, ADD(x, e))` for a plain variable, or
    through a hidden pointer variable when x is something more complicated.
  * `COMMA(MEMZERO, ...)` where a local had an initializer.
  * every variable's weight, and the register it won, in the header line.
"""
from .ctype import type_name

# The child fields worth printing, in the order a reader wants them.
KIDS = ('init', 'cond', 'lhs', 'rhs', 'then', 'els', 'inc')


def label_of(node):
    """One line describing this node, without its children."""
    s = node.kind
    if node.kind == 'NUM':
        s += f' {node.val}'
    elif node.kind == 'VAR' and node.var is not None:
        where = ''
        if node.var.is_local:
            where = (f' R{node.var.reg}' if node.var.reg >= 0
                     else f' {node.var.slot}(SP)')
        s += f' {node.var.name or "<return buffer>"}{where}'
    elif node.kind == 'MEMBER' and node.member is not None:
        m = node.member
        bits = f':{m.bit_width}@{m.bit_offset}' if m.is_bitfield else ''
        s += f' .{m.name} +{m.offset}{bits}'
    elif node.kind in ('GOTO', 'LABEL'):
        s += f' {node.label} ({node.unique_label})'
    elif node.kind == 'CASE':
        s += (f' {node.begin}..{node.end}' if node.end != node.begin
              else f' {node.begin}')
    elif node.kind == 'MEMZERO' and node.var is not None:
        s += f' {node.var.name} ({node.var.ty.size} bytes)'
    elif node.kind == 'ASM':
        s += f' {node.asm_str!r}'
    if node.ty is not None:
        s += f'   : {type_name(node.ty)}'
    return s


def rows(node, depth=0, tag=''):
    """Walk the tree, yielding (depth, text, source line) per node.

    The line number is what lets a tool line the tree up against the program
    it came from; `dump_node` just prints the text.
    """
    if node is None:
        return
    line = node.tok.pos.line if node.tok is not None else 0
    yield depth, tag + label_of(node), line
    for field in KIDS:
        kid = getattr(node, field, None)
        if kid is not None:
            yield from rows(kid, depth + 1,
                            '' if field in ('lhs', 'rhs') else f'{field}: ')
    for kid in (node.body or ()):
        yield from rows(kid, depth + 1)
    for i, kid in enumerate(node.args or ()):
        yield from rows(kid, depth + 1, f'arg{i}: ')
    for kid in (node.case_next or ()):
        yield from rows(kid, depth + 1)
    if node.default_case is not None:
        yield from rows(node.default_case, depth + 1)


def dump_node(node, out, indent=0, tag=''):
    """Print one node and everything under it."""
    for depth, text, _line in rows(node, indent, tag):
        print('  ' * depth + text, file=out)


def dump_function(fn, out):
    """Print one function: its parameters, its variables, its tree."""
    params = ', '.join(f'{type_name(p.ty)} {p.name or "<ret>"}'
                       for p in fn.params) or 'void'
    print(f'\n{type_name(fn.ty.return_ty)} {fn.name}({params})', file=out)
    for v in fn.locals:
        where = (f'R{v.reg}' if v.reg >= 0 else
                 f'{v.slot}(SP)' if v.weight else 'unused')
        extra = ' &taken' if v.addr_taken else ''
        print(f'    {type_name(v.ty):<16} {v.name or "<ret>":<14} '
              f'weight {v.weight:<5} {where}{extra}', file=out)
    dump_node(fn.body, out, 1)


def dump_program(prog, which='*', out=None):
    """Print every function in prog (or just the one named `which`).

    The driver calls this after code generation, so the weight, register and
    frame slot of every variable are the real ones.
    """
    import sys
    out = out or sys.stderr
    for fn in prog:
        if not fn.is_function or not fn.is_definition or not fn.is_live:
            continue
        if which not in ('*', fn.name):
            continue
        dump_function(fn, out)
    print('', file=out)
