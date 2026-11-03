# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""The machine layer of the back end: registers, the instruction buffer and
the little bookkeeping the rest of the code generator stands on.

TARA16 facts a code generator must know
---------------------------------------
* Eight 16-bit registers. `CALL` writes the return address into R6, `RET`
  jumps to it, and `PUSH`/`POP` use R7 as the stack pointer.
* The calling convention (`tara16-abi0`): R0-R2 carry arguments 1-3 and R0
  carries the result; R3-R5 must be preserved by a called function; further
  arguments are pushed by the caller, right to left.
* `LDW`/`STW` reach only -16..15 bytes from a base register, `ADDI` takes
  -128..127, and `LIL`/`LIH` load one byte each.

Values and addresses
--------------------
`Val` is a value sitting in a register. `owned` means "this is a temporary
the expression code borrowed from the pool and must give back".
`Addr` is a place in memory: an offset from the stack pointer, an offset
from a register, or a symbol plus an offset. Keeping addresses in this form
is what lets constant offsets fold into the 5-bit field of a load.
"""
from ..ctype import is_schar
from ..diag import error_at

SP = 7
LR = 6
NARGREG = 3
CALLER_SAVED = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 6)
CALLEE_SAVED = (1 << 3) | (1 << 4) | (1 << 5)
ALLOC_ORDER = (0, 1, 2, 6, 3, 4, 5)

WRITES_RD = {'MOV', 'NOT', 'LIL', 'LIH', 'LDW', 'LDB', 'ADD', 'SUB', 'ADDI',
             'MUL', 'AND', 'OR', 'XOR', 'SHL', 'SHR', 'SLT', 'POP', 'LA'}


def bit(r):
    """The one-bit set holding register r."""
    return 1 << r


class Val:
    """A value sitting in a register, and whether we must give it back."""
    __slots__ = ('reg', 'owned')

    def __init__(self, reg, owned=False):
        self.reg = reg
        self.owned = owned

    def __repr__(self):
        return f'R{self.reg}{"*" if self.owned else ""}'


NOVAL = Val(-1, False)


class Addr:
    """A place in memory, kept in pieces until something forces a register."""
    __slots__ = ('kind', 'reg', 'owned', 'sym', 'off')

    def __init__(self, kind, reg=-1, owned=False, sym=None, off=0):
        self.kind = kind            # 'sp' | 'reg' | 'sym'
        self.reg = reg
        self.owned = owned
        self.sym = sym
        self.off = off

    def copy(self):
        """A duplicate, so an offset can change without touching the first."""
        return Addr(self.kind, self.reg, self.owned, self.sym, self.off)

    def __repr__(self):
        return f'<{self.kind} {self.sym or self.reg}{self.off:+}>'


class Item:
    """One line of output: an instruction, a label, or raw text."""
    __slots__ = ('kind', 'op', 'r', 'imm', 'sym', 'text', 'dead', 'line')

    def __init__(self, kind, op=None):
        self.kind = kind            # 'ins' | 'label' | 'raw' | 'comment'
        self.op = op
        self.r = [-1, -1, -1]
        self.imm = 0
        self.sym = None
        self.text = None
        self.dead = False
        self.line = 0               # the source line this came from

    def __repr__(self):
        return f'<{self.op or self.text}>'


class TargetMixin:
    """Emitting instructions and handing out registers."""

    # ---- the instruction buffer (one function at a time) ----------------
    def reset_items(self):
        """Start a fresh instruction list for another pass over a body."""
        self.items = []

    def add(self, item):
        # Which line of C this came from. Nothing in the compiler depends on
        # it; `--lines` prints it, and it is what lets the documentation line
        # a program up against its own instructions.
        """Append one item to the instruction list, and note its line of C."""
        if self.cur_tok is not None:
            item.line = self.cur_tok.pos.line
        self.items.append(item)
        return item

    def ins(self, op):
        """Append an instruction with this opcode."""
        return self.add(Item('ins', op))

    def emit_label(self, name):
        """Append a label."""
        it = Item('label')
        it.text = name
        return self.add(it)

    def emit_raw(self, text):
        """Append a line of text to pass through untouched (inline asm)."""
        it = Item('raw')
        it.text = text
        return self.add(it)

    def comment(self, text):
        """Append a comment."""
        it = Item('comment')
        it.text = text
        return self.add(it)

    def e_rrr(self, op, d, a, b):
        """Emit a three-register instruction: op d, a, b."""
        it = self.ins(op)
        it.r = [d, a, b]

    def e_rr(self, op, d, a):
        """Emit a two-register instruction, dropping a move onto itself."""
        if op == 'MOV' and d == a:
            return                      # a register moved onto itself
        it = self.ins(op)
        it.r = [d, a, -1]

    def e_ri(self, op, d, imm):
        """Emit a register-and-immediate instruction: op d, imm."""
        it = self.ins(op)
        it.r = [d, -1, -1]
        it.imm = imm

    def e_mem(self, op, r, off, base):
        """Emit a load or store: op r, off(base)."""
        it = self.ins(op)
        it.r = [r, base, -1]
        it.imm = off

    def e_br(self, op, r, label):
        """Emit a conditional branch on a register."""
        it = self.ins(op)
        it.r = [r, -1, -1]
        it.sym = label

    def e_j(self, op, label):
        """Emit a jump or a call."""
        it = self.ins(op)
        it.sym = label

    def e_0(self, op):
        """Emit an instruction with no operands."""
        self.ins(op)

    def e_la(self, d, sym, off=0):
        """Emit LA: put the address of a symbol in a register."""
        it = self.ins('LA')
        it.r = [d, -1, -1]
        it.sym = sym
        it.imm = off

    def push(self, r):
        """Push a register, and remember that the stack moved."""
        it = self.ins('PUSH')
        it.r = [r, -1, -1]
        self.depth += 2

    def pop(self, r):
        """Pop a register, and remember that the stack moved."""
        it = self.ins('POP')
        it.r = [r, -1, -1]
        self.depth -= 2

    def new_label(self):
        """A fresh label nobody else will use."""
        self.label_no += 1
        return f'.T{self.label_no}'

    # ---- the register pool ----------------------------------------------
    def in_pool(self, r):
        """Is this register one the function may use for temporaries?"""
        return 0 <= r < 8 and (self.pool & bit(r))

    def free_count(self):
        """How many registers of the pool are free."""
        return bin(self.pool & ~self.busy).count('1')

    def alloc_avoid(self, avoid):
        """Take a free register, avoiding a set; an error if none is left."""
        for r in ALLOC_ORDER:
            if (self.pool & bit(r)) and not (self.busy & bit(r)) and not (avoid & bit(r)):
                self.busy |= bit(r)
                return r
        error_at(self.cur_tok.pos if self.cur_tok else None,
                 f"TARA16 codegen: out of registers in '{self.cur_fn.name}' "
                 '(expression too complex; split it into smaller statements)')

    def alloc_reg(self):
        """Take any free register from the pool."""
        return self.alloc_avoid(0)

    def free_reg(self, r):
        """Give a register back to the pool."""
        if self.in_pool(r):
            self.busy &= ~bit(r)

    def release(self, v):
        """Give back the register behind a value, if we owned it."""
        if v is not None and v.owned:
            self.free_reg(v.reg)

    def claim(self, r):
        """Take this particular register, if it belongs to the pool."""
        if self.in_pool(r):
            self.busy |= bit(r)
            return Val(r, True)
        return Val(r, False)

    def hint_usable(self, hint):
        """May a result be steered into `hint`?  A variable's register is
        always safe (the caller only passes one where writing it is), and a
        pool register is safe when nothing is using it."""
        if hint is None or hint < 0 or hint == SP:
            return False
        if not self.in_pool(hint):
            return True
        return not (self.busy & bit(hint))

    def take_dst(self, hint, a=None, b=None):
        """The destination register of an instruction with operands a, b.
        An operand register may be reused: the instruction reads its inputs
        and writes its output in the same cycle."""
        d = -1
        if self.hint_usable(hint):
            d = hint
        elif a is not None and a.owned:
            d = a.reg
        elif b is not None and b.owned:
            d = b.reg
        if a is not None and a.owned and a.reg != d:
            self.free_reg(a.reg)
        if b is not None and b.owned and b.reg != d:
            self.free_reg(b.reg)
        if d < 0:
            return Val(self.alloc_reg(), True)
        return self.claim(d)

    def make_mutable(self, v, hint):
        """A register holding v's value that we are allowed to modify."""
        if self.hint_usable(hint) or (hint is not None and hint >= 0 and hint == v.reg):
            if v.reg != hint:
                self.e_rr('MOV', hint, v.reg)
                self.release(v)
            return self.claim(hint)
        if v.owned:
            return v
        d = self.alloc_reg()
        self.e_rr('MOV', d, v.reg)
        return Val(d, True)

    # ---- constants and small address arithmetic -------------------------
    def load_const(self, r, v):
        """Put a 16-bit constant in a register: one instruction, or two."""
        w = v & 0xFFFF
        self.e_ri('LIL', r, w & 0xFF)
        if w >> 8:
            self.e_ri('LIH', r, w >> 8)

    def add_imm(self, r, k):
        """r += k. Needs no temporary while |k| fits a few ADDIs."""
        if k == 0:
            return
        if abs(k) <= 3 * 127 or r == SP:
            while k > 127:
                self.e_ri('ADDI', r, 127)
                k -= 127
            while k < -128:
                self.e_ri('ADDI', r, -128)
                k += 128
            if k:
                self.e_ri('ADDI', r, k)
            return
        t = self.alloc_reg()
        self.load_const(t, k)
        self.e_rrr('ADD', r, r, t)
        self.free_reg(t)

    def sp_access(self, op, r, off):
        """A load or store at any distance from the stack pointer. Far
        offsets move SP for one instruction: TARA16 has no interrupts, so
        nothing can observe the gap, and it costs no register."""
        if -16 <= off <= 15:
            self.e_mem(op, r, off, SP)
            return
        adj = off - 14 if off > 0 else off + 16
        self.add_imm(SP, adj)
        self.e_mem(op, r, off - adj, SP)
        self.add_imm(SP, -adj)

    def sext8(self, r):
        """Sign-extend a byte that was loaded zero-extended: (x ^ 0x80) - 0x80."""
        if self.free_count() == 0:
            self.e_ri('ADDI', r, 127)
            self.e_ri('ADDI', r, 1)
            self.e_ri('SHL', r, 8)
            self.e_ri('SHR', r, 8)
            self.e_ri('ADDI', r, -128)
            return
        t = self.alloc_reg()
        self.e_ri('LIL', t, 0x80)
        self.e_rrr('XOR', r, r, t)
        self.e_ri('ADDI', r, -128)
        self.free_reg(t)

    def sra_inplace(self, d, k):
        """Arithmetic shift right by a constant: TARA16 shifts in zeros."""
        neg, done = self.new_label(), self.new_label()
        self.e_br('BN', d, neg)
        self.e_ri('SHR', d, k)
        self.e_j('JMP', done)
        self.emit_label(neg)
        self.e_rr('NOT', d, d)
        self.e_ri('SHR', d, k)
        self.e_rr('NOT', d, d)
        self.emit_label(done)

    # ---- addresses --------------------------------------------------------
    def release_addr(self, a):
        """Give back the register an address was holding, if we owned it."""
        if a.kind == 'reg' and a.owned:
            self.free_reg(a.reg)

    def addr_regs(self, a):
        """The registers this address is holding, if any."""
        return bit(a.reg) if (a.kind == 'reg' and a.owned) else 0

    def addr_to_reg(self, a, hint=-1):
        """Materialize an address in a register."""
        if a.kind == 'sp':
            d = self.claim(hint) if self.hint_usable(hint) else Val(self.alloc_reg(), True)
            self.e_rr('MOV', d.reg, SP)
            self.add_imm(d.reg, a.off + self.depth)
            return d
        if a.kind == 'reg':
            if a.off == 0:
                return Val(a.reg, a.owned)
            v = self.make_mutable(Val(a.reg, a.owned), hint)
            self.add_imm(v.reg, a.off)
            return v
        d = self.claim(hint) if self.hint_usable(hint) else Val(self.alloc_reg(), True)
        self.e_la(d.reg, a.sym, a.off)
        return d

    def mem_access(self, op, r, a):
        """Load into / store from register r through address a."""
        is_load = op[0] == 'L'
        if a.kind == 'sp':
            self.sp_access(op, r, a.off + self.depth)
            return
        if a.kind == 'reg':
            if -16 <= a.off <= 15:
                self.e_mem(op, r, a.off, a.reg)
                return
            if a.owned:
                self.add_imm(a.reg, a.off)
                a.off = 0
                self.e_mem(op, r, 0, a.reg)
                return
            if is_load and r != a.reg:
                self.e_rr('MOV', r, a.reg)
                self.add_imm(r, a.off)
                self.e_mem(op, r, 0, r)
                return
            t = self.alloc_avoid(bit(r))
            self.e_rr('MOV', t, a.reg)
            self.add_imm(t, a.off)
            self.e_mem(op, r, 0, t)
            self.free_reg(t)
            return
        # a symbol
        if is_load:
            self.e_la(r, a.sym, a.off)
            self.e_mem(op, r, 0, r)
        else:
            t = self.alloc_avoid(bit(r))
            self.e_la(t, a.sym, a.off)
            self.e_mem(op, r, 0, t)
            self.free_reg(t)

    def reachable(self, a, span):
        """Make every byte a.off .. a.off+span-1 reachable with a 5-bit offset."""
        if a.kind == 'sp':
            return a
        if a.kind == 'reg' and -16 <= a.off and a.off + span - 1 <= 15:
            return a
        v = self.addr_to_reg(a, -1)
        return Addr('reg', v.reg, v.owned, off=0)

    def load_from(self, ty, a, hint):
        """Load a scalar of type ty from address a."""
        if self.hint_usable(hint) and not (a.kind == 'reg' and not a.owned and
                                           a.reg == hint and not (-16 <= a.off <= 15)):
            d = self.claim(hint)
        elif a.kind == 'reg' and a.owned:
            d = Val(a.reg, True)          # load in place, over the address
        else:
            d = Val(self.alloc_avoid(self.addr_regs(a)), True)
        self.mem_access(ld_op(ty), d.reg, a)
        if not (a.kind == 'reg' and a.owned and a.reg == d.reg):
            self.release_addr(a)
        if is_schar(ty):
            self.sext8(d.reg)
        return d


def ld_op(ty):
    """The load instruction for a value of this type."""
    return 'LDB' if ty.size == 1 else 'LDW'


def st_op(ty):
    """The store instruction for a value of this type."""
    return 'STB' if ty.size == 1 else 'STW'
