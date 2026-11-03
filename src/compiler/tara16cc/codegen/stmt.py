# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Statements: control flow, switch and return.

Two TARA16 details shape this file.

* There is no "branch if not zero", so a test that must jump when its
  condition is *true* costs an extra JMP. `prefers_true` notices the cases
  where turning the test around is cheaper, and a `for` loop whose
  condition is an equality test gets its test at the bottom.
* `switch` has no jump table (the only indirect jump is RET). Cases are
  tested one after another against a running difference, which costs about
  two words per case.
"""
from ..ctype import is_aggregate
from .target import Addr, Val


class StmtMixin:
    """Statements: control flow, switch, return, and the statement walk."""
    def prefers_true(self, c):
        """Is "jump if true" cheaper than "jump if false" for this condition?"""
        k = c.kind
        if k == 'EQ':
            return True
        if k == 'NOT':
            return not self.prefers_true(c.lhs)
        return False

    def gen_switch(self, node):
        """A switch: a chain of tests, each subtracting only the difference."""
        self.enter_tick(node.tick)
        v = self.gen(node.cond, -1)
        t = self.make_mutable(v, -1)
        cur = 0
        for n in node.case_next:
            if n.begin != n.end:
                # a GNU range: (unsigned)(x - lo) <= hi - lo
                u = self.alloc_reg()
                self.e_rr('MOV', u, t.reg)
                self.add_imm(u, i16(cur - n.begin))
                span = (n.end - n.begin) & 0xFFFF
                w = self.alloc_reg()
                self.load_const(w, span)
                if span < 0x8000:
                    nxt = self.new_label()
                    self.e_br('BN', u, nxt)
                    self.e_rrr('SLT', w, w, u)
                    self.e_br('BZ', w, n.unique_label)
                    self.emit_label(nxt)
                    self.free_reg(u)
                    self.free_reg(w)
                else:
                    lt = self.ult(Val(w, True), Val(u, True), -1)
                    self.e_br('BZ', lt.reg, n.unique_label)
                    self.release(lt)
                continue
            delta = i16((n.begin - cur) & 0xFFFF)
            if -127 <= delta <= 128:
                if delta:
                    self.e_ri('ADDI', t.reg, -delta)
            else:
                c = self.alloc_reg()
                self.load_const(c, delta)
                self.e_rrr('SUB', t.reg, t.reg, c)
                self.free_reg(c)
            cur = n.begin
            self.e_br('BZ', t.reg, n.unique_label)
        self.release(t)
        if node.default_case:
            self.e_j('JMP', node.default_case.unique_label)
        else:
            self.e_j('JMP', node.brk_label)
        self.gen_stmt(node.then)
        self.emit_label(node.brk_label)

    def gen_return(self, node):
        """A return: the value into R0, or into the hidden buffer, then out."""
        if node.lhs is not None:
            self.enter_tick(node.tick)
            ty = node.lhs.ty
            if is_aggregate(ty):
                # copy the value through the hidden pointer (parameter 0)
                hp = self.cur_fn.params[0]
                src = self.gen_addr(node.lhs)
                if hp.reg >= 0:
                    dst = Addr('reg', hp.reg, False)
                else:
                    r = self.alloc_avoid(self.addr_regs(src))
                    self.sp_access('LDW', r, hp.slot + self.depth)
                    dst = Addr('reg', r, True)
                self.copy_bytes(dst, src, ty)
            else:
                v = self.gen(node.lhs, 0)
                if v.reg != 0:
                    self.e_rr('MOV', 0, v.reg)
                self.release(v)
        if self.ret_direct:
            self.e_0('RET')
        else:
            self.e_j('JMP', self.ret_label)

    def gen_stmt(self, node):
        """Generate one statement, whatever kind it is."""
        k = node.kind
        self.cur_tok = node.tok or self.cur_tok
        if k == 'IF':
            self.enter_tick(node.tick)
            els, end = self.new_label(), self.new_label()
            if node.els:
                if self.prefers_true(node.cond):
                    then = self.new_label()
                    self.gen_branch(node.cond, True, then)
                    self.gen_stmt(node.els)
                    self.e_j('JMP', end)
                    self.emit_label(then)
                    self.gen_stmt(node.then)
                    self.emit_label(end)
                    return
                self.gen_branch(node.cond, False, els)
                self.gen_stmt(node.then)
                self.e_j('JMP', end)
                self.emit_label(els)
                self.gen_stmt(node.els)
                self.emit_label(end)
                return
            if self.prefers_true(node.cond):
                then = self.new_label()
                self.gen_branch(node.cond, True, then)
                self.e_j('JMP', end)
                self.emit_label(then)
                self.gen_stmt(node.then)
                self.emit_label(end)
                return
            self.gen_branch(node.cond, False, end)
            self.gen_stmt(node.then)
            self.emit_label(end)
            return
        if k == 'FOR':
            top = self.new_label()
            if node.init:
                self.gen_stmt(node.init)
            if node.cond is not None and self.prefers_true(node.cond):
                test = self.new_label()         # rotated: test at the bottom
                self.e_j('JMP', test)
                self.emit_label(top)
                self.gen_stmt(node.then)
                self.emit_label(node.cont_label)
                if node.inc is not None:
                    self.enter_tick(node.tick2)
                    self.gen_void(node.inc)
                self.emit_label(test)
                self.enter_tick(node.tick)
                self.gen_branch(node.cond, True, top)
                self.emit_label(node.brk_label)
                return
            self.emit_label(top)
            if node.cond is not None:
                self.enter_tick(node.tick)
                self.gen_branch(node.cond, False, node.brk_label)
            self.gen_stmt(node.then)
            self.emit_label(node.cont_label)
            if node.inc is not None:
                self.enter_tick(node.tick2)
                self.gen_void(node.inc)
            self.e_j('JMP', top)
            self.emit_label(node.brk_label)
            return
        if k == 'DO':
            top = self.new_label()
            self.emit_label(top)
            self.gen_stmt(node.then)
            self.emit_label(node.cont_label)
            self.enter_tick(node.tick)
            self.gen_branch(node.cond, True, top)
            self.emit_label(node.brk_label)
            return
        if k == 'SWITCH':
            self.gen_switch(node)
            return
        if k == 'CASE':
            self.emit_label(node.unique_label)
            self.gen_stmt(node.lhs)
            return
        if k == 'BLOCK':
            for n in (node.body or []):
                self.gen_stmt(n)
            return
        if k == 'GOTO':
            self.e_j('JMP', node.unique_label)
            return
        if k == 'LABEL':
            self.emit_label(node.unique_label)
            self.gen_stmt(node.lhs)
            return
        if k == 'RETURN':
            self.gen_return(node)
            return
        if k == 'EXPR_STMT':
            self.enter_tick(node.tick)
            self.gen_void(node.lhs)
            return
        if k == 'ASM':
            self.emit_raw(node.asm_str)
            return
        # an expression used as a statement (the parser wraps most of them)
        self.enter_tick(node.tick)
        self.gen_void(node)


def i16(v):
    """A 16-bit pattern read as a signed number."""
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v
