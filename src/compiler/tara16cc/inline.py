# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Inlining: copy small functions into the places that call them.

A call costs more on TARA16 than the few instructions around it suggest.
The arguments are moved into R0-R2, CALL and RET are two more instructions,
and whatever the caller keeps in R0-R2 must be saved around the call; a
callee that needs more registers than that must save and restore R3-R5.
For a one-line helper such as `pset` from tara16.h the call costs more
than the work it does, and it is made once for every pixel.

This pass works on the tree, between the parser and the code generator,
and replaces a call with a copy of the callee's body:

    pset(x, y + r);   ->   { TARA_PIX(x, y + r) |= tara_bit[x & 7]; }

Each parameter is either *substituted*, when the argument can stand where
the parameter stood (a constant, a variable, or an expression with no side
effects that the body reads once), or *bound* to a fresh local variable
that is assigned before the body. Two shapes of function can be copied:

* a body of expressions ending in `return e;` becomes the expression
  `(p = arg, ..., e)`, which can replace a call anywhere;
* a `void` function becomes the block `{ p = arg; ... body ... }`, which can
  replace a call that is a statement on its own.

What is worth copying is decided by size, because 2 KB is the whole machine.
A function of `TINY` tree nodes or fewer is copied everywhere: the copy is
no bigger than the call. A larger `inline` one, up to `HOT` nodes, is
copied where it is the only call, and into loops, which is where the time
goes -- but only if the program calls it from at most `LOOP_COPIES` loops,
so that a helper called all over a program is not copied all over it.
Over the test programs this makes the code smaller, not larger.
"""
from .ctype import is_aggregate, is_scalar
from .node import Node, Obj

TINY = 8           # nodes: no bigger than the call it replaces
HOT = 48           # nodes: worth it in a loop, or for the only caller
LOOP_COPIES = 3    # at most this many calls from loops, program-wide
MAX_DEPTH = 3      # copies inside copies (hline -> pset), at most this deep

CHILDREN = ('lhs', 'rhs', 'cond', 'then', 'els', 'init', 'inc')
SCALARS = ('member', 'val', 'label', 'unique_label', 'brk_label',
           'cont_label', 'begin', 'end', 'asm_str', 'func_ty')
PURE_OPS = {'ADD', 'SUB', 'MUL', 'SHL', 'SHR', 'BITAND', 'BITOR', 'BITXOR',
            'NEG', 'BITNOT', 'NOT', 'EQ', 'NE', 'LT', 'LE', 'CAST'}


def subtrees(n):
    """The children of a node, in the order the pass visits them."""
    for f in CHILDREN:
        sub = getattr(n, f)
        if sub is not None:
            yield sub
    for lst in (n.body, n.args):
        for sub in (lst or []):
            yield sub


# Nodes that only wrap or convert, and cost no instructions of their own.
# They are left out of the size measure, which is then the same in both
# compilers: their parsers build these wrappers differently (the C one keeps
# casts that change nothing and pads initializers with empty expressions)
# but agree on everything else.
WRAPPERS = {'CAST', 'BLOCK', 'COMMA', 'EXPR_STMT', 'NULL_EXPR'}


def count_nodes(n):
    """The size of a tree: its operators, operands and statements, not its
    wrappers. This is the measure the heuristic uses."""
    if n is None:
        return 0
    own = 0 if n.kind in WRAPPERS else 1
    return own + sum(count_nodes(s) for s in subtrees(n))


def contains(n, kinds):
    """Does the tree hold a node of one of these kinds?"""
    if n is None:
        return False
    if n.kind in kinds:
        return True
    return any(contains(s, kinds) for s in subtrees(n))


def expression_like(s):
    """A statement that is only expressions: one, or a declaration's list."""
    if s.kind == 'EXPR_STMT':
        return True
    return s.kind == 'BLOCK' and all(x.kind == 'EXPR_STMT' for x in (s.body or []))


