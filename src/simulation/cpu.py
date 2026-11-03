# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.

"""
TARA CPU Core
Teaching Architecture for RISC Assembly - CS2300
ISA: 16-bit fixed-width instructions, 5-bit opcode, 8 registers, 2KB memory
"""

# ─── Opcodes ───────────────────────────────────────────────────────────────────
OP = {
    'NOP':  0,  'HLT':  1,  'MOV':  2,  'LIL':  3,  'LIH':  4,
    'LDW':  5,  'STW':  6,  'LDB':  7,  'STB':  8,
    'ADD':  9,  'SUB': 10,  'ADDI':11,  'MUL': 12,
    'AND': 13,  'OR':  14,  'XOR': 15,  'NOT': 16,
    'SHL': 17,  'SHR': 18,  'SLT': 19,
    'BZ':  20,  'BN':  21,  'JMP': 22,  'CALL':23,  'RET': 24,
    'PUSH':25,  'POP': 26,
}
OP_NAME = {v: k for k, v in OP.items()}

# Instruction formats
FMT = {
    'NOP': 'F0', 'HLT': 'F0', 'RET': 'F0',
    'ADD': 'F1', 'SUB': 'F1', 'MUL': 'F1', 'AND': 'F1', 'OR': 'F1',
    'XOR': 'F1', 'SLT': 'F1',
    'MOV': 'F2', 'NOT': 'F2',
    'LIL': 'F3', 'LIH': 'F3', 'ADDI': 'F3', 'SHL': 'F3', 'SHR': 'F3',
    'LDW': 'F4', 'STW': 'F4', 'LDB': 'F4', 'STB': 'F4',
    'BZ':  'F5', 'BN':  'F5',
    'JMP': 'F6', 'CALL':'F6',
    'PUSH':'F7', 'POP': 'F7',
}


def sext(val, bits):
    """Sign-extend a value from 'bits' width to Python int."""
    if val & (1 << (bits - 1)):
        val -= (1 << bits)
    return val


