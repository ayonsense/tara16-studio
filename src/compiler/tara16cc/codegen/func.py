# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Functions: where variables live, the prologue and the epilogue.

The work happens in this order for each function.

1. **Analysis.** Walk the body once to count how often each variable is
   used (a use inside a loop counts four times) and to notice variables
   whose address is taken; they cannot live in a register.
2. **A probe pass.** Generate the body once with everything in memory, only
   to learn whether the function calls anything. A *leaf* function may use
   R0-R5 freely; a function that calls others may keep variables only in
   R3-R5, which the called function must preserve.
3. **Register allocation** (`-fno-regvars` switches it off).
4. **Code, then code again.** The prologue must save exactly the registers
   the body writes, but the body's code depends on how many registers were
   saved, because stack arguments move. So the body is generated, the real
   set of saved registers is read off, and it is generated again
   (`-fno-savetrim` keeps the first, pessimistic answer).
5. **Clean-up:** the peephole pass, and sharing the epilogue with other
   functions that end the same way.
"""
from ..ctype import align_to, is_aggregate, is_scalar
from ..diag import error
from .target import CALLEE_SAVED, LR, NARGREG, SP, bit, ld_op, st_op


class FnOut:
    """One finished function, kept until the shared-epilogue pass has run."""
    __slots__ = ('header', 'items', 'epi_entry', 'epi_lr', 'epi_len', 'epi_ret')

    def __init__(self, header, items):
        self.header = header
        self.items = items
        self.epi_entry = None
        self.epi_lr = False
        self.epi_len = 0
        self.epi_ret = -1


def has_struct_param(fn):
    """A struct argument arrives as a pointer the callee copies, and the copy
    needs a call to the runtime, which clobbers the link register."""
    return any(is_aggregate(p.ty) for p in fn.params)

WRITES = {'MOV', 'NOT', 'LIL', 'LIH', 'LDW', 'LDB', 'ADD', 'SUB', 'ADDI',
          'MUL', 'AND', 'OR', 'XOR', 'SHL', 'SHR', 'SLT', 'POP', 'LA'}


class FuncMixin:
    # ------------------------------------------------------------ analysis
    """Whole functions: weights, registers, the frame, the prologue, data."""
    def walk_weights(self, n, w):
        """Count uses of each local, weighting loops."""
        if n is None:
            return
        lw = min(w * 4, 256)
        k = n.kind
        if k == 'VAR':
            if n.var.is_local:
                n.var.weight += w
            return
        if k == 'ADDR':
            self.mark_addr_taken(n.lhs)
        elif k == 'MEMZERO':
            n.var.weight += w
            return
        elif k == 'FUNCALL':
            if n.ret_buffer:
                n.ret_buffer.weight += w
        elif k == 'ASSIGN':
            if n.lhs.kind == 'MEMBER' and n.lhs.member.is_bitfield:
                self.fn_has_bitfield_store = True
        elif k == 'FOR':
            self.walk_weights(n.init, w)
            self.walk_weights(n.cond, lw)
            self.walk_weights(n.then, lw)
            self.walk_weights(n.inc, lw)
            return
        elif k == 'DO':
            self.walk_weights(n.then, lw)
            self.walk_weights(n.cond, lw)
            return
        for sub in (n.lhs, n.rhs, n.cond, n.then, n.els, n.init, n.inc):
            self.walk_weights(sub, w)
        for lst in (n.body, n.args):
            for sub in (lst or []):
                self.walk_weights(sub, w)

    def mark_addr_taken(self, n):
        """Note that a variable had its address taken: it needs memory."""
        while n is not None and n.kind == 'MEMBER':
            n = n.lhs
        if n is not None and n.kind == 'VAR' and n.var.is_local:
            n.var.addr_taken = True

    def reg_candidate(self, v):
        """Could this variable live in a register at all?"""
        return is_scalar(v.ty) and not v.addr_taken and v.weight > 0

    def allocate_registers(self, fn, leaf, all_memory):
        """Hand out registers to the busiest variables that can use one."""
        for v in fn.locals:
            v.reg = -1
        if all_memory or not self.opt.regvars:
            return
        cands = [v for v in fn.locals if self.reg_candidate(v)]
        # busiest first; on a tie the variable that is not a parameter
        # wins, because a parameter already sits in a register on entry
        cands.sort(key=lambda v: (-v.weight, v.argidx))
        if leaf:
            # temporaries: whatever R0-R5 the variables leave, plus R6
            min_temps = 3 if self.fn_has_bitfield_store else 2
            maxv = 6 - min_temps
            taken = 0
            sel = cands[:maxv]
            for v in sel:                      # a parameter stays where it arrived
                if 0 <= v.argidx < NARGREG:
                    v.reg = v.argidx
                    taken |= bit(v.reg)
            for v in sel:
                if v.reg >= 0:
                    continue
                for r in (2, 1, 0, 3, 4, 5):
                    if taken & bit(r):
                        continue
                    if r >= 3 and v.weight < 3:
                        break                  # R3-R5 cost a PUSH and a POP
                    v.reg = r
                    taken |= bit(r)
                    break
        else:
            nxt = 3
            for v in cands:
                if nxt > 5:
                    break
                cost = 2 + (1 if v.argidx >= 0 else 0)
                if v.weight <= cost:
                    break
                v.reg = nxt
                nxt += 1

    # ------------------------------------------------------------- liveness
    def live_ranges(self, fn):
        """Number the full expressions in the order they are written (each is one
        *tick*) and give every local the span its value must last.
        Temporaries never outlive a full expression, so two variables whose
        spans do not overlap can share a register. Spans are counted in
        half-ticks: tick t is position 2t while its expression is worked out
        and 2t+1 once the statement `v = ...` has stored v, so a variable
        that dies in a statement can hand its register to the one the
        statement creates. A variable used inside a loop it was declared
        outside of lives for the whole loop, because the next trip round may
        read it. False for a function with a label: a goto may jump
        backwards anywhere, so no span can be trusted."""
        self.lv_tick = 0
        self.lv_loops = []
        self.lv_refs = []
        self.lv_label = False
        self.lv_stmt(fn.body, 0)
        if self.lv_label:
            return False
        self.ntick = self.lv_tick
        for v in fn.locals:
            v.live_lo, v.live_hi = 2 * self.ntick + 2, -1
        for var, pos, loops in self.lv_refs:
            lo = hi = pos
            if len(loops) > var.loop_depth:
                span = loops[var.loop_depth]
                lo, hi = 2 * span[0], 2 * span[1] + 1
            var.live_lo = min(var.live_lo, lo)
            var.live_hi = max(var.live_hi, hi)
        for p in fn.params:                 # in a register from the start
            p.live_lo = 0
            p.live_hi = max(p.live_hi, 0)
        if is_aggregate(fn.ty.return_ty) and fn.params:
            fn.params[0].live_hi = 2 * self.ntick + 1    # every return reads it
        return True

    def lv_full(self, e, fixed):
        """One full expression: a new tick, unless inside a statement
        expression, which shares the tick of the expression around it."""
        if fixed:
            self.lv_expr(e, 2 * fixed)
            return fixed
        self.lv_tick += 1
        t = self.lv_tick
        if e.kind == 'COMMA' and self.skip_memzero(e):
            e = e.rhs               # `int v = x;`: the clear is never emitted
        if e.kind == 'ASSIGN' and e.lhs.kind == 'VAR' and e.lhs.var.is_local:
            # `v = ...`: v is written after everything else is read
            self.lv_refs.append((e.lhs.var, 2 * t + 1, list(self.lv_loops)))
            self.lv_expr(e.rhs, 2 * t)
        else:
            self.lv_expr(e, 2 * t)
        return t

    def lv_loop(self, fixed):
        """Open a loop: its span of ticks is filled in as it is walked."""
        span = [fixed, fixed] if fixed else [self.lv_tick + 1, self.lv_tick]
        self.lv_loops.append(span)
        return span

    def lv_end_loop(self, span, fixed):
        """Close a loop: it ends at the last tick inside it."""
        if not fixed:
            span[1] = self.lv_tick
        self.lv_loops.pop()

    def lv_stmt(self, n, fixed):
        """Walk a statement in the order it runs, giving each full
        expression a tick (or the fixed one, inside an expression)."""
        if n is None:
            return
        k = n.kind
        if k == 'IF':
            n.tick = self.lv_full(n.cond, fixed)
            self.lv_stmt(n.then, fixed)
            self.lv_stmt(n.els, fixed)
        elif k == 'FOR':
            self.lv_stmt(n.init, fixed)
            span = self.lv_loop(fixed)
            if n.cond is not None:
                n.tick = self.lv_full(n.cond, fixed)
            self.lv_stmt(n.then, fixed)
            if n.inc is not None:
                n.tick2 = self.lv_full(n.inc, fixed)
            self.lv_end_loop(span, fixed)
        elif k == 'DO':
            span = self.lv_loop(fixed)
            self.lv_stmt(n.then, fixed)
            n.tick = self.lv_full(n.cond, fixed)
            self.lv_end_loop(span, fixed)
        elif k == 'SWITCH':
            n.tick = self.lv_full(n.cond, fixed)
            self.lv_stmt(n.then, fixed)
        elif k in ('CASE', 'LABEL'):
            if k == 'LABEL':
                self.lv_label = True
            self.lv_stmt(n.lhs, fixed)
        elif k == 'BLOCK':
            for sub in (n.body or []):
                self.lv_stmt(sub, fixed)
        elif k == 'RETURN':
            if n.lhs is not None:
                n.tick = self.lv_full(n.lhs, fixed)
        elif k == 'EXPR_STMT':
            n.tick = self.lv_full(n.lhs, fixed)
        elif k not in ('GOTO', 'ASM'):
            n.tick = self.lv_full(n, fixed)

    def lv_expr(self, n, t):
        """Note every local an expression mentions, at position t."""
        if n is None:
            return
        k = n.kind
        if k in ('VAR', 'MEMZERO'):
            if n.var.is_local:
                self.lv_refs.append((n.var, t, list(self.lv_loops)))
            return
        if k == 'STMT_EXPR':
            for sub in (n.body or []):
                self.lv_stmt(sub, t // 2)
            return
        if k == 'FUNCALL' and n.ret_buffer:
            self.lv_refs.append((n.ret_buffer, t, list(self.lv_loops)))
        for sub in (n.lhs, n.rhs, n.cond, n.then, n.els, n.init, n.inc):
            self.lv_expr(sub, t)
        for sub in (n.args or []):
            self.lv_expr(sub, t)

    def allocate_live(self, fn, leaf):
        """Hand out registers busiest-first, as allocate_registers does, but
        let variables whose spans do not overlap share one."""
        for v in fn.locals:
            v.reg = -1
        cands = [v for v in fn.locals if self.reg_candidate(v)]
        cands.sort(key=lambda v: (-v.weight, v.argidx))
        placed = []

        def free(r, v):
            """Is register r unused by every placed variable v overlaps?"""
            for u in placed:
                if u.reg == r and u.live_lo <= v.live_hi and v.live_lo <= u.live_hi:
                    return False
            return True

        if leaf:
            # temporaries: whatever R0-R5 the living variables leave, and R6
            min_temps = 3 if self.fn_has_bitfield_store else 2
            maxv = 6 - min_temps
            count = [0] * (2 * self.ntick + 2)
            pargs = 0                          # argument registers of parameters
            waiting = {}                       # ... of parameters not yet placed
            for v in cands:
                if 0 <= v.argidx < NARGREG:
                    pargs |= bit(v.argidx)
                    waiting[v.argidx] = v
            for v in cands:
                waiting.pop(v.argidx, None)
                if max(count[v.live_lo:v.live_hi + 1]) >= maxv:
                    continue                   # it would leave too few temporaries
                if 0 <= v.argidx < NARGREG:
                    order = (v.argidx, 3, 4, 5)   # a parameter stays where it arrived
                else:
                    order = tuple(r for r in (2, 1, 0) if not pargs & bit(r)) + \
                        tuple(r for r in (2, 1, 0) if pargs & bit(r)) + (3, 4, 5)
                for r in order:
                    if r >= 3 and v.weight < 3:
                        break                  # R3-R5 cost a PUSH and a POP
                    p = waiting.get(r)
                    if p is not None and p.live_lo <= v.live_hi and v.live_lo <= p.live_hi:
                        continue               # a parameter still to come arrives in r
                    if free(r, v):
                        v.reg = r
                        placed.append(v)
                        for t in range(v.live_lo, v.live_hi + 1):
                            count[t] += 1
                        break
        else:
            for v in cands:
                cost = 2 + (1 if v.argidx >= 0 else 0)
                if v.weight <= cost:
                    break
                for r in (3, 4, 5):
                    if free(r, v):
                        v.reg = r
                        placed.append(v)
                        break

    def tick_masks(self, fn):
        """For each tick, the registers its living variables sit in."""
        m = [0] * (2 * self.ntick + 2)
        for v in fn.locals:
            if v.reg >= 0:
                for t in range(max(v.live_lo, 0), v.live_hi + 1):
                    m[t] |= bit(v.reg)
        self.live_regs = m

    def enter_tick(self, t):
        """Before a full expression: its temporaries may use any register of
        the pool that no living variable is sitting in."""
        if self.live_regs is None or t == self.cur_tick:
            return
        if self.busy:
            error(f'internal: temporaries live across a statement in {self.cur_fn.name}')
        self.cur_tick = t
        self.live_during = self.live_regs[2 * t]
        self.pool = self.base_pool & ~(self.live_during | self.live_regs[2 * t + 1])

    def var_regs(self, fn):
        """The set of registers variables are living in."""
        m = 0
        for v in fn.locals:
            if v.reg >= 0:
                m |= bit(v.reg)
        return m

    def needs_slot(self, v):
        """Does this variable need a place in the frame?"""
        return v.reg < 0 and v.weight > 0

    def layout_frame(self, fn, nsaved_words):
        """Give every memory variable a frame offset. Busy scalars go
        closest to the stack pointer, where the 5-bit offset reaches."""
        c = [v for v in fn.locals
             if self.needs_slot(v) and not (v.argidx >= NARGREG and
                                            not is_aggregate(v.ty))]
        c.sort(key=lambda v: (0 if is_scalar(v.ty) else 1,
                              -v.weight if is_scalar(v.ty) else v.ty.size))
        off = 0
        for v in c:
            al = 2 if v.ty.align >= 2 else 1
            off = align_to(off, al)
            v.slot = off
            off += v.ty.size
        self.frame_size = align_to(off, 2)
        for v in fn.locals:
            if v.argidx >= NARGREG and not is_aggregate(v.ty):
                # a pushed argument is a big-endian word: a char is its second byte
                v.slot = (self.frame_size + 2 * nsaved_words +
                          2 * (v.argidx - NARGREG) + (1 if v.ty.size == 1 else 0))

    # ------------------------------------------------- prologue / epilogue
    def gen_prologue(self, fn):
        """The opening: save what must survive, make room for the frame."""
        self.cur_tok = fn.tok       # the prologue belongs to the function's
        if self.save_lr:            # own line, not to the last statement's
            self.push(LR)
        for r in range(3, 6):
            if self.saved & bit(r):
                self.push(r)
        self.add_imm(SP, -self.frame_size)
        self.depth = 0
        # incoming register arguments are live until they are stored
        self.busy = 0
        for p in fn.params:
            if 0 <= p.argidx < NARGREG:
                self.busy |= bit(p.argidx) & self.pool
        # 1. struct parameters: copy the caller's value into our frame
        for p in fn.params:
            if not is_aggregate(p.ty) or p.weight == 0:
                continue
            if p.argidx >= NARGREG:
                error(f"TARA16: in '{fn.name}', struct parameter '{p.name}' must "
                      'be one of the first three parameters (pass a pointer instead)')
            from .target import Addr
            src = Addr('reg', p.argidx, False)
            dst = Addr('sp', off=p.slot)
            self.copy_bytes(dst, src, p.ty)
        # 2. scalar register parameters
        for p in fn.params:
            i = p.argidx
            if i >= NARGREG or is_aggregate(p.ty) or p.weight == 0:
                continue
            if p.reg >= 0:
                self.e_rr('MOV', p.reg, i)
            else:
                self.sp_access(st_op(p.ty), i, p.slot)
        # 3. stack parameters that live in registers
        for p in fn.params:
            if p.argidx < NARGREG or p.reg < 0:
                continue
            self.sp_access(ld_op(p.ty), p.reg, p.slot)
        self.busy = 0
        for p in fn.params:
            if p.reg >= 0 and p.ty.kind == 'char' and not p.ty.is_unsigned and \
                    p.argidx >= NARGREG:
                self.sext8(p.reg)

    def gen_epilogue(self):
        """The ending: undo the frame, pop what was saved, return."""
        self.emit_label(self.ret_label)
        self.add_imm(SP, self.frame_size)
        for r in range(5, 2, -1):
            if self.saved & bit(r):
                self.ins('POP').r[0] = r
        if self.save_lr:
            self.ins('POP').r[0] = LR
        self.e_0('RET')

    def written_regs(self, start, end):
        """Which registers the instructions in items[start:end] write."""
        w = 0
        for it in self.items[start:end]:
            if it.kind == 'raw':
                w |= CALLEE_SAVED | bit(LR)       # inline asm: assume the worst
                continue
            if it.kind != 'ins':
                continue
            op = it.op
            if op in ('STW', 'STB', 'PUSH', 'BZ', 'BN', 'JMP', 'RET', 'HLT', 'NOP'):
                continue
            if op == 'CALL':
                w |= bit(LR)
                continue
            if it.r[0] >= 0:
                w |= bit(it.r[0])
        return w

    def gen_body_pass(self, fn):
        """Generate prologue, body and ending once, from scratch."""
        self.reset_items()
        self.depth = 0
        self.busy = 0
        self.made_call = False
        self.cse_var, self.cse_reg = None, -1
        self.ret_label = f'.Lret.{fn.name}'
        self.ret_direct = self.frame_size == 0 and not self.save_lr and self.saved == 0
        self.pool = self.base_pool
        self.cur_tick = -1
        self.enter_tick(0)
        self.gen_prologue(fn)
        self.body_start = len(self.items)
        self.gen_stmt(fn.body)
        if self.depth != 0 or self.busy != 0:
            error(f'internal: unbalanced stack ({self.depth}) or registers '
                  f'(0x{self.busy:x}) in {fn.name}')
        if fn.name == 'main':
            self.e_ri('LIL', 0, 0)               # falling off the end returns 0
        self.body_end = len(self.items)
        if self.ret_direct:
            self.emit_label(self.ret_label)
            self.e_0('RET')
        else:
            self.gen_epilogue()

    # ------------------------------------------------------ one function
    def gen_function(self, fn):
        """Generate one function: analyse, allocate, then code it twice."""
        self.cur_fn = fn
        self.cur_tok = fn.tok
        self.fn_has_bitfield_store = False
        for v in fn.locals:
            v.weight = 0
            v.addr_taken = False
            v.reg = -1
            v.slot = 0
        self.walk_weights(fn.body, 1)
        if is_aggregate(fn.ty.return_ty) and fn.params:
            fn.params[0].weight += 1             # the hidden pointer is read
        live = self.opt.live and self.opt.regvars and self.live_ranges(fn)
        self.live_regs = None

        # --- probe pass: does the body call anything?
        self.allocate_registers(fn, False, True)
        self.base_pool = bit(0) | bit(1) | bit(2) | bit(LR)
        self.save_lr = True
        self.saved = 0
        self.layout_frame(fn, 1)
        self.gen_body_pass(fn)
        leaf = not self.made_call
        has_raw = any(it.kind == 'raw' for it in self.items[self.body_start:self.body_end])

        # --- real passes
        if has_raw:
            # Raw assembly has no clobber list. Keep every C variable in
            # memory so arbitrary R0-R6 writes cannot silently corrupt it.
            self.allocate_registers(fn, leaf, True)
        elif live:
            self.allocate_live(fn, leaf)
        else:
            self.allocate_registers(fn, leaf, False)
        vr = self.var_regs(fn)
        if live:
            # a variable's register is a temporary whenever it is not alive
            if leaf:
                self.base_pool = (bit(0) | bit(1) | bit(2) | bit(3) | bit(4) |
                                  bit(5) | bit(LR))
            else:
                self.base_pool = bit(0) | bit(1) | bit(2) | bit(LR) | vr
            self.tick_masks(fn)
        elif leaf:
            self.base_pool = ((bit(0) | bit(1) | bit(2) | bit(3) | bit(4) | bit(5))
                              & ~vr) | bit(LR)
        else:
            self.base_pool = bit(0) | bit(1) | bit(2) | bit(LR)
        assumed = CALLEE_SAVED & (vr | self.base_pool)
        if has_raw:
            assumed = CALLEE_SAVED               # inline asm may write anything
        assumed_lr = True
        for _ in range(8):
            self.saved = assumed
            self.save_lr = assumed_lr
            self.layout_frame(fn, (1 if self.save_lr else 0) + bin(self.saved).count('1'))
            self.gen_body_pass(fn)
            w = self.written_regs(0, self.body_end)
            wb = self.written_regs(self.body_start, self.body_end)
            actual = (wb | vr) & CALLEE_SAVED
            actual_lr = (not leaf) or has_struct_param(fn) or bool(w & bit(LR))
            if (actual & ~assumed) or (actual_lr and not assumed_lr):
                error(f'internal: callee-saved register escaped in {fn.name}')
            if not self.opt.savetrim:
                break
            if actual == assumed and actual_lr == assumed_lr:
                break
            self.base_pool &= ~(assumed & ~actual)
            if not actual_lr:
                self.base_pool &= ~bit(LR)
            assumed, assumed_lr = actual, actual_lr
        if self.opt.peephole:
            self.peephole()

        # --- the header comment says where every variable ended up
        head = ['']
        regs = ''.join(f' R{r}' for r in range(6) if vr & bit(r))
        head.append(f'; ---- {fn.name}  ({"leaf" if leaf else "calls others"}, '
                    f'{self.frame_size}-byte frame'
                    f'{", variables in" + regs if regs else ""}) ----')
        for v in fn.locals:
            if not v.name or v.weight == 0:
                continue
            if v.reg >= 0:
                head.append(f';   {v.name:<12} R{v.reg}')
            elif v.argidx >= NARGREG and not is_aggregate(v.ty):
                head.append(f';   {v.name:<12} caller frame {v.slot}(SP)')
            else:
                head.append(f';   {v.name:<12} {v.slot}(SP)')
        head.append('  .text')
        head.append(f'  .chunk {fn.name}')
        if fn.ind_stub:
            head.append(f'__ind_{fn.name}:')
            head.append('  POP R6')
        head.append(f'{fn.name}:')
        self.functions.append(FnOut(head, self.items))

    # ------------------------------------------------- shared epilogues
    def classify_epilogue(self, fo):
        """A function that ends in POP R5 / POP R4 / POP R3 / POP R6 / RET
        (or a suffix of it) can share one copy in the runtime."""
        items = fo.items
        i = len(items) - 1
        while i >= 0 and (items[i].dead or items[i].kind != 'ins'):
            i -= 1
        if i < 0 or items[i].op != 'RET':
            return
        ret = i
        regs = []
        i = ret - 1
        while i >= 0 and len(regs) < 4:
            it = items[i]
            if it.dead or it.kind == 'comment':
                i -= 1
                continue
            if it.kind != 'ins' or it.op != 'POP':
                break
            regs.append(it.r[0])
            i -= 1
        if not regs:
            return
        lr = regs[0] == LR
        want = [LR, 3, 4, 5] if lr else [3, 4, 5]
        for k, r in enumerate(regs):
            if k >= len(want) or r != want[k]:
                return
        names = (['__epi_lr', '__epi_r3', '__epi_r4', '__epi_r5'] if lr else
                 ['__lepi_r3', '__lepi_r4', '__lepi_r5'])
        fo.epi_entry = names[len(regs) - 1]
        fo.epi_lr = lr
        fo.epi_len = len(regs) + 1
        fo.epi_ret = ret

    def flush_functions(self, out):
        """Print every finished function, sharing endings where it pays."""
        save = [0, 0]
        for fo in self.functions:
            self.classify_epilogue(fo)
            if fo.epi_entry:
                save[1 if fo.epi_lr else 0] += fo.epi_len - 1
        use = [save[0] > 4, save[1] > 5] if self.opt.epilogues else [False, False]
        for fo in self.functions:
            if fo.epi_entry and use[1 if fo.epi_lr else 0]:
                ret = fo.items[fo.epi_ret]
                k = fo.epi_len - 1
                i = fo.epi_ret - 1
                while i >= 0 and k > 0:
                    if fo.items[i].dead or fo.items[i].kind != 'ins':
                        i -= 1
                        continue
                    fo.items[i].dead = True
                    k -= 1
                    i -= 1
                ret.op = 'JMP'
                ret.sym = fo.epi_entry
                self.epi_used = True
            out.extend(fo.header)
            out.extend(self.print_items(fo.items))

    # ---------------------------------------------------------- printing
    def print_items(self, items):
        """Turn the finished instruction list into lines of assembly."""
        lines = []
        tag = self.opt.lines
        for it in items:
            n = len(lines)
            if it.dead:
                continue
            if it.kind == 'label':
                lines.append(f'{it.text}:')
                continue
            if it.kind == 'raw':
                lines.append(f'  {it.text}')
                continue
            if it.kind == 'comment':
                lines.append(f'  ; {it.text}')
                continue
            op = it.op
            if op == 'LA':
                lines.append(f'  LA R{it.r[0]}, {it.sym}{it.imm:+d}' if it.imm
                             else f'  LA R{it.r[0]}, {it.sym}')
            elif op in ('BZ', 'BN'):
                lines.append(f'  {op} R{it.r[0]}, {it.sym}')
            elif op in ('JMP', 'CALL'):
                lines.append(f'  {op} {it.sym}')
            elif op in ('RET', 'HLT', 'NOP'):
                lines.append(f'  {op}')
            elif op in ('PUSH', 'POP'):
                lines.append(f'  {op} R{it.r[0]}')
            elif op in ('LDW', 'STW', 'LDB', 'STB'):
                lines.append(f'  {op} R{it.r[0]}, {it.imm}(R{it.r[1]})')
            elif op in ('MOV', 'NOT'):
                lines.append(f'  {op} R{it.r[0]}, R{it.r[1]}')
            elif op in ('LIL', 'LIH', 'ADDI', 'SHL', 'SHR'):
                lines.append(f'  {op} R{it.r[0]}, {it.imm}')
            else:
                lines.append(f'  {op} R{it.r[0]}, R{it.r[1]}, R{it.r[2]}')
            if tag and it.line and len(lines) > n:
                lines[n] = f'{lines[n]:<28} ; line {it.line}'
        return lines

    # -------------------------------------------------------------- data
    def emit_data(self, prog, out):
        """Write the global variables, in the section each belongs to."""
        for var in prog:
            if var.is_function or not var.is_definition:
                continue
            if var.is_tls:
                error(f"TARA16: thread-local variable '{var.name}' is not supported")
            size = var.ty.size
            if size <= 0:
                continue
            if self.opt.zero_page and size <= 8:
                sec = 'zdata'
            else:
                sec = 'data' if var.init_data else 'bss'
            out.append('')
            out.append(f'  .{sec}')
            out.append(f'  .chunk {var.name}')
            if var.align >= 2 or var.ty.align >= 2:
                out.append('  .align 2')
            out.append(f'{var.name}:')
            if not var.init_data:
                out.append(f'  .zero {size}')
                continue
            rel = sorted(var.rel)
            pos = 0
            ri = 0
            while pos < size:
                if ri < len(rel) and rel[ri][0] == pos:
                    off, label, addend = rel[ri]
                    out.append(f'  .word {self.reloc_name(label)}{addend:+d}')
                    ri += 1
                    pos += 2
                    continue
                end = rel[ri][0] if ri < len(rel) else size
                while pos < end:
                    chunk = var.init_data[pos:min(pos + 12, end)]
                    out.append('  .byte ' + ', '.join(str(b) for b in chunk))
                    pos += len(chunk)

    def reloc_name(self, label):
        """The label to store for a name: a function means its stub."""
        v = self.globals_by_name.get(label)
        if v is not None and v.is_function:
            return f'__ind_{v.name}'
        return label