def shape(fn):
    """'expr' if the body can become an expression, 'stmt' if it can become
    a block, None if it cannot be copied at all."""
    ty = fn.ty
    if is_aggregate(ty.return_ty):
        return None
    if any(is_aggregate(p.ty) for p in fn.params):
        return None
    if contains(fn.body, ('LABEL',)):
        return None
    stmts = fn.body.body or []
    if ty.return_ty.kind != 'void':
        if stmts and stmts[-1].kind == 'RETURN' and stmts[-1].lhs is not None and \
                all(expression_like(s) for s in stmts[:-1]):
            return 'expr'
        return None
    body = stmts[:-1] if stmts and stmts[-1].kind == 'RETURN' else stmts
    if any(contains(s, ('RETURN',)) for s in body):
        return None
    return 'stmt'


def usage(n, p, loops, acc):
    """Count reads of parameter p in a tree, note whether any is inside a
    loop, and whether p is ever written or has its address taken."""
    if n is None:
        return
    k = n.kind
    if k == 'VAR' and n.var is p:
        acc[0] += 1
        if loops:
            acc[1] = True
        return
    if k == 'ASSIGN' and n.lhs.kind == 'VAR' and n.lhs.var is p:
        acc[2] = True
    if k == 'ADDR':
        m = n.lhs
        while m is not None and m.kind == 'MEMBER':
            m = m.lhs
        if m is not None and m.kind == 'VAR' and m.var is p:
            acc[2] = True
    if k == 'FOR':
        usage(n.init, p, loops, acc)
        for sub in (n.cond, n.then, n.inc):
            usage(sub, p, loops + 1, acc)
        return
    if k == 'DO':
        for sub in (n.then, n.cond):
            usage(sub, p, loops + 1, acc)
        return
    for sub in subtrees(n):
        usage(sub, p, loops, acc)


def addr_taken(n, out):
    """Collect the locals whose address a tree takes."""
    if n is None:
        return
    if n.kind == 'ADDR':
        m = n.lhs
        while m is not None and m.kind == 'MEMBER':
            m = m.lhs
        if m is not None and m.kind == 'VAR' and m.var.is_local:
            out.add(m.var)
    for sub in subtrees(n):
        addr_taken(sub, out)