class TaraCPU:
    MEM_SIZE = 2048

    def __init__(self):
        self.reset()

    def reset(self):
        self.reg = [0] * 8          # R0–R7
        self.pc = 0                  # Program counter (byte address)
        self.mem = bytearray(self.MEM_SIZE)
        self.halted = False
        self.error = None
        self.history = []            # list of state snapshots per instruction
        self.cycle_count = 0
        self.instr_count = 0
        self.last_instr = None       # last decoded instruction dict

    def load_program(self, words, start=0):
        """Load list of 16-bit instruction words into memory."""
        for i, w in enumerate(words):
            addr = start + i * 2
            if addr + 1 < self.MEM_SIZE:
                self.mem[addr]     = (w >> 8) & 0xFF
                self.mem[addr + 1] =  w       & 0xFF

    def read_word(self, addr):
        addr &= 0x7FF
        return (self.mem[addr] << 8) | self.mem[addr + 1]

    def write_word(self, addr, val):
        addr &= 0x7FF
        val &= 0xFFFF
        self.mem[addr]     = (val >> 8) & 0xFF
        self.mem[addr + 1] =  val       & 0xFF

    def read_byte(self, addr):
        return self.mem[addr & 0x7FF]

    def write_byte(self, addr, val):
        self.mem[addr & 0x7FF] = val & 0xFF

    def _r(self, i):
        return self.reg[i] & 0xFFFF

    def _wr(self, i, val):
        self.reg[i] = val & 0xFFFF

    def decode(self, word):
        op   = (word >> 11) & 0x1F
        name = OP_NAME.get(op, f'???({op})')
        fmt  = FMT.get(name, '??')

        # rd / rsA / rsB cover all register fields; rbase=rsA, rdata=rtest=rstk=rd
        rd   = (word >> 8) & 0x7
        rsA  = (word >> 5) & 0x7
        rsB  = (word >> 2) & 0x7
        imm8 =  word       & 0xFF
        off5 =  word       & 0x1F
        rel8 =  word       & 0xFF
        rel11=  word       & 0x7FF

        return dict(word=word, op=op, name=name, fmt=fmt,
                    rd=rd, rsA=rsA, rsB=rsB,
                    imm8=imm8, off5=off5,
                    rel8=rel8, rel11=rel11)

    def step(self, record_history=True):
        """Execute one instruction. Returns True if executed, False if halted."""
        if self.halted:
            return False

        # Snapshot state before execution
        snap = None
        if record_history:
            snap = {
                'pc': self.pc,
                'reg': list(self.reg),
                'cycle': self.cycle_count,
            }

        if self.pc + 1 >= self.MEM_SIZE:
            self.error = f"PC out of bounds: 0x{self.pc:04X}"
            self.halted = True
            return False

        word = self.read_word(self.pc)
        d = self.decode(word)
        self.last_instr = d
        next_pc = (self.pc + 2) & 0xFFFF

        name = d['name']
        self.cycle_count += 1
        self.instr_count += 1

        try:
            if name == 'NOP':
                pass

            elif name == 'HLT':
                self.halted = True

            elif name == 'MOV':
                self._wr(d['rd'], self._r(d['rsA']))

            elif name == 'LIL':
                self._wr(d['rd'], d['imm8'])

            elif name == 'LIH':
                v = self._r(d['rd']) & 0x00FF
                self._wr(d['rd'], v | (d['imm8'] << 8))

            elif name == 'LDW':
                ea = (self._r(d['rsA']) + sext(d['off5'], 5)) & 0x7FF
                self._wr(d['rd'], self.read_word(ea))

            elif name == 'STW':
                ea = (self._r(d['rsA']) + sext(d['off5'], 5)) & 0x7FF
                self.write_word(ea, self._r(d['rd']))

            elif name == 'LDB':
                ea = (self._r(d['rsA']) + sext(d['off5'], 5)) & 0x7FF
                self._wr(d['rd'], self.read_byte(ea))

            elif name == 'STB':
                ea = (self._r(d['rsA']) + sext(d['off5'], 5)) & 0x7FF
                self.write_byte(ea, self._r(d['rd']) & 0xFF)

            elif name == 'ADD':
                self._wr(d['rd'], self._r(d['rsA']) + self._r(d['rsB']))

            elif name == 'SUB':
                self._wr(d['rd'], self._r(d['rsA']) - self._r(d['rsB']))

            elif name == 'ADDI':
                self._wr(d['rd'], self._r(d['rd']) + sext(d['imm8'], 8))

            elif name == 'MUL':
                self._wr(d['rd'], self._r(d['rsA']) * self._r(d['rsB']))

            elif name == 'AND':
                self._wr(d['rd'], self._r(d['rsA']) & self._r(d['rsB']))

            elif name == 'OR':
                self._wr(d['rd'], self._r(d['rsA']) | self._r(d['rsB']))

            elif name == 'XOR':
                self._wr(d['rd'], self._r(d['rsA']) ^ self._r(d['rsB']))

            elif name == 'NOT':
                self._wr(d['rd'], ~self._r(d['rsA']) & 0xFFFF)

            elif name == 'SHL':
                shamt = d['imm8'] & 0x1F
                self._wr(d['rd'], self._r(d['rd']) << shamt)

            elif name == 'SHR':
                shamt = d['imm8'] & 0x1F
                self._wr(d['rd'], self._r(d['rd']) >> shamt)

            elif name == 'SLT':
                a = sext(self._r(d['rsA']), 16)
                b = sext(self._r(d['rsB']), 16)
                self._wr(d['rd'], 1 if a < b else 0)

            elif name == 'BZ':
                val = sext(self._r(d['rd']), 16)
                if val == 0:
                    next_pc = (next_pc + sext(d['rel8'], 8) * 2) & 0xFFFF

            elif name == 'BN':
                val = sext(self._r(d['rd']), 16)
                if val < 0:
                    next_pc = (next_pc + sext(d['rel8'], 8) * 2) & 0xFFFF

            elif name == 'JMP':
                next_pc = (next_pc + sext(d['rel11'], 11) * 2) & 0xFFFF

            elif name == 'CALL':
                self._wr(6, next_pc)
                next_pc = (next_pc + sext(d['rel11'], 11) * 2) & 0xFFFF

            elif name == 'RET':
                next_pc = self._r(6)

            elif name == 'PUSH':
                self._wr(7, self._r(7) - 2)
                self.write_word(self._r(7), self._r(d['rd']))

            elif name == 'POP':
                self._wr(d['rd'], self.read_word(self._r(7)))
                self._wr(7, self._r(7) + 2)

            else:
                self.error = f"Unknown opcode {d['op']} at PC=0x{self.pc:04X}"
                self.halted = True
                return False

        except Exception as e:
            self.error = str(e)
            self.halted = True
            return False

        self.pc = next_pc & 0x7FF
        if record_history:
            snap['instr'] = d
            self.history.append(snap)
        return not self.halted
