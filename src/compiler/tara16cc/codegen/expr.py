# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Expressions.

`gen(node, hint)` evaluates one expression and returns the register that
holds its value. Three ideas run through the whole file:

* **A pool of temporaries.** Intermediate values live in registers handed
  out by `alloc_reg`. When the pool runs dry, `gen_keep` pushes what is
  live, evaluates, and pops it back (a *spill*).
* **Harder operand first** (`gen_pair`): evaluating the side that needs more
  registers first keeps the peak lower. This is Sethi-Ullman ordering, and
  it is switched off by `-fno-order`.
* **Steering** (`hint`): the caller says where it would like the result, so
  `x = a + b` can be a single ADD into x's register. `-fno-steer` turns it
  off and the code generator inserts a MOV instead.

Everything else is the TARA16 instruction set showing through: comparisons
built from SLT/BZ/BN, multiplication and division through runtime routines,
and addresses folded into the 5-bit offset of a load.
"""
from ..ctype import (is_aggregate, is_array_like, is_integer, is_schar,
                     is_scalar, norm, pointer_to)
from ..diag import error_at
from ..node import Node
from .target import (Addr, CALLER_SAVED, LR, NARGREG, NOVAL, SP, Val, bit,
                     ld_op, st_op)


def is_uns(ty):
    # Pointers compare as signed: every TARA16 address is below 0x800.
    """Must this type be compared as unsigned?"""
    return ty.is_unsigned and ty.kind != 'ptr'


class ExprMixin:
    # ---------------------------------------------------------- constants
    """Expressions: values, addresses, calls, comparisons, arithmetic."""
    def is_const(self, n):
        """The value of a constant integer expression, or None."""
        if n is None or n.ty is None:
            return None
        if not (is_integer(n.ty) or n.ty.kind == 'ptr'):
            return None
        k = n.kind
        if k == 'NUM':
            return norm(n.ty, n.val)
        if k == 'CAST':
            a = self.is_const(n.lhs)
            return None if a is None else norm(n.ty, a)
        if k == 'NEG':
            a = self.is_const(n.lhs)
            return None if a is None else norm(n.ty, -a)
        if k == 'BITNOT':
            a = self.is_const(n.lhs)
            return None if a is None else norm(n.ty, ~a)
        if k in ('ADD', 'SUB', 'MUL', 'BITAND', 'BITOR', 'BITXOR'):
            a, b = self.is_const(n.lhs), self.is_const(n.rhs)
            if a is None or b is None:
                return None
            if k == 'ADD':
                v = a + b
            elif k == 'SUB':
                v = a - b
            elif k == 'MUL':
                v = (a & 0xFFFF) * (b & 0xFFFF)
            elif k == 'BITAND':
                v = a & b
            elif k == 'BITOR':
                v = a | b
            else:
                v = a ^ b
            return norm(n.ty, v)
        if k == 'SHL':
            a, b = self.is_const(n.lhs), self.is_const(n.rhs)
            if a is None or b is None or b < 0 or b > 15:
                return None
            return norm(n.ty, a << b)
        return None

    # ------------------------------------------------------- pressure
    def has_call(self, n):
        """Would evaluating n destroy the caller-saved registers?"""
        if n is None:
            return False
        k = n.kind
        if k == 'FUNCALL' or k in ('DIV', 'MOD'):
            return True
        if k == 'MUL' and not self.opt.mul:
            return True
        if k in ('SHL', 'SHR') and self.is_const(n.rhs) is None:
            return True
        if k in ('ASSIGN', 'MEMZERO') and n.ty is not None and \
                is_aggregate(n.ty) and n.ty.size > 16:
            return True
        for sub in (n.lhs, n.rhs, n.cond, n.then, n.els, n.init, n.inc):
            if self.has_call(sub):
                return True
        for lst in (n.body, n.args):
            for sub in (lst or []):
                if self.has_call(sub):
                    return True
        return False

    def noop_cast(self, frm, to):
        """Is this conversion free, needing no instruction at all?"""
        if to.kind == 'void' or is_array_like(frm) or frm.kind == 'func':
            return True
        if to.kind == 'bool':
            return frm.kind == 'bool'
        if to.size == 1:
            return frm.kind == 'bool' or (frm.size == 1 and
                                          frm.is_unsigned == to.is_unsigned)
        return True

    def need(self, n):
        """Temporaries needed to evaluate n (Sethi-Ullman style; never an
        under-estimate for the shapes this back end produces)."""
        def su(a, b):
            """Registers needed for a node with these two subtree costs."""
            v = a + 1 if a == b else max(a, b)
            return max(v, 1)

        if n is None:
            return 0
        if n.ty is not None and (is_integer(n.ty) or n.ty.kind == 'ptr') and \
                self.is_const(n) is not None:
            return 1
        k = n.kind
        if k == 'VAR':
            return 0 if self.reg_var(n) else 1
        if k in ('NUM', 'FUNCALL'):
            return 1                       # a call saves live temporaries itself
        if k == 'CAST':
            if self.noop_cast(n.lhs.ty, n.ty):
                return self.need(n.lhs)
            return max(1, self.need(n.lhs)) + (1 if is_schar(n.ty) else 0)
        if k in ('NEG', 'BITNOT', 'ADDR', 'DEREF'):
            return max(1, self.need(n.lhs))
        if k == 'NOT':
            return max(1, self.need(n.lhs)) + 1
        if k == 'MEMBER':
            return max(1, self.need(n.lhs)) + (1 if n.member.is_bitfield else 0)
        if k == 'ASSIGN':
            if self.reg_var(n.lhs):
                return self.need(n.rhs)
            if n.lhs.kind == 'MEMBER' and n.lhs.member.is_bitfield:
                return su(self.need(n.lhs), self.need(n.rhs)) + 3
            return su(self.need(n.lhs), self.need(n.rhs)) + 1
        if k == 'COMMA':
            return max(self.need(n.lhs), self.need(n.rhs))
        if k == 'COND':
            return max(self.need(n.cond), self.need(n.then), self.need(n.els)) + 1
        if k in ('LOGAND', 'LOGOR'):
            return max(self.need(n.lhs), self.need(n.rhs)) + 1
        if k == 'MUL':
            return su(self.need(n.lhs), self.need(n.rhs)) + (0 if self.opt.mul else 1)
        if k in ('ADD', 'SUB', 'DIV', 'MOD', 'BITAND', 'BITOR', 'BITXOR',
                 'SHL', 'SHR', 'NE'):
            return su(self.need(n.lhs), self.need(n.rhs))
        if k == 'EQ':
            return su(self.need(n.lhs), self.need(n.rhs)) + 1
        if k in ('LT', 'LE'):
            # unsigned: the operands, the 0x8000 constant and a flipped copy
            return su(self.need(n.lhs), self.need(n.rhs)) + \
                (2 if is_uns(n.lhs.ty) else 0)
        return 3

    def reg_var(self, n):
        """The variable behind n, if it lives in a register."""
        if n is not None and n.kind == 'VAR' and n.var.is_local and n.var.reg >= 0:
            return n.var
        return None

    # -------------------------------------------------- spilling and pairs
    def gen_keep(self, node, hint, keep):
        """Evaluate node while the temporaries in `keep` stay alive."""
        keep &= self.pool
        if not keep or self.free_count() >= self.need(node):
            return self.gen(node, hint)
        for r in range(8):
            if keep & bit(r):
                self.push(r)
                self.busy &= ~bit(r)
        if hint is not None and hint >= 0 and (keep & bit(hint)):
            hint = -1
        cse_save = self.cse_var
        if self.cse_reg >= 0 and (keep & bit(self.cse_reg)):
            self.cse_var = None
        v = self.gen(node, hint)
        self.cse_var = cse_save
        if v.reg >= 0 and (keep & bit(v.reg)):
            t = self.alloc_avoid(keep)
            self.e_rr('MOV', t, v.reg)
            self.release(v)
            v = Val(t, True)
        for r in range(7, -1, -1):
            if keep & bit(r):
                self.pop(r)
                self.busy |= bit(r)
        return v

    def gen_pair(self, l, r):
        """Evaluate two operands, the harder one first, and keep both."""
        if self.opt.order:
            r_first = (self.has_call(r) and not self.has_call(l)) or \
                self.need(r) > self.need(l)
        else:
            r_first = False
        if r_first:
            b = self.gen(r, -1)
            a = self.gen_keep(l, -1, bit(b.reg) if b.owned else 0)
        else:
            a = self.gen(l, -1)
            b = self.gen_keep(r, -1, bit(a.reg) if a.owned else 0)
        return a, b

    # ------------------------------------------------------------ addresses
    def strip_nop_casts(self, n):
        """Look through casts that change nothing, to the value beneath."""
        while n.kind == 'CAST' and n.ty.size == 2 and n.lhs.ty.size == 2 and \
                (is_integer(n.lhs.ty) or n.lhs.ty.kind == 'ptr'):
            n = n.lhs
        return n

    def split_index(self, n):
        """(i + c) * s  ->  (i * s, c * s). Returns (node, byte offset) or None."""
        m = self.strip_nop_casts(n)
        if m.kind == 'MUL':
            s = self.is_const(m.rhs)
            if s is not None:
                x = self.strip_nop_casts(m.lhs)
                if x.kind in ('ADD', 'SUB'):
                    k = self.is_const(x.rhs)
                    if k is not None:
                        off = norm_i16((k if x.kind == 'ADD' else -k) * s)
                        return mk_binary('MUL', x.lhs, m.rhs, m.ty), off
                if x.kind == 'ADD':
                    k = self.is_const(x.lhs)
                    if k is not None:
                        return mk_binary('MUL', x.rhs, m.rhs, m.ty), norm_i16(k * s)
        if m.kind in ('ADD', 'SUB'):
            k = self.is_const(m.rhs)
            if k is not None:
                return m.lhs, norm_i16(k if m.kind == 'ADD' else -k)
        return None

    def addr_keep(self, node, keep, is_ptr):
        """Form an address while the temporaries in `keep` stay alive."""
        keep &= self.pool
        if not keep or self.free_count() >= self.need(node):
            return self.gen_ptr_addr(node) if is_ptr else self.gen_addr(node)
        for r in range(8):
            if keep & bit(r):
                self.push(r)
                self.busy &= ~bit(r)
        cse_save = self.cse_var
        if self.cse_reg >= 0 and (keep & bit(self.cse_reg)):
            self.cse_var = None
        a = self.gen_ptr_addr(node) if is_ptr else self.gen_addr(node)
        self.cse_var = cse_save
        if a.kind == 'reg' and (keep & bit(a.reg)):
            t = self.alloc_avoid(keep)
            self.e_rr('MOV', t, a.reg)
            if a.owned:
                self.free_reg(a.reg)
            a.reg = t
            a.owned = True
        for r in range(7, -1, -1):
            if keep & bit(r):
                self.pop(r)
                self.busy |= bit(r)
        return a

    def gen_addr_keep(self, node, keep):
        """Form an lvalue address, keeping some registers alive."""
        return self.addr_keep(node, keep, False)

    def ptr_plus_index(self, a, idx):
        """An address plus an index already in a register."""
        if a.kind == 'sp':
            d = self.take_dst(-1, idx, None)
            self.e_rrr('ADD', d.reg, idx.reg, SP)
            return Addr('reg', d.reg, True, off=a.off + self.depth)
        if a.kind == 'sym':
            t = self.alloc_avoid(bit(idx.reg) if idx.owned else 0)
            self.e_la(t, a.sym, a.off)
            d = self.take_dst(-1, Val(t, True), idx)
            self.e_rrr('ADD', d.reg, t, idx.reg)
            return Addr('reg', d.reg, True, off=0)
        base = Val(a.reg, a.owned)
        d = self.take_dst(-1, base, idx)
        self.e_rrr('ADD', d.reg, a.reg, idx.reg)
        return Addr('reg', d.reg, True, off=a.off)

    def gen_ptr_addr(self, e):
        """The address a pointer-valued expression points to, with constant
        parts folded into the offset."""
        if is_array_like(e.ty) or e.ty.kind == 'func':
            return self.gen_addr(e)
        k = e.kind
        if k == 'ADDR':
            return self.gen_addr(e.lhs)
        if k == 'CAST' and (e.lhs.ty.kind == 'ptr' or is_array_like(e.lhs.ty)) and \
                e.ty.kind == 'ptr':
            return self.gen_ptr_addr(e.lhs)
        if k == 'ADD' and e.lhs.ty.base:
            c = self.is_const(e.rhs)
            if c is not None:
                a = self.gen_ptr_addr(e.lhs)
                a.off += norm_i16(c)
                return a
            # base + i*2 with i in a register: add i twice, saving a register
            ix = self.strip_nop_casts(e.rhs)
            if ix.kind == 'MUL' and self.is_const(ix.rhs) == 2 and \
                    self.reg_var(self.strip_nop_casts(ix.lhs)) and \
                    not self.has_call(e.lhs):
                ri = self.strip_nop_casts(ix.lhs).var.reg
                a = self.gen_ptr_addr(e.lhs)
                if a.kind == 'sym' or (a.kind == 'reg' and a.owned):
                    if a.kind == 'sym':
                        reg = self.alloc_reg()
                        self.e_la(reg, a.sym, a.off)
                        r = Addr('reg', reg, True, off=0)
                    else:
                        r = Addr('reg', a.reg, True, off=a.off)
                    self.e_rrr('ADD', r.reg, r.reg, ri)
                    self.e_rrr('ADD', r.reg, r.reg, ri)
                    return r
                idx = self.gen(e.rhs, -1)
                return self.ptr_plus_index(a, idx)
            split = self.split_index(e.rhs)
            if split and split[1] != 0:
                sub, coff = split
                tmp = Node('ADD', e.tok, e.ty)
                tmp.lhs, tmp.rhs = e.lhs, sub
                a = self.gen_ptr_addr(tmp)
                a.off += coff
                return a
            if self.opt.order and self.need(e.rhs) > self.need(e.lhs):
                idx = self.gen(e.rhs, -1)
                a = self.addr_keep(e.lhs, bit(idx.reg) if idx.owned else 0, True)
            else:
                a = self.gen_ptr_addr(e.lhs)
                idx = self.gen_keep(e.rhs, -1, self.addr_regs(a))
            return self.ptr_plus_index(a, idx)
        if k == 'SUB' and e.lhs.ty.base:
            c = self.is_const(e.rhs)
            if c is not None:
                a = self.gen_ptr_addr(e.lhs)
                a.off -= norm_i16(c)
                return a
        if k == 'VAR' and self.reg_var(e):
            return Addr('reg', e.var.reg, False)
        v = self.gen(e, -1)
        return Addr('reg', v.reg, v.owned)

    def gen_addr(self, node):
        """The address of an lvalue (or of an aggregate-valued expression)."""
        k = node.kind
        if k == 'VAR':
            var = node.var
            if var.is_local:
                if var.reg >= 0:
                    error_at(node.tok.pos, 'internal: address of a register variable')
                return Addr('sp', off=var.slot)
            if var is self.cse_var and self.cse_reg >= 0:
                return Addr('reg', self.cse_reg, False)
            if var.is_function:
                return Addr('sym', sym=f'__ind_{var.name}')
            return Addr('sym', sym=var.name)
        if k == 'DEREF':
            return self.gen_ptr_addr(node.lhs)
        if k == 'COMMA':
            self.gen_void(node.lhs)
            return self.gen_addr(node.rhs)
        if k == 'MEMBER':
            a = self.gen_addr(node.lhs)
            a.off += node.member.offset
            return a
        if k == 'FUNCALL' and node.ret_buffer:
            v = self.gen_call(node, -1)
            self.release(v)
            return Addr('sp', off=node.ret_buffer.slot)
        if k in ('ASSIGN', 'COND', 'STMT_EXPR') and is_aggregate(node.ty):
            v = self.gen(node, -1)
            return Addr('reg', v.reg, v.owned)
        if k == 'CAST' and is_aggregate(node.ty):
            return self.gen_addr(node.lhs)
        error_at(node.tok.pos, 'not an lvalue')

    def copy_bytes(self, dst, src, ty):
        """Copy ty.size bytes; both addresses are consumed."""
        size = ty.size
        if size > 16:
            s = self.addr_to_reg(src, -1)
            d = self.addr_to_reg(dst, -1)
            self.gen_libcall3('__memcpy', d, s, size)
            return
        s = self.reachable(src, size)
        d = self.reachable(dst, size)
        t = self.alloc_reg()
        words = ty.align >= 2 and size % 2 == 0
        step = 2 if words else 1
        for i in range(0, size, step):
            si, di = s.copy(), d.copy()
            si.off += i
            di.off += i
            self.mem_access('LDW' if words else 'LDB', t, si)
            self.mem_access('STW' if words else 'STB', t, di)
        self.free_reg(t)
        self.release_addr(s)
        self.release_addr(d)

    # ---------------------------------------------------------------- calls
    def save_live(self, live):
        """Push the caller-saved registers that are holding something."""
        for r in range(8):
            if live & bit(r):
                self.push(r)
        self.busy &= ~live

    def restore_live(self, live):
        """Pop the registers a call was allowed to destroy."""
        self.busy |= live
        for r in range(7, -1, -1):
            if live & bit(r):
                self.pop(r)

    def call_result(self, hint, live):
        """Where a call's result goes: it arrives in R0."""
        if self.hint_usable(hint) and not (live & bit(hint)):
            d = hint
        elif not (live & bit(0)):
            d = 0
        else:
            d = self.alloc_avoid(live)
        self.e_rr('MOV', d, 0)
        return self.claim(d)

    def move_args(self, vals, n):
        """Move up to three values into R0, R1, R2 (a parallel move)."""
        done = [vals[i].reg == i for i in range(n)]
        for _ in range(6):
            progress = False
            for i in range(n):
                if done[i]:
                    continue
                blocked = any(not done[j] and j != i and vals[j].reg == i
                              for j in range(n))
                if not blocked:
                    self.e_rr('MOV', i, vals[i].reg)
                    vals[i].reg = i
                    done[i] = True
                    progress = True
            if not progress:
                for i in range(n):            # a cycle: break it through R6
                    if not done[i]:
                        self.e_rr('MOV', LR, vals[i].reg)
                        vals[i].reg = LR
                        break
            if all(done[:n]):
                break

    def gen_libcall(self, name, a, b, hint):
        """R0 = name(a, b); a and b are consumed."""
        self.made_call = True
        opnd = (bit(a.reg) if a.owned else 0) | (bit(b.reg) if b.owned else 0)
        live = self.busy & CALLER_SAVED & ~opnd
        self.save_live(live)
        args = [a, b]
        self.release(a)
        self.release(b)
        self.move_args(args, 2)
        self.e_j('CALL', name)
        d = self.call_result(hint, live)
        self.restore_live(live)
        return d

    def gen_libcall3(self, name, a, b, n):
        """Call a runtime routine with two arguments and a count."""
        self.made_call = True
        opnd = (bit(a.reg) if a.owned else 0) | (bit(b.reg) if b.owned else 0)
        live = self.busy & CALLER_SAVED & ~opnd
        self.save_live(live)
        args = [a, b]
        self.release(a)
        self.release(b)
        self.move_args(args, 2)
        self.load_const(2, n)
        self.e_j('CALL', name)
        self.restore_live(live)

    def is_direct_call(self, node):
        """Is this a call to a named function rather than a pointer?"""
        return node.lhs.kind == 'VAR' and node.lhs.var.ty.kind == 'func'

    def gen_arg(self, arg, hint, keep):
        """Evaluate one argument, into its register or onto the stack."""
        if is_aggregate(arg.ty):
            if keep and self.free_count() < 3:
                return self.gen_keep(arg, hint, keep)
            a = self.gen_addr(arg)
            return self.addr_to_reg(a, hint)
        return self.gen_keep(arg, hint, keep)

    def gen_call(self, node, hint):
        """A call: save what must survive, place the arguments, CALL."""
        self.made_call = True
        direct = self.is_direct_call(node)
        args = list(node.args or [])
        if node.ret_buffer:
            hidden = Node('ADDR', node.tok, pointer_to(node.ret_buffer.ty))
            inner = Node('VAR', node.tok, node.ret_buffer.ty)
            inner.var = node.ret_buffer
            hidden.lhs = inner
            args = [hidden] + args

        # 1. caller-saved temporaries that must survive the call
        live = self.busy & CALLER_SAVED
        self.save_live(live)
        cse_save = self.cse_var
        if self.cse_reg >= 0 and (live & bit(self.cse_reg)):
            self.cse_var = None

        # 2. stack arguments, right to left
        nstack = 0
        for i in range(len(args) - 1, NARGREG - 1, -1):
            v = self.gen_arg(args[i], -1, 0)
            self.push(v.reg)
            self.release(v)
            nstack += 1

        # 3. the target of an indirect call (consumed by __icall and the stub)
        if not direct:
            v = self.gen(node.lhs, -1)
            self.push(v.reg)
            self.release(v)

        # 4. register arguments, the ones containing calls first
        nreg = min(len(args), NARGREG)
        loaded = 0
        for first_pass in (True, False):
            for i in range(nreg):
                if first_pass != self.has_call(args[i]):
                    continue
                v = self.gen_arg(args[i], i, loaded)
                if v.reg != i:
                    self.e_rr('MOV', i, v.reg)
                    self.release(v)
                self.busy |= bit(i)
                loaded |= bit(i)

        # 5. the call itself
        if direct:
            self.e_j('CALL', node.lhs.var.name)
        else:
            self.e_j('CALL', '__icall')
            self.icall_used = True
        self.busy &= ~loaded

        # 6. remove stack arguments
        if nstack:
            self.add_imm(SP, 2 * nstack)
            self.depth -= 2 * nstack
        if not direct:
            self.depth -= 2

        # 7. the result
        self.cse_var = cse_save
        if node.ret_buffer:
            self.restore_live(live)
            return self.addr_to_reg(Addr('sp', off=node.ret_buffer.slot), hint)
        if node.ty.kind != 'void':
            res = self.call_result(hint, live)
            self.restore_live(live)
            return res
        self.restore_live(live)
        return NOVAL

    # ----------------------------------------------------------- conversions
    def convert(self, v, frm, to, hint):
        """Emit the instructions one conversion needs, if any."""
        if to.kind == 'void':
            return v
        if is_array_like(frm) or frm.kind == 'func':
            return v                        # already an address
        if to.kind == 'bool':
            if frm.kind == 'bool':
                return v
            d = self.make_mutable(v, hint)
            l = self.new_label()
            self.e_br('BZ', d.reg, l)
            self.e_ri('LIL', d.reg, 1)
            self.emit_label(l)
            return d
        if to.size == 1:
            if frm.kind == 'bool':
                return v
            if to.is_unsigned:
                if frm.size == 1 and frm.is_unsigned:
                    return v
                d = self.make_mutable(v, hint)
                self.e_ri('SHL', d.reg, 8)
                self.e_ri('SHR', d.reg, 8)
                return d
            if frm.size == 1 and not frm.is_unsigned:
                return v
            d = self.make_mutable(v, hint)
            if frm.size != 1:
                self.e_ri('SHL', d.reg, 8)
                self.e_ri('SHR', d.reg, 8)
            self.sext8(d.reg)
            return d
        return v                            # 16-bit targets need nothing

    # ---------------------------------------------------------- comparisons
    def branch_nz(self, r, sense, label):
        """Branch to label if r is non-zero (sense) or zero (not sense).
        TARA16 has BZ but no 'branch if not zero', hence the JMP."""
        if not sense:
            self.e_br('BZ', r, label)
            return
        skip = self.new_label()
        self.e_br('BZ', r, skip)
        self.e_j('JMP', label)
        self.emit_label(skip)

    def ult(self, a, b, hint):
        """d = (a <u b): flip both sign bits and use the signed SLT."""
        k = self.alloc_avoid(0)
        self.e_ri('LIL', k, 0)
        self.e_ri('LIH', k, 0x80)
        x = a.reg if a.owned else self.alloc_reg()
        self.e_rrr('XOR', x, a.reg, k)
        y = b.reg if b.owned else k
        self.e_rrr('XOR', y, b.reg, k)
        if y != k:
            self.free_reg(k)
        xv, yv = Val(x, True), Val(y, True)
        d = self.take_dst(hint, xv, yv)
        self.e_rrr('SLT', d.reg, x, y)
        return d

    def lt_val(self, a, b, uns, hint):
        """Compute a < b as a 1 or a 0 in a register."""
        if uns:
            return self.ult(a, b, hint)
        d = self.take_dst(hint, a, b)
        self.e_rrr('SLT', d.reg, a.reg, b.reg)
        return d

    def branch_lt(self, l, r, uns, sense, label):
        """Jump to label iff (l < r) == sense."""
        k = self.is_const(r)
        if k == 0:
            if uns:                          # x <u 0 is never true
                self.gen_void(l)
                if not sense:
                    self.e_j('JMP', label)
                return
            v = self.gen(l, -1)
            if sense:
                self.e_br('BN', v.reg, label)
            else:
                skip = self.new_label()
                self.e_br('BN', v.reg, skip)
                self.e_j('JMP', label)
                self.emit_label(skip)
            self.release(v)
            return
        kl = self.is_const(l)
        if kl == 0:
            v = self.gen(r, -1)
            if uns:                          # 0 <u y  <=>  y != 0
                self.branch_nz(v.reg, sense, label)
            elif sense:                      # 0 < y
                skip = self.new_label()
                self.e_br('BZ', v.reg, skip)
                self.e_br('BN', v.reg, skip)
                self.e_j('JMP', label)
                self.emit_label(skip)
            else:
                self.e_br('BZ', v.reg, label)
                self.e_br('BN', v.reg, label)
            self.release(v)
            return
        if uns and k is not None and 0 < (k & 0xFFFF) <= 0x7FFF:
            # x <u c with a small c:  x >= 0 (signed) and x <s c
            v = self.gen(l, -1)
            t = self.alloc_avoid(bit(v.reg) if v.owned else 0)
            skip = self.new_label()
            self.e_br('BN', v.reg, skip if sense else label)
            self.load_const(t, k)
            self.e_rrr('SLT', t, v.reg, t)
            self.release(v)
            if sense:
                self.e_ri('ADDI', t, -1)
                self.e_br('BZ', t, label)
            else:
                self.e_br('BZ', t, label)
            self.free_reg(t)
            self.emit_label(skip)
            return
        if uns and kl is not None and (kl & 0xFFFF) < 0x7FFF:
            one = Node('NUM', r.tok, r.ty)     # c <u x  <=>  !(x <u c+1)
            one.val = (kl & 0xFFFF) + 1
            self.branch_lt(r, one, uns, not sense, label)
            return
        a, b = self.gen_pair(l, r)
        t = self.lt_val(a, b, uns, -1)
        if sense:
            m = self.make_mutable(t, -1)
            self.e_ri('ADDI', m.reg, -1)
            self.e_br('BZ', m.reg, label)
            self.release(m)
        else:
            self.e_br('BZ', t.reg, label)
            self.release(t)

    def gen_diff(self, l, r):
        """A register holding (l - r), which is zero iff they are equal."""
        k = self.is_const(r)
        if k is not None and (k & 0xFFFF) == 0:
            return self.gen(l, -1)
        kl = self.is_const(l)
        if kl is not None and (kl & 0xFFFF) == 0:
            return self.gen(r, -1)
        if k is not None:
            c = norm_i16(k)
            if -127 <= c <= 128:
                v = self.gen(l, -1)
                if v.owned:
                    self.e_ri('ADDI', v.reg, -c)
                    return v
                t = self.alloc_reg()
                self.load_const(t, k)
                self.e_rrr('SUB', t, v.reg, t)
                return Val(t, True)
        a, b = self.gen_pair(l, r)
        d = self.take_dst(-1, a, b)
        self.e_rrr('SUB', d.reg, a.reg, b.reg)
        return d

    def branch_eq(self, l, r, sense, label):
        """Jump to label iff (l == r) == sense."""
        d = self.gen_diff(l, r)
        if sense:
            self.e_br('BZ', d.reg, label)
        else:
            skip = self.new_label()
            self.e_br('BZ', d.reg, skip)
            self.e_j('JMP', label)
            self.emit_label(skip)
        self.release(d)

    def gen_branch(self, node, sense, label):
        """Jump to label iff (node != 0) == sense, without computing a
        true/false value first."""
        k = self.is_const(node)
        if k is not None:
            if (k != 0) == sense:
                self.e_j('JMP', label)
            return
        kind = node.kind
        if kind == 'NOT':
            self.gen_branch(node.lhs, not sense, label)
            return
        if kind == 'LOGAND':
            if not sense:
                self.gen_branch(node.lhs, False, label)
                self.gen_branch(node.rhs, False, label)
            else:
                skip = self.new_label()
                self.gen_branch(node.lhs, False, skip)
                self.gen_branch(node.rhs, True, label)
                self.emit_label(skip)
            return
        if kind == 'LOGOR':
            if sense:
                self.gen_branch(node.lhs, True, label)
                self.gen_branch(node.rhs, True, label)
            else:
                skip = self.new_label()
                self.gen_branch(node.lhs, True, skip)
                self.gen_branch(node.rhs, False, label)
                self.emit_label(skip)
            return
        if kind == 'COMMA':
            self.gen_void(node.lhs)
            self.gen_branch(node.rhs, sense, label)
            return
        if kind == 'CAST':
            frm, to = node.lhs.ty, node.ty
            if (is_integer(frm) or frm.kind == 'ptr') and \
                    (to.kind == 'bool' or to.size >= frm.size):
                self.gen_branch(node.lhs, sense, label)
                return
        if kind == 'EQ':
            self.branch_eq(node.lhs, node.rhs, sense, label)
            return
        if kind == 'NE':
            self.branch_eq(node.lhs, node.rhs, not sense, label)
            return
        if kind == 'LT':
            self.branch_lt(node.lhs, node.rhs, is_uns(node.lhs.ty), sense, label)
            return
        if kind == 'LE':                      # a <= b  <=>  !(b < a)
            self.branch_lt(node.rhs, node.lhs, is_uns(node.lhs.ty), not sense, label)
            return
        v = self.gen(node, -1)
        self.branch_nz(v.reg, sense, label)
        self.release(v)

    def bool_by_branch(self, node, hint):
        """Make a 1 or 0 out of a condition that is generated as branches."""
        hint_ok = hint is not None and hint >= 0 and self.in_pool(hint) and \
            self.hint_usable(hint)
        if self.free_count() > self.need(node):
            d = self.claim(hint) if hint_ok else Val(self.alloc_reg(), True)
            l = self.new_label()
            self.e_ri('LIL', d.reg, 1)
            self.gen_branch(node, True, l)
            self.e_ri('LIL', d.reg, 0)
            self.emit_label(l)
            return d
        t, end = self.new_label(), self.new_label()
        self.gen_branch(node, True, t)
        d = self.claim(hint) if hint_ok else Val(self.alloc_reg(), True)
        self.e_ri('LIL', d.reg, 0)
        self.e_j('JMP', end)
        self.emit_label(t)
        self.e_ri('LIL', d.reg, 1)
        self.emit_label(end)
        return d

    def gen_compare(self, node, hint):
        """Compute a comparison as a value, when a branch will not do."""
        l, r = node.lhs, node.rhs
        uns = is_uns(l.ty)
        kind = node.kind
        if kind == 'LT':
            if not uns and self.is_const(r) == 0:       # x < 0  ->  x >> 15
                d = self.make_mutable(self.gen(l, hint), hint)
                self.e_ri('SHR', d.reg, 15)
                return d
            a, b = self.gen_pair(l, r)
            return self.lt_val(a, b, uns, hint)
        if kind == 'LE':                                 # 1 - (r < l)
            a, b = self.gen_pair(r, l)
            d = self.lt_val(a, b, uns, hint)
            m = self.make_mutable(d, hint)
            self.e_ri('ADDI', m.reg, -1)
            self.e_ri('SHR', m.reg, 15)
            return m
        if kind == 'NE':
            d = self.make_mutable(self.gen_diff(l, r), hint)
            lab = self.new_label()
            self.e_br('BZ', d.reg, lab)
            self.e_ri('LIL', d.reg, 1)
            self.emit_label(lab)
            return d
        # EQ
        t = self.gen_diff(l, r)
        if self.hint_usable(hint) and hint != t.reg:
            d = self.claim(hint)
        else:
            d = Val(self.alloc_avoid(bit(t.reg) if t.owned else 0), True)
        lab = self.new_label()
        self.e_ri('LIL', d.reg, 1)
        self.e_br('BZ', t.reg, lab)
        self.e_ri('LIL', d.reg, 0)
        self.emit_label(lab)
        self.release(t)
        return d

    # ---------------------------------------------------------- arithmetic
    def mul_const_shift_add(self, v, c, hint):
        """x * c with shifts and additions, or None if that is not worth it."""
        c &= 0xFFFF
        pc = bin(c).count('1')
        if c == 0 or pc > 3:
            return None
        lz = (c & -c).bit_length() - 1
        if pc == 1:
            if lz <= 2:
                d = self.take_dst(hint, v, None)
                self.e_rrr('ADD', d.reg, v.reg, v.reg)
                if lz == 2:
                    self.e_rrr('ADD', d.reg, d.reg, d.reg)
                return d
            d = self.make_mutable(v, hint)
            self.e_ri('SHL', d.reg, lz)
            return d
        if self.opt.mul:
            return None                      # with MUL, LIL+MUL is never worse
        # x*c = sum of x<<bit, accumulated from the lowest bit
        if v.owned:
            x = v
        else:
            t = self.alloc_reg()
            self.e_rr('MOV', t, v.reg)
            x = Val(t, True)
        acc = self.alloc_avoid(bit(x.reg))
        shifted = 0
        first = True
        for b in range(16):
            if not (c & (1 << b)):
                continue
            if b > shifted:
                self.e_ri('SHL', x.reg, b - shifted)
                shifted = b
            if first:
                self.e_rr('MOV', acc, x.reg)
                first = False
            else:
                self.e_rrr('ADD', acc, acc, x.reg)
        self.release(x)
        a = Val(acc, True)
        if self.hint_usable(hint) and hint != acc:
            self.e_rr('MOV', hint, acc)
            self.release(a)
            a = self.claim(hint)
        return a

    def gen_mul(self, node, hint):
        """Multiply: a shift, an inline sequence, MUL, or the runtime."""
        l, r = node.lhs, node.rhs
        if self.is_const(l) is not None and self.is_const(r) is None:
            l, r = r, l
        k = self.is_const(r)
        if k is not None:
            c = k & 0xFFFF
            if c == 0:
                self.gen_void(l)
                d = self.claim(hint) if self.hint_usable(hint) else \
                    Val(self.alloc_reg(), True)
                self.e_ri('LIL', d.reg, 0)
                return d
            if c == 1:
                return self.gen(l, hint)
            v = self.gen(l, hint if log2_exact(c) >= 0 else -1)
            out = self.mul_const_shift_add(v, c, hint)
            if out is not None:
                return out
            if self.opt.mul:
                t = self.alloc_reg()
                self.load_const(t, c)
                tv = Val(t, True)
                d = self.take_dst(hint, v, tv)
                self.e_rrr('MUL', d.reg, v.reg, t)
                if t != d.reg:
                    self.free_reg(t)
                return d
            t = self.alloc_reg()
            self.load_const(t, c)
            return self.gen_libcall('__mulhi3', v, Val(t, True), hint)
        a, b = self.gen_pair(l, r)
        if not self.opt.mul:
            return self.gen_libcall('__mulhi3', a, b, hint)
        d = self.take_dst(hint, a, b)
        self.e_rrr('MUL', d.reg, a.reg, b.reg)
        return d

    def gen_divmod(self, node, hint):
        """Divide or take a remainder; always a runtime call."""
        l, r = node.lhs, node.rhs
        uns = is_uns(l.ty) or l.ty.kind == 'ptr'
        k = self.is_const(r)
        if k is not None:
            c = k & 0xFFFF
            sh = log2_exact(c)
            if c == 1:
                if node.kind == 'DIV':
                    return self.gen(l, hint)
                self.gen_void(l)
                d = self.claim(hint) if self.hint_usable(hint) else \
                    Val(self.alloc_reg(), True)
                self.e_ri('LIL', d.reg, 0)
                return d
            # an exact pointer difference divides by the element size
            ptrdiff = (node.kind == 'DIV' and l.kind == 'SUB' and
                       l.lhs.ty.base and l.rhs.ty.base)
            if sh > 0 and (uns or ptrdiff):
                d = self.make_mutable(self.gen(l, hint), hint)
                if node.kind == 'DIV':
                    if uns:
                        self.e_ri('SHR', d.reg, sh)
                    else:
                        self.sra_inplace(d.reg, sh)
                else:
                    self.e_ri('SHL', d.reg, 16 - sh)
                    self.e_ri('SHR', d.reg, 16 - sh)
                return d
        name = ('__udivhi3' if uns else '__divhi3') if node.kind == 'DIV' else \
               ('__umodhi3' if uns else '__modhi3')
        a, b = self.gen_pair(l, r)
        return self.gen_libcall(name, a, b, hint)

    def gen_shift(self, node, hint):
        """Shift left or right, by a constant or by a register."""
        l, r = node.lhs, node.rhs
        uns = is_uns(l.ty) or l.ty.kind == 'ptr'
        k = self.is_const(r)
        if k is not None:
            c = int(k)
            if c == 0:
                return self.gen(l, hint)
            if c >= 16 or c < 0:              # undefined in C: do what the
                if node.kind == 'SHR' and not uns:   # hardware would do
                    d = self.make_mutable(self.gen(l, hint), hint)
                    self.sra_inplace(d.reg, 15)
                    return d
                self.gen_void(l)
                d = self.claim(hint) if self.hint_usable(hint) else \
                    Val(self.alloc_reg(), True)
                self.e_ri('LIL', d.reg, 0)
                return d
            if node.kind == 'SHL' and c <= 2:
                v = self.gen(l, hint)
                d = self.take_dst(hint, v, None)
                self.e_rrr('ADD', d.reg, v.reg, v.reg)
                if c == 2:
                    self.e_rrr('ADD', d.reg, d.reg, d.reg)
                return d
            d = self.make_mutable(self.gen(l, hint), hint)
            if node.kind == 'SHL':
                self.e_ri('SHL', d.reg, c)
            elif uns:
                self.e_ri('SHR', d.reg, c)
            else:
                self.sra_inplace(d.reg, c)
            return d
        a, b = self.gen_pair(l, r)
        name = '__ashlhi3' if node.kind == 'SHL' else \
               ('__lshrhi3' if uns else '__ashrhi3')
        return self.gen_libcall(name, a, b, hint)

    def gen_arith(self, node, hint):
        """+ - & | ^, with constants folded into ADDI and friends."""
        l, r = node.lhs, node.rhs
        kind = node.kind
        comm = kind != 'SUB'
        if comm and self.is_const(l) is not None and self.is_const(r) is None:
            l, r = r, l
        k = self.is_const(r)
        if k is not None:
            c = k & 0xFFFF
            sc = norm_i16(c)
            if kind == 'SUB':
                kind = 'ADD'
                sc = -sc
                c = (-c) & 0xFFFF
                if sc == 32768:
                    sc = -32768
            if kind == 'ADD' and c == 0:
                return self.gen(l, hint)
            if kind in ('BITOR', 'BITXOR') and c == 0:
                return self.gen(l, hint)
            if kind == 'BITAND' and c == 0xFFFF:
                return self.gen(l, hint)
            if kind == 'ADD' and -256 <= sc <= 254:
                d = self.make_mutable(self.gen(l, hint), hint)
                self.add_imm(d.reg, sc)
                return d
            if kind == 'BITAND' and c == 0x00FF:
                d = self.make_mutable(self.gen(l, hint), hint)
                self.e_ri('SHL', d.reg, 8)
                self.e_ri('SHR', d.reg, 8)
                return d
            if kind == 'BITAND' and c == 0xFF00:
                d = self.make_mutable(self.gen(l, hint), hint)
                self.e_ri('SHR', d.reg, 8)
                self.e_ri('SHL', d.reg, 8)
                return d
            if kind == 'BITXOR' and c == 0xFFFF:
                v = self.gen(l, hint)
                d = self.take_dst(hint, v, None)
                self.e_rr('NOT', d.reg, v.reg)
                return d
            v = self.gen(l, -1)
            t = self.alloc_reg()
            self.load_const(t, c)
            tv = Val(t, True)
            d = self.take_dst(hint, v, tv)
            self.e_rrr({'ADD': 'ADD', 'BITAND': 'AND', 'BITOR': 'OR',
                        'BITXOR': 'XOR'}[kind], d.reg, v.reg, t)
            if t != d.reg:
                self.free_reg(t)
            return d
        if kind == 'SUB' and self.is_const(l) is not None and \
                (self.is_const(l) & 0xFFFF) == 0:
            v = self.gen(r, -1)                # 0 - x
            d = self.take_dst(hint, v, None)
            self.e_rr('NOT', d.reg, v.reg)
            self.e_ri('ADDI', d.reg, 1)
            return d
        a, b = self.gen_pair(l, r)
        d = self.take_dst(hint, a, b)
        op = {'ADD': 'ADD', 'SUB': 'SUB', 'BITAND': 'AND', 'BITOR': 'OR',
              'BITXOR': 'XOR'}[kind]
        self.e_rrr(op, d.reg, a.reg, b.reg)
        return d

    # ------------------------------------------------------------ bitfields
    def bitfield_extract(self, v, mem, hint):
        """Shift and mask a bit-field out of the word it shares."""
        d = self.make_mutable(v, hint)
        w = mem.ty.size * 8
        left = w - mem.bit_width - mem.bit_offset
        if w == 8:
            left += 8                    # a byte container sits in a 16-bit register
        if left:
            self.e_ri('SHL', d.reg, left)
        right = 16 - mem.bit_width
        if mem.ty.is_unsigned:
            self.e_ri('SHR', d.reg, right)
        else:
            self.sra_inplace(d.reg, right)
        return d

    # ----------------------------------------------------------- assignment
    def refs_var(self, n, var):
        """Does this expression mention that variable anywhere?"""
        if n is None:
            return False
        if n.kind == 'VAR' and n.var is var:
            return True
        for sub in (n.lhs, n.rhs, n.cond, n.then, n.els, n.init, n.inc):
            if self.refs_var(sub, var):
                return True
        for lst in (n.body, n.args):
            for sub in (lst or []):
                if self.refs_var(sub, var):
                    return True
        return False

    def global_base(self, n):
        """The global variable an lvalue is reached through, if any."""
        while n.kind == 'MEMBER':
            n = n.lhs
        if n.kind == 'VAR' and not n.var.is_local and not n.var.is_function:
            return n.var
        return None

    def gen_assign(self, node, hint, want):
        """A store, with the address formed once and the value steered."""
        lhs, rhs = node.lhs, node.rhs
        ty = lhs.ty

        if is_aggregate(ty):                   # struct copy
            src = self.gen_addr(rhs)
            dst = self.gen_addr_keep(lhs, self.addr_regs(src))
            if want:
                d = self.addr_to_reg(dst, -1)
                self.copy_bytes(Addr('reg', d.reg, False), src, ty)
                return d
            self.copy_bytes(dst, src, ty)
            return NOVAL

        rv = self.reg_var(lhs)
        if rv:                                  # a variable in a register
            steer = rv.reg
            if self.live_regs is not None and rv.live_lo > 2 * self.cur_tick and \
                    (self.live_during & bit(rv.reg)):
                steer = -1      # a variable dying here still sits in that register
            v = self.gen(rhs, steer)
            if v.reg != rv.reg:
                self.e_rr('MOV', rv.reg, v.reg)
                self.release(v)
            return Val(rv.reg, False)

        if lhs.kind == 'MEMBER' and lhs.member.is_bitfield:
            return self.gen_bitfield_assign(node, hint, want)

        # a global read-modify-write: form the address once
        g = self.global_base(lhs)
        if self.opt.cse and g and self.refs_var(rhs, g) and self.cse_var is None:
            r = self.alloc_reg()
            self.e_la(r, g.name, 0)
            self.cse_var, self.cse_reg = g, r
            v = self.gen_keep(rhs, hint if want else -1, bit(r))
            a = self.gen_addr(lhs)              # uses cse_reg as its base
            self.cse_var, self.cse_reg = None, -1
            self.mem_access(st_op(ty), v.reg, a)
            self.free_reg(r)
            if want:
                return v
            self.release(v)
            return NOVAL

        # A byte store truncates, so narrowing casts in front of it are free.
        # Every cast between integer types leaves the low byte alone, so a
        # whole chain of them can go -- except a cast to _Bool, which turns any
        # nonzero value into 1, and a _Bool destination, which must hold 0 or 1.
        val = rhs
        if not want and ty.size == 1 and ty.kind != 'bool':
            while val.kind == 'CAST' and is_integer(val.ty) and \
                    val.ty.kind != 'bool' and is_integer(val.lhs.ty):
                val = val.lhs

        if self.need(lhs) > self.need(val) or \
                (self.has_call(lhs) and not self.has_call(val)):
            a = self.gen_addr(lhs)
            v = self.gen_keep(val, hint if want else -1, self.addr_regs(a))
        else:
            v = self.gen(val, hint if want else -1)
            a = self.gen_addr_keep(lhs, bit(v.reg) if v.owned else 0)
        self.mem_access(st_op(ty), v.reg, a)
        self.release_addr(a)
        if want:
            return v
        self.release(v)
        return NOVAL

    def gen_bitfield_assign(self, node, hint, want):
        """container = (container & ~(mask << off)) | ((value & mask) << off)"""
        lhs, rhs = node.lhs, node.rhs
        mem = lhs.member
        cty = mem.ty
        mask = (1 << mem.bit_width) - 1
        v = self.gen(rhs, -1)
        a = self.reachable(self.gen_addr_keep(lhs, bit(v.reg) if v.owned else 0),
                           cty.size)
        keep = self.addr_regs(a)
        nv = v if v.owned else self.make_mutable(v, -1)
        n = nv.reg
        keep |= bit(n)
        m = self.alloc_avoid(keep)
        self.load_const(m, mask)
        self.e_rrr('AND', n, n, m)
        self.free_reg(m)
        if mem.bit_offset:
            self.e_ri('SHL', n, mem.bit_offset)
        o = self.alloc_avoid(keep)
        self.mem_access(ld_op(cty), o, a.copy())
        m = self.alloc_avoid(keep | bit(o))
        self.load_const(m, ~(mask << mem.bit_offset) & 0xFFFF)
        self.e_rrr('AND', o, o, m)
        self.free_reg(m)
        self.e_rrr('OR', o, o, n)
        self.mem_access(st_op(cty), o, a.copy())
        self.free_reg(o)
        if not want:
            self.free_reg(n)
            self.release_addr(a)
            return NOVAL
        left = 16 - mem.bit_width - mem.bit_offset
        if left:
            self.e_ri('SHL', n, left)
        if mem.ty.is_unsigned:
            self.e_ri('SHR', n, 16 - mem.bit_width)
        else:
            self.sra_inplace(n, 16 - mem.bit_width)
        self.release_addr(a)
        return Val(n, True)

    def gen_memzero(self, var):
        """Fill a variable with zeros, for a partial initializer."""
        if var.reg >= 0:
            self.e_ri('LIL', var.reg, 0)
            return
        size = var.ty.size
        if size > 32:
            a = Addr('sp', off=var.slot)
            d = self.addr_to_reg(a, -1)
            self.gen_libcall3('__memclr', d, d, size)
            return
        z = self.alloc_reg()
        self.e_ri('LIL', z, 0)
        i = 0
        while i + 2 <= size:
            self.sp_access('STW', z, var.slot + i + self.depth)
            i += 2
        while i < size:
            self.sp_access('STB', z, var.slot + i + self.depth)
            i += 1
        self.free_reg(z)

    # ------------------------------------------------------- the dispatcher
    def gen_cond_value(self, node, hint):
        """A ?: that is wanted as a value: branches around two results."""
        els, end = self.new_label(), self.new_label()
        self.gen_branch(node.cond, False, els)
        saved_busy = self.busy
        v = self.gen(node.then, hint)
        if self.hint_usable(hint) or (hint is not None and hint >= 0 and hint == v.reg):
            d = hint
        elif v.owned:
            d = v.reg
        else:
            d = self.alloc_reg()
        self.e_rr('MOV', d, v.reg)
        if v.reg != d:
            self.release(v)
        self.e_j('JMP', end)
        self.emit_label(els)
        self.busy = saved_busy                 # the else arm starts fresh
        v = self.gen(node.els, d)
        if v.reg != d:
            self.e_rr('MOV', d, v.reg)
            self.release(v)
        self.emit_label(end)
        self.busy = saved_busy
        return self.claim(d)

    def gen(self, node, hint=-1):
        """Generate node; the value lands in a register, hint is a wish."""
        if not self.opt.steer:
            hint = -1                          # -fno-steer: never steer results
        self.cur_tok = node.tok or self.cur_tok
        return self.gen_inner(node, hint)

    def gen_inner(self, node, hint):
        """The body of gen: one case per kind of node."""
        k = node.kind
        if node.ty is not None and (is_integer(node.ty) or node.ty.kind == 'ptr'):
            c = self.is_const(node)
            if c is not None:
                d = self.claim(hint) if self.hint_usable(hint) else \
                    Val(self.alloc_reg(), True)
                self.load_const(d.reg, c)
                return d
        if k == 'NULL_EXPR':
            return NOVAL
        if k == 'NUM':
            d = self.claim(hint) if self.hint_usable(hint) else \
                Val(self.alloc_reg(), True)
            self.load_const(d.reg, node.val)
            return d
        if k in ('VAR', 'MEMBER', 'DEREF'):
            if k == 'VAR' and self.reg_var(node):
                return Val(node.var.reg, False)
            ty = node.ty
            if is_array_like(ty) or ty.kind == 'func' or is_aggregate(ty):
                a = self.gen_addr(node)
                return self.addr_to_reg(a, hint)
            if k == 'MEMBER' and node.member.is_bitfield:
                a = self.gen_addr(node)
                v = self.load_from(node.member.ty, a, hint)
                return self.bitfield_extract(v, node.member, hint)
            a = self.gen_addr(node)
            return self.load_from(ty, a, hint)
        if k == 'ADDR':
            a = self.gen_addr(node.lhs)
            return self.addr_to_reg(a, hint)
        if k == 'ASSIGN':
            return self.gen_assign(node, hint, True)
        if k == 'STMT_EXPR':
            last = None
            for n in (node.body or []):
                if n is (node.body or [])[-1] and n.kind == 'EXPR_STMT':
                    last = n
                    break
                self.gen_stmt(n)
            if last is None:
                return NOVAL
            return self.gen(last.lhs, hint)
        if k == 'COMMA':
            if not self.skip_memzero(node):
                self.gen_void(node.lhs)
            return self.gen(node.rhs, hint)
        if k == 'CAST':
            v = self.gen(node.lhs, hint)
            return self.convert(v, node.lhs.ty, node.ty, hint)
        if k == 'MEMZERO':
            self.gen_memzero(node.var)
            return NOVAL
        if k == 'COND':
            if node.ty.kind == 'void':
                self.gen_void(node)
                return NOVAL
            return self.gen_cond_value(node, hint)
        if k == 'NOT':
            v = self.gen(node.lhs, -1)
            if self.hint_usable(hint) and hint != v.reg:
                d = self.claim(hint)
            else:
                d = Val(self.alloc_avoid(bit(v.reg) if v.owned else 0), True)
            l = self.new_label()
            self.e_ri('LIL', d.reg, 1)
            self.e_br('BZ', v.reg, l)
            self.e_ri('LIL', d.reg, 0)
            self.emit_label(l)
            self.release(v)
            return d
        if k == 'NEG':
            v = self.gen(node.lhs, hint)
            d = self.take_dst(hint, v, None)
            self.e_rr('NOT', d.reg, v.reg)
            self.e_ri('ADDI', d.reg, 1)
            return d
        if k == 'BITNOT':
            v = self.gen(node.lhs, hint)
            d = self.take_dst(hint, v, None)
            self.e_rr('NOT', d.reg, v.reg)
            return d
        if k in ('LOGAND', 'LOGOR'):
            return self.bool_by_branch(node, hint)
        if k == 'FUNCALL':
            return self.gen_call(node, hint)
        if k in ('ADD', 'SUB', 'BITAND', 'BITOR', 'BITXOR'):
            return self.gen_arith(node, hint)
        if k == 'MUL':
            return self.gen_mul(node, hint)
        if k in ('DIV', 'MOD'):
            return self.gen_divmod(node, hint)
        if k in ('SHL', 'SHR'):
            return self.gen_shift(node, hint)
        if k in ('EQ', 'NE', 'LT', 'LE'):
            return self.gen_compare(node, hint)
        error_at(node.tok.pos if node.tok else None,
                 f'internal: cannot generate {k}')

    def skip_memzero(self, node):
        """`int x = 0;` on a register variable: the clear and the store are
        the same instruction, so drop the clear."""
        return (node.lhs.kind == 'MEMZERO' and is_scalar(node.lhs.var.ty) and
                node.rhs.kind == 'ASSIGN' and node.rhs.lhs.kind == 'VAR' and
                node.rhs.lhs.var is node.lhs.var)

    def gen_void(self, node):
        """Evaluate for side effects only."""
        if node is None:
            return
        k = node.kind
        if k in ('NULL_EXPR', 'NUM', 'VAR'):
            return
        if k == 'ASSIGN':
            self.gen_assign(node, -1, False)
            return
        if k == 'COMMA':
            if not self.skip_memzero(node):
                self.gen_void(node.lhs)
            self.gen_void(node.rhs)
            return
        if k == 'CAST':
            self.gen_void(node.lhs)
            return
        if k == 'MEMZERO':
            self.gen_memzero(node.var)
            return
        if k == 'COND':
            els, end = self.new_label(), self.new_label()
            self.gen_branch(node.cond, False, els)
            self.gen_void(node.then)
            self.e_j('JMP', end)
            self.emit_label(els)
            self.gen_void(node.els)
            self.emit_label(end)
            return
        if k == 'LOGAND':
            end = self.new_label()
            self.gen_branch(node.lhs, False, end)
            self.gen_void(node.rhs)
            self.emit_label(end)
            return
        if k == 'LOGOR':
            end = self.new_label()
            self.gen_branch(node.lhs, True, end)
            self.gen_void(node.rhs)
            self.emit_label(end)
            return
        if k in ('ADD', 'SUB', 'MUL', 'BITAND', 'BITOR', 'BITXOR', 'EQ', 'NE',
                 'LT', 'LE', 'SHL', 'SHR', 'DIV', 'MOD'):
            self.gen_void(node.lhs)          # pure: only side effects matter
            self.gen_void(node.rhs)
            return
        if k in ('NEG', 'BITNOT', 'NOT'):
            self.gen_void(node.lhs)
            return
        if k == 'ADDR' and node.lhs.kind == 'VAR':
            return
        v = self.gen(node, -1)
        self.release(v)


def log2_exact(v):
    """The shift count if v is a power of two, else -1."""
    v &= 0xFFFF
    if v == 0 or (v & (v - 1)):
        return -1
    return v.bit_length() - 1


def norm_i16(v):
    """A 16-bit pattern read as a signed number."""
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def mk_binary(kind, l, r, ty):
    """Build a binary tree node of this kind and type."""
    n = Node(kind, l.tok, ty)
    n.lhs, n.rhs = l, r
    return n
