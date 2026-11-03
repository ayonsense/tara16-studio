# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""A TARA16 CPU, so that `--run` works without anything else installed.

It is a transcription of the golden model that defines the instruction set
for TARA Studio, the Verilog build and the TTL board
(`python-sim/tara_simulator_fpga/src/simulation/cpu.py`). `tests/golden.py`
runs both on every test program and compares registers, program counter and
all 2 KB of memory, so this copy cannot drift.

Memory map: the stack grows down from 0x5FE, the keyboard byte is 0x5FF,
and the 64x64 screen is 0x600-0x7FF, one bit per pixel, row 0 at the
bottom, the leftmost pixel in the highest bit.
"""
MEM_SIZE = 2048
FB = 0x600
KEYS = 0x5FF

OP_NAME = {
    0: 'NOP', 1: 'HLT', 2: 'MOV', 3: 'LIL', 4: 'LIH', 5: 'LDW', 6: 'STW',
    7: 'LDB', 8: 'STB', 9: 'ADD', 10: 'SUB', 11: 'ADDI', 12: 'MUL', 13: 'AND',
    14: 'OR', 15: 'XOR', 16: 'NOT', 17: 'SHL', 18: 'SHR', 19: 'SLT', 20: 'BZ',
    21: 'BN', 22: 'JMP', 23: 'CALL', 24: 'RET', 25: 'PUSH', 26: 'POP',
}


def sext(val, bits):
    """A value of `bits` bits, read as a signed number."""
    val &= (1 << bits) - 1
    return val - (1 << bits) if val & (1 << (bits - 1)) else val


class CPU:
    """A TARA16: eight registers, a program counter, and 2 KB of memory."""
    def __init__(self):
        self.mem = bytearray(MEM_SIZE)
        self.reg = [0] * 8
        self.pc = 0
        self.halted = False
        self.error = None
        self.instr_count = 0
        self.last = None

    def load(self, words, start=0):
        """Put an image into memory, ready to run from address zero."""
        for i, w in enumerate(words):
            a = start + i * 2
            if a + 1 < MEM_SIZE:
                self.mem[a] = (w >> 8) & 0xFF
                self.mem[a + 1] = w & 0xFF

    def read_word(self, a):
        """The 16-bit word at an address, big-endian."""
        a &= 0x7FF
        return (self.mem[a] << 8) | self.mem[a + 1]

    def write_word(self, a, v):
        """Write a 16-bit word at an address, big-endian."""
        a &= 0x7FF
        self.mem[a] = (v >> 8) & 0xFF
        self.mem[a + 1] = v & 0xFF

    def _r(self, i):
        """The value of a register, as an unsigned 16-bit number."""
        return self.reg[i] & 0xFFFF

    def _w(self, i, v):
        """Write a register, keeping only 16 bits."""
        self.reg[i] = v & 0xFFFF

    def step(self):
        """Execute one instruction."""
        if self.halted:
            return False
        if self.pc + 1 >= MEM_SIZE:
            self.error = f'PC out of bounds: 0x{self.pc:04X}'
            self.halted = True
            return False
        word = self.read_word(self.pc)
        op = (word >> 11) & 0x1F
        rd = (word >> 8) & 7
        ra = (word >> 5) & 7
        rb = (word >> 2) & 7
        imm8 = word & 0xFF
        off5 = word & 0x1F
        rel11 = word & 0x7FF
        name = OP_NAME.get(op)
        self.last = (name, rd, ra, rb, imm8, off5, self.pc)
        nxt = (self.pc + 2) & 0xFFFF
        self.instr_count += 1
        try:
            if name == 'NOP':
                pass
            elif name == 'HLT':
                self.halted = True
            elif name == 'MOV':
                self._w(rd, self._r(ra))
            elif name == 'LIL':
                self._w(rd, imm8)
            elif name == 'LIH':
                self._w(rd, (self._r(rd) & 0x00FF) | (imm8 << 8))
            elif name == 'LDW':
                self._w(rd, self.read_word((self._r(ra) + sext(off5, 5)) & 0x7FF))
            elif name == 'STW':
                self.write_word((self._r(ra) + sext(off5, 5)) & 0x7FF, self._r(rd))
            elif name == 'LDB':
                self._w(rd, self.mem[(self._r(ra) + sext(off5, 5)) & 0x7FF])
            elif name == 'STB':
                self.mem[(self._r(ra) + sext(off5, 5)) & 0x7FF] = self._r(rd) & 0xFF
            elif name == 'ADD':
                self._w(rd, self._r(ra) + self._r(rb))
            elif name == 'SUB':
                self._w(rd, self._r(ra) - self._r(rb))
            elif name == 'ADDI':
                self._w(rd, self._r(rd) + sext(imm8, 8))
            elif name == 'MUL':
                self._w(rd, self._r(ra) * self._r(rb))
            elif name == 'AND':
                self._w(rd, self._r(ra) & self._r(rb))
            elif name == 'OR':
                self._w(rd, self._r(ra) | self._r(rb))
            elif name == 'XOR':
                self._w(rd, self._r(ra) ^ self._r(rb))
            elif name == 'NOT':
                self._w(rd, ~self._r(ra) & 0xFFFF)
            elif name == 'SHL':
                self._w(rd, self._r(rd) << (imm8 & 0x1F))
            elif name == 'SHR':
                self._w(rd, self._r(rd) >> (imm8 & 0x1F))
            elif name == 'SLT':
                self._w(rd, 1 if sext(self._r(ra), 16) < sext(self._r(rb), 16) else 0)
            elif name == 'BZ':
                if sext(self._r(rd), 16) == 0:
                    nxt = (nxt + sext(imm8, 8) * 2) & 0xFFFF
            elif name == 'BN':
                if sext(self._r(rd), 16) < 0:
                    nxt = (nxt + sext(imm8, 8) * 2) & 0xFFFF
            elif name == 'JMP':
                nxt = (nxt + sext(rel11, 11) * 2) & 0xFFFF
            elif name == 'CALL':
                self._w(6, nxt)
                nxt = (nxt + sext(rel11, 11) * 2) & 0xFFFF
            elif name == 'RET':
                nxt = self._r(6)
            elif name == 'PUSH':
                self._w(7, self._r(7) - 2)
                self.write_word(self._r(7), self._r(rd))
            elif name == 'POP':
                self._w(rd, self.read_word(self._r(7)))
                self._w(7, self._r(7) + 2)
            else:
                self.error = f'Unknown opcode {op} at PC=0x{self.pc:04X}'
                self.halted = True
                return False
        except Exception as e:                       # e.g. a word at 0x7FF
            self.error = str(e)
            self.halted = True
            return False
        self.pc = nxt & 0x7FF
        return not self.halted


def load_hex(path):
    """Read a .hex image: one 16-bit word per line."""
    words = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                words.append(int(line, 16))
    return words


def run(words, max_steps=5_000_000, keys=None, stack_limit=None, keys_fn=None):
    """Run an image. Returns (cpu, instructions executed, lowest SP seen)."""
    cpu = CPU()
    cpu.load(words)
    if keys is not None:
        cpu.mem[KEYS] = keys & 0xFF
    n = 0
    min_sp = 0xFFFF
    while not cpu.halted and n < max_steps:
        if keys_fn is not None:
            cpu.mem[KEYS] = keys_fn(n) & 0xFF
        cpu.step()
        n += 1
        sp = cpu.reg[7]
        if sp < min_sp and n > 2:
            min_sp = sp
            if stack_limit is not None and sp < stack_limit:
                cpu.error = (f'stack overflow: SP=0x{sp:04X} below '
                             f'0x{stack_limit:04X} at PC=0x{cpu.pc:04X}')
                cpu.halted = True
    return cpu, n, min_sp


def display_text(cpu):
    """The screen as text, row 63 (the top) first."""
    rows = []
    for y in range(63, -1, -1):
        line = []
        for x in range(64):
            byte = cpu.mem[FB + y * 8 + (x >> 3)]
            line.append('#' if byte & (0x80 >> (x & 7)) else '.')
        rows.append(''.join(line))
    return '\n'.join(rows)


def display_png(cpu, path, scale=6):
    """Save the screen as a PNG, if Pillow is installed."""
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit('tara16-cc: --png needs the Pillow package')
    img = Image.new('1', (64, 64))
    px = img.load()
    for y in range(64):
        for x in range(64):
            byte = cpu.mem[FB + y * 8 + (x >> 3)]
            px[x, 63 - y] = 1 if byte & (0x80 >> (x & 7)) else 0
    img.resize((64 * scale, 64 * scale), Image.NEAREST).save(path)