class Inliner:
    """One pass over a program, copying calls to small functions."""
    def __init__(self, prog):
        """Find every function with a body, count its calls, and keep an
        untouched copy of each one that could be copied."""
        self.prog = prog
        self.fns = {}            # name -> function with a body
        self.tmpl = {}           # name -> (shape, cost, untouched copy of the body)
        self.sites = {}          # name -> calls to it from live functions
        self.count = 0           # expansions so far: makes copied labels unique
        for f in prog:
            if f.is_function and f.is_definition and f.body is not None:
                self.fns[f.name] = f
        self.loopsites = {}      # name -> calls to it from inside a loop
        for f in self.fns.values():
            if f.is_live:
                self.count_sites(f.body)
                self.count_loop_sites(f.body, 0)
        self.tlocals = {}        # name -> the callee's locals, as parsed
        for name, f in self.fns.items():
            form = shape(f)
            if form:
                self.tmpl[name] = (form, count_nodes(f.body),
                                   self.clone(f.body, {}, '', None))
                self.tlocals[name] = list(f.locals)

    def count_sites(self, n):
        """Count the direct calls to each function in a tree."""
        if n is None:
            return
        if n.kind == 'FUNCALL' and n.lhs.kind == 'VAR' and n.lhs.var.is_function:
            name = n.lhs.var.name
            self.sites[name] = self.sites.get(name, 0) + 1
        for sub in subtrees(n):
            self.count_sites(sub)

    def count_loop_sites(self, n, loops):
        """Count the direct calls to each function made from inside a loop."""
        if n is None:
            return
        if n.kind == 'FUNCALL' and loops and n.lhs.kind == 'VAR' and n.lhs.var.is_function:
            self.loopsites[n.lhs.var.name] = self.loopsites.get(n.lhs.var.name, 0) + 1
        inner = loops + (1 if n.kind in ('FOR', 'DO') else 0)
        for sub in subtrees(n):
            self.count_loop_sites(sub, loops if sub is n.init else inner)

    # ------------------------------------------------------------ copying
    def clone(self, n, vm, suffix, tok):
        """A deep copy of a tree. Variables in vm are replaced (by another
        variable, or by a copy of an argument); labels get the suffix, so
        two copies of one loop never share a label; and with a token, every
        node is placed at the call, so `--lines` and messages point there."""
        if n is None:
            return None
        if n.kind == 'VAR' and n.var in vm:
            r = vm[n.var]
            if isinstance(r, Node):
                return self.clone(r, {}, '', None)
            m = Node('VAR', tok or n.tok, n.ty)
            m.var = r
            return m
        m = Node(n.kind, tok or n.tok, n.ty)
        for f in SCALARS:
            setattr(m, f, getattr(n, f))
        if suffix:
            for f in ('unique_label', 'brk_label', 'cont_label'):
                if getattr(n, f):
                    setattr(m, f, getattr(n, f) + suffix)
        m.var = vm.get(n.var, n.var) if n.var is not None else None
        m.ret_buffer = vm.get(n.ret_buffer, n.ret_buffer) if n.ret_buffer else None
        for f in CHILDREN:
            setattr(m, f, self.clone(getattr(n, f), vm, suffix, tok))
        if n.body is not None:
            m.body = [self.clone(s, vm, suffix, tok) for s in n.body]
        if n.args is not None:
            m.args = [self.clone(s, vm, suffix, tok) for s in n.args]
        if n.kind == 'SWITCH':
            cases = {}
            self.find_cases(m.then, cases)
            m.case_next = [cases[c.unique_label + suffix] for c in n.case_next]
            if n.default_case is not None:
                m.default_case = cases[n.default_case.unique_label + suffix]
        return m

    def find_cases(self, n, out):
        """The CASE nodes of a copied switch body, by label."""
        if n is None:
            return
        if n.kind == 'CASE':
            out[n.unique_label] = n
        if n.kind == 'SWITCH':
            return                          # an inner switch keeps its own
        for sub in subtrees(n):
            self.find_cases(sub, out)

    # ------------------------------------------------------------ deciding
    def simple(self, a):
        """An argument that may be copied to every use: a constant, or a
        local variable nothing can change behind the caller's back."""
        while a.kind == 'CAST':
            a = a.lhs
        if a.kind == 'NUM':
            return True
        return a.kind == 'VAR' and a.var.is_local and is_scalar(a.var.ty) and \
            a.var not in self.taken

    def pure(self, a):
        """An argument with no side effects and no memory reads: moving it
        to the one place the body reads it changes nothing."""
        if self.simple(a):
            return True
        if a.kind not in PURE_OPS:
            return False
        return all(self.pure(s) for s in (a.lhs, a.rhs) if s is not None)

    def worth(self, name, loops):
        """Is copying this function here worth the space it takes?"""
        form, cost, _ = self.tmpl[name]
        if cost <= TINY:
            return True
        if cost > HOT or not self.fns[name].is_inline:
            return False
        if self.sites.get(name, 0) == 1:
            return True                     # the only copy: no bigger at all
        return loops > 0 and self.loopsites.get(name, 0) <= LOOP_COPIES

    def target(self, call, chain, want):
        """The function a call could be replaced by, or None."""
        if call.kind != 'FUNCALL' or call.lhs.kind != 'VAR' or \
                not call.lhs.var.is_function or call.ret_buffer is not None:
            return None
        name = call.lhs.var.name
        t = self.tmpl.get(name)
        if t is None or t[0] != want or name in chain or len(chain) > MAX_DEPTH:
            return None
        if len(call.args or []) != len(self.fns[name].params):
            return None
        return name

    def bind(self, name, args, loops):
        """Map each parameter to its argument or to a new local, and each
        local of the callee to a new local of the caller."""
        callee = self.fns[name]
        body = self.tmpl[name][2]
        vm, binds = {}, []
        for p, a in zip(callee.params, args):
            acc = [0, False, False]
            usage(body, p, 0, acc)
            uses, in_loop, written = acc
            if not written and (self.simple(a) or
                                (uses <= 1 and not in_loop and self.pure(a))):
                vm[p] = a
                continue
            v = self.new_local(f'{name}.{p.name}', p.ty, loops)
            vm[p] = v
            asg = Node('ASSIGN', a.tok, p.ty)
            asg.lhs = Node('VAR', a.tok, p.ty)
            asg.lhs.var = v
            asg.rhs = a
            binds.append(asg)
        for v in self.tlocals[name]:
            if v.argidx < 0:
                vm[v] = self.new_local(f'{name}.{v.name}' if v.name else '',
                                       v.ty, loops + v.loop_depth)
        return vm, binds

    def new_local(self, name, ty, depth):
        """A local of the function being rewritten, at the front of its list."""
        v = Obj(name, ty, is_local=True)
        v.tok = self.fn.tok
        v.loop_depth = depth
        self.fn.locals.insert(0, v)
        return v

    # ------------------------------------------------------------ rewriting
    def run(self):
        """Rewrite every live function, in program order."""
        for f in self.prog:
            if f.is_function and f.is_definition and f.body is not None and f.is_live:
                self.fn = f
                self.taken = set()
                addr_taken(f.body, self.taken)
                self.stmt(f.body, 0, (f.name,))

    def stmt(self, n, loops, chain):
        """Rewrite the calls in a statement; `loops` counts the loops around it."""
        if n is None:
            return
        k = n.kind
        if k == 'EXPR_STMT':
            name = self.target(n.lhs, chain, 'stmt')
            if name and self.worth(name, loops):
                call = n.lhs
                for a in call.args:
                    self.expr(a, loops, chain)
                self.expand_stmt(n, name, call, loops)
                for s in n.body:
                    self.stmt(s, loops, chain + (name,))
                return
            self.expr(n.lhs, loops, chain)
            return
        if k == 'FOR':
            self.stmt(n.init, loops, chain)
            self.expr(n.cond, loops + 1, chain)
            self.stmt(n.then, loops + 1, chain)
            self.expr(n.inc, loops + 1, chain)
            return
        if k == 'DO':
            self.stmt(n.then, loops + 1, chain)
            self.expr(n.cond, loops + 1, chain)
            return
        if k in ('IF', 'SWITCH', 'RETURN'):
            self.expr(n.cond if k != 'RETURN' else n.lhs, loops, chain)
            self.stmt(n.then, loops, chain)
            self.stmt(n.els, loops, chain)
            return
        if k in ('CASE', 'LABEL'):
            self.stmt(n.lhs, loops, chain)
            return
        if k == 'BLOCK':
            for s in (n.body or []):
                self.stmt(s, loops, chain)
            return
        if k in ('GOTO', 'ASM'):
            return
        self.expr(n, loops, chain)

    def expr(self, n, loops, chain):
        """Rewrite the calls inside an expression, innermost first."""
        if n is None:
            return
        if n.kind == 'STMT_EXPR':
            for s in (n.body or []):
                self.stmt(s, loops, chain)
            return
        for f in CHILDREN:
            self.expr(getattr(n, f), loops, chain)
        for a in (n.args or []):
            self.expr(a, loops, chain)
        name = self.target(n, chain, 'expr')
        if name and self.worth(name, loops):
            self.expand_expr(n, name, loops)
            self.expr(n, loops, chain + (name,))

    def expand_stmt(self, n, name, call, loops):
        """Turn the statement `f(args);` into a block holding f's body."""
        self.count += 1
        suffix = f'.i{self.count}'
        vm, binds = self.bind(name, call.args, loops)
        stmts = self.tmpl[name][2].body or []
        if stmts and stmts[-1].kind == 'RETURN':
            stmts = stmts[:-1]
        body = []
        for b in binds:
            e = Node('EXPR_STMT', call.tok)
            e.lhs = b
            body.append(e)
        for s in stmts:
            body.append(self.clone(s, vm, suffix, call.tok))
        n.kind = 'BLOCK'
        n.lhs = None
        n.body = body

    def expand_expr(self, n, name, loops):
        """Turn the call n into the expression (binds..., body..., value)."""
        self.count += 1
        suffix = f'.i{self.count}'
        vm, binds = self.bind(name, n.args, loops)
        stmts = self.tmpl[name][2].body
        parts = list(binds)
        for s in stmts[:-1]:
            for e in (s.body if s.kind == 'BLOCK' else [s]):
                parts.append(self.clone(e.lhs, vm, suffix, n.tok))
        parts.append(self.clone(stmts[-1].lhs, vm, suffix, n.tok))
        e = parts[-1]
        for p in reversed(parts[:-1]):
            c = Node('COMMA', n.tok, e.ty)
            c.lhs, c.rhs = p, e
            e = c
        for f in Node.__slots__:            # n becomes e, in place
            setattr(n, f, getattr(e, f))


def inline_program(prog):
    """Copy the calls worth copying, in every live function of a program."""
    Inliner(prog).run()
