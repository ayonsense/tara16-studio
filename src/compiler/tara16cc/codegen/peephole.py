# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""The clean-up pass.

The tree walk cannot see across the seams between the pieces it generates:
a jump to the next instruction, a store followed at once by a load of the
same slot, two ADDIs in a row. This pass looks through a short window of
instructions and removes the waste. It runs until nothing changes, and
`-fno-peephole` switches it off.
"""
from .target import SP


class PeepholeMixin:
    """The clean-up pass over the finished instruction list."""
    def _live(self, i):
        """The next item after i that is still alive and not a comment."""
        for j in range(i + 1, len(self.items)):
            if not self.items[j].dead and self.items[j].kind != 'comment':
                return j
        return len(self.items)

    def _find_label(self, name):
        """Where the label called `name` is, or -1."""
        for i, it in enumerate(self.items):
            if it.kind == 'label' and not it.dead and it.text == name:
                return i
        return -1

    def _label_used(self, name):
        """Does any live instruction still refer to this label?"""
        for it in self.items:
            if it.dead:
                continue
            if it.kind == 'ins' and it.sym == name:
                return True
            if it.kind == 'raw' and name in (it.text or ''):
                return True
        return False

    def _near(self, i, name):
        """Is label `name` in this function and safely within a branch's reach
        of item i? BZ and BN reach 128 words; one aimed further is rewritten
        by the assembler into three words, slower when it falls through, so
        threading a branch there would cost more than the jump it saves."""
        l = self._find_label(name)
        if l < 0:
            return False
        lo, hi = (i + 1, l) if l > i else (l, i)
        words = 0
        for it in self.items[lo:hi]:
            if it.dead:
                continue
            if it.kind == 'ins':
                words += 2 if it.op == 'LA' else 1
            elif it.kind == 'raw':
                words += 1
        return words <= 100

    def _is(self, it, op):
        """Is this item a live instruction with this opcode?"""
        return it.kind == 'ins' and not it.dead and it.op == op

    def peephole(self):
        """Rewrite short sequences into shorter ones, until nothing changes."""
        changed = True
        rounds = 0
        while changed and rounds < 20:
            changed = False
            rounds += 1
            for i, it in enumerate(self.items):
                if it.dead or it.kind != 'ins':
                    continue

                # a jump or branch to one of the labels that follow it
                if it.op in ('JMP', 'BZ', 'BN'):
                    j = self._live(i)
                    hit = False
                    while j < len(self.items) and self.items[j].kind == 'label':
                        if self.items[j].text == it.sym:
                            hit = True
                        j = self._live(j)
                    if hit:
                        it.dead = True
                        changed = True
                        continue

                # jump threading: JMP L ; ... L: JMP M  ->  JMP M
                if it.op in ('JMP', 'BZ', 'BN'):
                    l = self._find_label(it.sym)
                    if l >= 0:
                        j = self._live(l)
                        while j < len(self.items) and self.items[j].kind == 'label':
                            j = self._live(j)
                        if j < len(self.items) and self._is(self.items[j], 'JMP') \
                                and self.items[j].sym != it.sym and \
                                (it.op == 'JMP' or self._near(i, self.items[j].sym)):
                            it.sym = self.items[j].sym
                            changed = True

                # code after an unconditional transfer that no label reaches
                if it.op in ('JMP', 'RET'):
                    j = self._live(i)
                    while j < len(self.items):
                        n = self.items[j]
                        if n.kind == 'raw':
                            break
                        if n.kind == 'label' and self._label_used(n.text):
                            break
                        n.dead = True
                        changed = True
                        j = self._live(j)

                # STW r, k(SP) ; LDW s, k(SP)  ->  STW ; MOV s, r
                if it.op in ('STW', 'STB') and it.r[1] == SP:
                    j = self._live(i)
                    if j < len(self.items):
                        n = self.items[j]
                        if it.op == 'STW' and self._is(n, 'LDW') and \
                                n.r[1] == SP and n.imm == it.imm:
                            if n.r[0] == it.r[0]:
                                n.dead = True
                            else:
                                n.op = 'MOV'
                                n.r[1] = it.r[0]
                                n.imm = 0
                            changed = True

                # ADDI r, a ; ADDI r, b  ->  ADDI r, a+b
                if it.op == 'ADDI':
                    j = self._live(i)
                    if j < len(self.items) and self._is(self.items[j], 'ADDI') \
                            and self.items[j].r[0] == it.r[0]:
                        s = it.imm + self.items[j].imm
                        if -128 <= s <= 127:
                            self.items[j].dead = True
                            it.imm = s
                            if s == 0:
                                it.dead = True
                            changed = True
                            continue

                # PUSH r ; POP r  ->  nothing
                if it.op == 'PUSH':
                    j = self._live(i)
                    if j < len(self.items) and self._is(self.items[j], 'POP') \
                            and self.items[j].r[0] == it.r[0]:
                        it.dead = True
                        self.items[j].dead = True
                        changed = True

                # MOV a, b ; MOV b, a  ->  MOV a, b
                if it.op == 'MOV':
                    j = self._live(i)
                    if j < len(self.items) and self._is(self.items[j], 'MOV') \
                            and self.items[j].r[0] == it.r[1] \
                            and self.items[j].r[1] == it.r[0]:
                        self.items[j].dead = True
                        changed = True

        # labels the compiler made and nobody uses
        for i in range(self.body_start, len(self.items)):
            it = self.items[i]
            if it.kind == 'label' and not it.dead and it.text.startswith('.') and \
                    not it.text.startswith('.Lret.') and not self._label_used(it.text):
                it.dead = True
