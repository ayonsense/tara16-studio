#!/usr/bin/env python3
# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""tara16_as.py -- assembler/linker for the TARA16 C toolchain.

The input language is a SUPERSET of the TARA Studio assembly syntax
(`src/assembler/asm.py`): every Studio program assembles unchanged. The
extensions exist because a C compiler needs data and symbolic addresses:

    .text / .zdata / .data / .bss / .init   choose a section
    .chunk NAME        start a garbage-collection unit (a function or object)
    .keep              mark the current chunk as a GC root
    .word  e[, e...]   16-bit big-endian words     .byte e[, e...]
    .zero  N           N zero bytes                .align N
    .equ   NAME, e     define an absolute symbol
    LA  Rd, sym+off    pseudo: load an address   -> LIL (1 word) if < 0x100,
                                                    else LIL+LIH (2 words)
    LI  Rd, expr       pseudo: load a constant   -> same relaxation
    expressions:       123 0x7B 0b101 -5 sym sym+4 lo(e) hi(e) (e)

Branch relaxation: BZ/BN reach only +-128 instructions. An out-of-range
`BZ Rt, far` is rewritten to the 3-word sequence
        BZ  Rt, +1   ;  JMP skip  ;  JMP far  ; skip:
(JMP/CALL reach all of the 2 KB memory, so they never need relaxing).

Layout: .init (crt0, address 0) | .zdata | .text | .data | .bss.
.zdata comes first so that small globals land below 0x100, where `LA` is a
single LIL instruction.

Chunk GC: chunks not reachable (by symbol reference) from a root are
dropped -- unused functions, unused string literals, __func__ names, and
runtime routines. Code outside any .chunk is always kept.

Outputs (any subset):
    .hex    one 16-bit word per line -- $readmemh image for the Verilog build
    .lst    listing (address, words, source)
    .sym    symbol table
    .tara   TARA Studio-loadable program: plain instructions only. Data and
            .bss are NOP (0x0000) placeholders at their real addresses, and a
            generated `__init` routine (placed after everything else) stores
            the non-zero data words before jumping to main. Addresses are
            identical to the .hex image, so both behave the same.
"""
import re
import sys
import os

# ---------------------------------------------------------------------------
# ISA (must match src/simulation/cpu.py of the golden simulator)
# ---------------------------------------------------------------------------
OP = {
    'NOP': 0, 'HLT': 1, 'MOV': 2, 'LIL': 3, 'LIH': 4,
    'LDW': 5, 'STW': 6, 'LDB': 7, 'STB': 8,
    'ADD': 9, 'SUB': 10, 'ADDI': 11, 'MUL': 12,
    'AND': 13, 'OR': 14, 'XOR': 15, 'NOT': 16,
    'SHL': 17, 'SHR': 18, 'SLT': 19,
    'BZ': 20, 'BN': 21, 'JMP': 22, 'CALL': 23, 'RET': 24,
    'PUSH': 25, 'POP': 26,
}
OP_NAME = {v: k for k, v in OP.items()}
F0 = {'NOP', 'HLT', 'RET'}
F1 = {'ADD', 'SUB', 'MUL', 'AND', 'OR', 'XOR', 'SLT'}
F2 = {'MOV', 'NOT'}
F3 = {'LIL', 'LIH', 'ADDI', 'SHL', 'SHR'}
F4 = {'LDW', 'STW', 'LDB', 'STB'}
F5 = {'BZ', 'BN'}
F6 = {'JMP', 'CALL'}
F7 = {'PUSH', 'POP'}
PSEUDO = {'LA', 'LI'}

SECTION_ORDER = ['init', 'zdata', 'text', 'data', 'bss']
CODE_SECTIONS = {'init', 'text'}
MEM_SIZE = 2048


class AsmError(Exception):
    """Something the assembler or linker could not do."""
    pass


def sext(v, bits):
    """A value of `bits` bits, read as a signed number."""
    v &= (1 << bits) - 1
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------
_TOK = re.compile(r'\s*(0[xX][0-9a-fA-F]+|0[bB][01]+|\d+|[A-Za-z_.$][\w.$]*|[()+\-])')


def tokenize_expr(s):
    """Cut an expression such as `label+4` into pieces."""
    toks, pos = [], 0
    s = s.strip()
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m:
            raise AsmError(f"bad expression '{s}'")
        toks.append(m.group(1))
        pos = m.end()
    return toks


class Expr:
    """Parsed expression: evaluated lazily against a symbol table."""
    def __init__(self, text):
        self.text = text.strip()
        self.toks = tokenize_expr(self.text)
        self.syms = [t for t in self.toks
                     if re.match(r'[A-Za-z_.$]', t) and t not in ('lo', 'hi')]
        # validate syntax now
        self._parse(lambda name: 0)

    def _parse(self, lookup):
        """Read the text into chunks, labels, instructions and data."""
        toks, i = self.toks, [0]

        def peek():
            """The token under consideration."""
            return toks[i[0]] if i[0] < len(toks) else None

        def take():
            """Take the token under consideration and step past it."""
            t = peek()
            i[0] += 1
            return t

        def primary():
            """A number, a name, or a parenthesised expression."""
            t = take()
            if t is None:
                raise AsmError(f"bad expression '{self.text}'")
            if t == '(':
                v = expr()
                if take() != ')':
                    raise AsmError(f"missing ')' in '{self.text}'")
                return v
            if t == '-':
                return -primary()
            if t == '+':
                return primary()
            if t in ('lo', 'hi') and peek() == '(':
                take()
                v = expr()
                if take() != ')':
                    raise AsmError(f"missing ')' in '{self.text}'")
                return (v & 0xFF) if t == 'lo' else ((v >> 8) & 0xFF)
            if re.match(r'0[xX]', t):
                return int(t, 16)
            if re.match(r'0[bB]', t):
                return int(t[2:], 2)
            if t.isdigit():
                return int(t)
            return lookup(t)

        def expr():
            """A sum or difference of primaries."""
            v = primary()
            while peek() in ('+', '-'):
                op = take()
                r = primary()
                v = v + r if op == '+' else v - r
            return v

        v = expr()
        if i[0] != len(toks):
            raise AsmError(f"trailing junk in expression '{self.text}'")
        return v

    def value(self, symtab):
        """The number this expression stands for, once labels are known."""
        def lookup(name):
            """The address of a symbol, or an error if there is none."""
            if name not in symtab:
                raise AsmError(f"undefined symbol '{name}'")
            return symtab[name]
        return self._parse(lookup)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
class Item:
    """One source statement that occupies memory (instruction or data)."""
    __slots__ = ('kind', 'mnem', 'ops', 'exprs', 'size', 'addr', 'line',
                 'lineno', 'src', 'data', 'align', 'chunk', 'labels')

    def __init__(self, kind, line, lineno, src):
        self.kind = kind          # 'insn' | 'data' | 'align'
        self.mnem = None
        self.ops = []
        self.exprs = []
        self.size = 0
        self.addr = 0
        self.line = line
        self.lineno = lineno
        self.src = src
        self.data = None
        self.align = 1
        self.chunk = None
        self.labels = []


class Chunk:
    """One function or one variable: the unit the linker keeps or drops."""
    def __init__(self, name, section, root):
        self.name = name
        self.section = section
        self.root = root
        self.items = []
        self.labels = []      # labels defined in this chunk
        self.refs = set()     # symbols referenced
        self.live = False
        self.lines = []       # source text belonging to this chunk


def parse_reg(tok):
    """The register number a name such as R3 or SP stands for."""
    t = tok.strip().upper()
    if t in ('SP',):
        return 7
    if t in ('LR',):
        return 6
    if len(t) == 2 and t[0] == 'R' and t[1] in '01234567':
        return int(t[1])
    raise AsmError(f"invalid register '{tok}'")


_MEM = re.compile(r'^(.*)\(\s*([RrSsLl][0-9PpRr])\s*\)$')


def parse_mem(tok):
    """The `off(Rb)` form of a load or store, as (offset, base)."""
    m = _MEM.match(tok.strip())
    if not m:
        raise AsmError(f"invalid memory operand '{tok}'")
    off = m.group(1).strip() or '0'
    return Expr(off), parse_reg(m.group(2))


def split_operands(s):
    """Split an operand list on commas, ignoring commas in brackets."""
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
class Program:
    """One assembly text, read into chunks, labels and instructions."""
    def __init__(self):
        self.chunks = []
        self.equs = {}
        self.errors = []
        self.label_chunk = {}

    def parse(self, text, filename='<input>'):
        """Read assembly text; errors are collected rather than raised."""
        section = 'text'
        cur = {}                     # section -> current chunk
        implicit_n = [0]

        def chunk_for(sec):
            """The chunk this section is filling, making one if needed."""
            if sec not in cur:
                implicit_n[0] += 1
                c = Chunk(f'<{filename}:{sec}:{implicit_n[0]}>', sec, True)
                self.chunks.append(c)
                cur[sec] = c
            return cur[sec]

        pending_labels = []
        raw_lines = text.splitlines()
        owner = [None] * (len(raw_lines) + 1)   # chunk owning each line
        for lineno, raw in enumerate(raw_lines, 1):
            line = raw.split(';', 1)[0].strip()
            where = f'{filename}:{lineno}'
            if not line:
                continue
            try:
                # labels
                while True:
                    m = re.match(r'^([A-Za-z_.$][\w.$]*)\s*:(.*)$', line)
                    if not m:
                        break
                    name = m.group(1)
                    c = chunk_for(section)
                    owner[lineno] = c
                    if name in self.label_chunk or name in self.equs:
                        raise AsmError(f"duplicate label '{name}'")
                    self.label_chunk[name] = c
                    c.labels.append(name)
                    pending_labels.append(name)
                    line = m.group(2).strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                word = parts[0]
                rest = parts[1].strip() if len(parts) > 1 else ''
                lw = word.lower()
                if lw.startswith('.'):
                    d = lw
                    if d in ('.text', '.data', '.zdata', '.bss', '.init'):
                        section = d[1:]
                        continue
                    if d == '.section':
                        section = rest.strip().lstrip('.')
                        if section not in SECTION_ORDER:
                            raise AsmError(f"unknown section '{rest}'")
                        continue
                    if d == '.chunk':
                        c = Chunk(rest or f'<chunk@{where}>', section, False)
                        self.chunks.append(c)
                        cur[section] = c
                        owner[lineno] = c
                        continue
                    if d == '.keep':
                        chunk_for(section).root = True
                        continue
                    if d in ('.global', '.globl', '.local', '.type', '.size'):
                        continue
                    if d in ('.equ', '.set'):
                        name, e = [x.strip() for x in rest.split(',', 1)]
                        self.equs[name] = Expr(e)
                        continue
                    c = chunk_for(section)
                    owner[lineno] = c
                    it = Item('data', line, lineno, where)
                    it.chunk = c
                    it.labels, pending_labels = pending_labels, []
                    if d == '.word':
                        it.exprs = [Expr(x) for x in split_operands(rest)]
                        it.data = 'word'
                        it.size = 2 * len(it.exprs)
                    elif d == '.byte':
                        it.exprs = [Expr(x) for x in split_operands(rest)]
                        it.data = 'byte'
                        it.size = len(it.exprs)
                    elif d in ('.zero', '.space', '.skip'):
                        it.data = 'zero'
                        it.size = Expr(rest).value({})
                    elif d in ('.align', '.balign'):
                        it.kind = 'align'
                        it.align = Expr(rest).value({})
                    else:
                        raise AsmError(f"unknown directive '{word}'")
                    for e in it.exprs:
                        c.refs.update(e.syms)
                    c.items.append(it)
                    continue
                # instruction
                mnem = word.upper()
                if mnem not in OP and mnem not in PSEUDO:
                    raise AsmError(f"unknown mnemonic '{word}'")
                c = chunk_for(section)
                owner[lineno] = c
                it = Item('insn', line, lineno, where)
                it.chunk = c
                it.labels, pending_labels = pending_labels, []
                it.mnem = mnem
                ops = split_operands(rest)
                self._parse_insn(it, ops)
                for e in it.exprs:
                    if e is not None:
                        c.refs.update(e.syms)
                c.items.append(it)
            except AsmError as e:
                self.errors.append(f'{where}: {e}')
        # unowned lines (comments, blanks, section switches) belong to the
        # next chunk that owns a line; the tail goes to the last chunk
        nxt = None
        for i in range(len(raw_lines), 0, -1):
            if owner[i] is not None:
                nxt = owner[i]
            else:
                owner[i] = nxt
        last = None
        for i in range(1, len(raw_lines) + 1):
            c = owner[i] or last
            if c is not None:
                c.lines.append(raw_lines[i - 1])
                last = c
        return self

    def _parse_insn(self, it, ops):
        """Turn one instruction into the fields the encoder needs."""
        m = it.mnem

        def need(n):
            """Check that an instruction was given the right operand count."""
            if len(ops) != n:
                raise AsmError(f"{m} expects {n} operand(s), got {len(ops)}")
        if m in F0:
            need(0)
            it.size = 2
        elif m in F1:
            need(3)
            it.ops = [parse_reg(o) for o in ops]
            it.size = 2
        elif m in F2:
            need(2)
            it.ops = [parse_reg(o) for o in ops]
            it.size = 2
        elif m in F3:
            need(2)
            it.ops = [parse_reg(ops[0])]
            it.exprs = [Expr(ops[1])]
            it.size = 2
        elif m in F4:
            need(2)
            off, base = parse_mem(ops[1])
            it.ops = [parse_reg(ops[0]), base]
            it.exprs = [off]
            it.size = 2
        elif m in F5:
            need(2)
            it.ops = [parse_reg(ops[0])]
            it.exprs = [Expr(ops[1])]
            it.size = 2            # may relax to 6
        elif m in F6:
            need(1)
            it.exprs = [Expr(ops[0])]
            it.size = 2
        elif m in F7:
            need(1)
            it.ops = [parse_reg(ops[0])]
            it.size = 2
        elif m in PSEUDO:
            need(2)
            it.ops = [parse_reg(ops[0])]
            it.exprs = [Expr(ops[1])]
            it.size = 2            # may relax to 4


# ---------------------------------------------------------------------------
# Linking: GC, layout, relaxation, encoding
# ---------------------------------------------------------------------------
class Image:
    """A linked program: bytes, a symbol table, and where each part sits."""
    pass


def link(prog, roots=('_start',), gc=True, mem_size=MEM_SIZE, defines=None):
    """Drop unreachable chunks, place the rest, resolve every label."""
    if prog.errors:
        raise AsmError('\n'.join(prog.errors))
    defines = dict(defines or {})

    # --- GC -----------------------------------------------------------------
    for c in prog.chunks:
        c.live = c.root or not gc
    work = [c for c in prog.chunks if c.live]
    for r in roots:
        if r in prog.label_chunk:
            c = prog.label_chunk[r]
            if not c.live:
                c.live = True
                work.append(c)
    equ_refs = {}
    for name, e in prog.equs.items():
        equ_refs[name] = e.syms
    while work:
        c = work.pop()
        refs = set(c.refs)
        # follow .equ indirections
        stack = list(refs)
        while stack:
            s = stack.pop()
            for t in equ_refs.get(s, ()):
                if t not in refs:
                    refs.add(t)
                    stack.append(t)
        for s in refs:
            d = prog.label_chunk.get(s)
            if d is not None and not d.live:
                d.live = True
                work.append(d)
    live = [c for c in prog.chunks if c.live]
    ordered = []
    for sec in SECTION_ORDER:
        ordered += [c for c in live if c.section == sec]

    items = []
    for c in ordered:
        items += c.items

    # --- relaxation loop ------------------------------------------------------
    def layout():
        """Place every live chunk and work out where each label lands."""
        symtab = dict(defines)
        addr = 0
        sec_bounds = {}
        cur_sec = None
        for c in ordered:
            if c.section != cur_sec:
                if cur_sec is not None:
                    sec_bounds[cur_sec][1] = addr
                cur_sec = c.section
                if cur_sec in ('zdata', 'text', 'data', 'bss', 'init'):
                    addr = (addr + 1) & ~1          # sections start even
                sec_bounds.setdefault(cur_sec, [addr, addr])
                sec_bounds[cur_sec][0] = min(sec_bounds[cur_sec][0], addr)
            for it in c.items:
                if it.kind == 'align':
                    a = max(1, it.align)
                    pad = (-addr) % a
                    it.size = pad
                if it.kind == 'insn' and addr & 1:
                    raise AsmError(f"{it.src}: instruction at odd address "
                                   f"0x{addr:03X} (missing .align 2?)")
                it.addr = addr
                for l in it.labels:
                    symtab[l] = addr
                addr += it.size
            # labels at the very end of a chunk (no following item)
        if cur_sec is not None:
            sec_bounds[cur_sec][1] = addr
        # labels with no item after them inside their chunk
        for c in ordered:
            end = c.items[-1].addr + c.items[-1].size if c.items else None
            for l in c.labels:
                if l not in symtab:
                    symtab[l] = end if end is not None else 0
        return symtab, addr, sec_bounds

    # chunks with labels but no items (e.g. label at end): give them address
    for _ in range(100):
        symtab, end, bounds = layout()
        for name, e in prog.equs.items():
            symtab[name] = e.value(symtab)
        changed = False
        for it in items:
            if it.kind != 'insn':
                continue
            if it.mnem in F5 and it.size == 2:
                t = it.exprs[0].value(symtab)
                rel = (t - (it.addr + 2)) // 2
                if not -128 <= rel <= 127:
                    it.size = 6
                    changed = True
            elif it.mnem in PSEUDO and it.size == 2:
                v = it.exprs[0].value(symtab) & 0xFFFF
                if v >= 0x100:
                    it.size = 4
                    changed = True
        if not changed:
            break
    else:
        raise AsmError('relaxation did not converge')

    # labels that were defined in dropped chunks are not in symtab: fine.
    img = Image()
    img.symtab = symtab
    img.end = end
    img.bounds = bounds
    img.items = items
    img.mem = bytearray(max(end, 0))
    img.code_words = set()     # addresses of instruction words
    img.insn_text = {}         # addr -> list of Studio-syntax lines
    errors = []
    for it in items:
        try:
            if it.kind == 'insn':
                words, texts = encode(it, symtab)
                for k, w in enumerate(words):
                    a = it.addr + 2 * k
                    img.mem[a] = (w >> 8) & 0xFF
                    img.mem[a + 1] = w & 0xFF
                    img.code_words.add(a)
                img.insn_text[it.addr] = texts
            elif it.kind == 'data':
                a = it.addr
                if it.data == 'word':
                    for e in it.exprs:
                        v = e.value(symtab) & 0xFFFF
                        img.mem[a] = v >> 8
                        img.mem[a + 1] = v & 0xFF
                        a += 2
                elif it.data == 'byte':
                    for e in it.exprs:
                        v = e.value(symtab)
                        if not -128 <= v <= 255:
                            raise AsmError(f".byte value {v} out of range")
                        img.mem[a] = v & 0xFF
                        a += 1
        except AsmError as e:
            errors.append(f'{it.src}: {e}  [{it.line}]')
    if errors:
        raise AsmError('\n'.join(errors))
    if end > mem_size:
        raise AsmError(f"program does not fit: image ends at 0x{end:04X}, "
                       f"memory is 0x{mem_size:04X} bytes")
    return img


def _chk(cond, msg):
    """Raise an assembler error unless the condition holds."""
    if not cond:
        raise AsmError(msg)


def encode(it, symtab):
    """Return (words, studio_text_lines) for one instruction item."""
    m = it.mnem
    op = OP.get(m)
    if m in F0:
        return [op << 11], [m]
    if m in F1:
        d, a, b = it.ops
        return [(op << 11) | (d << 8) | (a << 5) | (b << 2)], \
               [f'{m} R{d}, R{a}, R{b}']
    if m in F2:
        d, a = it.ops
        return [(op << 11) | (d << 8) | (a << 5)], [f'{m} R{d}, R{a}']
    if m in F3:
        d = it.ops[0]
        v = it.exprs[0].value(symtab)
        if m in ('LIL', 'LIH'):
            _chk(-128 <= v <= 255, f"{m} immediate {v} out of range 0..255")
        elif m == 'ADDI':
            _chk(-128 <= v <= 127, f"ADDI immediate {v} out of range -128..127")
        else:
            _chk(0 <= v <= 31, f"{m} shift amount {v} out of range 0..31")
        v &= 0xFF
        vs = str(sext(v, 8)) if m == 'ADDI' else str(v)
        return [(op << 11) | (d << 8) | v], [f'{m} R{d}, {vs}']
    if m in F4:
        r, base = it.ops
        off = it.exprs[0].value(symtab)
        _chk(-16 <= off <= 15, f"{m} offset {off} out of range -16..15")
        return [(op << 11) | (r << 8) | (base << 5) | (off & 0x1F)], \
               [f'{m} R{r}, {off}(R{base})']
    if m in F5:
        r = it.ops[0]
        t = it.exprs[0].value(symtab)
        if it.size == 2:
            rel = (t - (it.addr + 2)) // 2
            _chk((t - it.addr) % 2 == 0, f"{m} target 0x{t:X} is odd")
            return [(op << 11) | (r << 8) | (rel & 0xFF)], [(m, r, t)]
        # relaxed: BZ r,+1 ; JMP +1 ; JMP far
        w0 = (op << 11) | (r << 8) | 1
        w1 = (OP['JMP'] << 11) | 1
        rel = ((t - (it.addr + 6)) // 2) & 0x7FF
        w2 = (OP['JMP'] << 11) | rel
        return [w0, w1, w2], [f'{m} R{r}, 1', 'JMP 1', ('JMP', None, t)]
    if m in F6:
        t = it.exprs[0].value(symtab)
        rel = ((t - (it.addr + 2)) // 2) & 0x7FF   # PC wraps at 2 KB
        return [(op << 11) | rel], [(m, None, t)]
    if m in F7:
        r = it.ops[0]
        return [(op << 11) | (r << 8)], [f'{m} R{r}']
    if m in PSEUDO:
        d = it.ops[0]
        v = it.exprs[0].value(symtab) & 0xFFFF
        lo, hi = v & 0xFF, v >> 8
        what = it.exprs[0].text
        note = f'{"&" if m == "LA" else ""}{what}'
        if it.size == 2:
            _chk(hi == 0, 'internal: LA/LI relaxation')
            return [(OP['LIL'] << 11) | (d << 8) | lo], \
                   [f'LIL R{d}, {lo:<12}; {note} = 0x{v:03X}']
        return [(OP['LIL'] << 11) | (d << 8) | lo,
                (OP['LIH'] << 11) | (d << 8) | hi], \
               [f'LIL R{d}, {lo:<12}; {note} = 0x{v:03X}', f'LIH R{d}, {hi}']
    raise AsmError(f'cannot encode {m}')


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
def write_hex(img, path):
    """Write the .hex image: one 16-bit word per line."""
    end = (img.end + 1) & ~1
    with open(path, 'w') as f:
        for a in range(0, end, 2):
            f.write(f'{(img.mem[a] << 8) | (img.mem[a + 1] if a + 1 < len(img.mem) else 0):04x}\n')


def addr_labels(img):
    """The labels at each address, for the listing."""
    by = {}
    for name, a in img.symtab.items():
        by.setdefault(a, []).append(name)
    return by


def write_sym(img, path):
    """Write the symbol table: every name and where it ended up."""
    with open(path, 'w') as f:
        for name, a in sorted(img.symtab.items(), key=lambda kv: (kv[1], kv[0])):
            f.write(f'{a:04X} {name}\n')


def write_lst(img, path):
    """Write the listing: address, word, and the line it came from."""
    with open(path, 'w') as f:
        for it in img.items:
            for l in it.labels:
                f.write(f'{"":14}{l}:\n')
            if it.kind == 'insn':
                ws = [(img.mem[it.addr + 2 * k] << 8) | img.mem[it.addr + 2 * k + 1]
                      for k in range(it.size // 2)]
                f.write(f'{it.addr:04X}  {" ".join(f"{w:04X}" for w in ws):<14}  {it.line}\n')
            elif it.kind == 'data' and it.size:
                bs = img.mem[it.addr:it.addr + min(it.size, 8)]
                more = ' ...' if it.size > 8 else ''
                f.write(f'{it.addr:04X}  {bs.hex(" ")}{more:<4}  {it.line}\n')


def summary(img, stack_top=None):
    """The one line the driver prints: code, data, bss, free space."""
    b = img.bounds
    def size(s):
        """How many bytes one section occupies."""
        return (b[s][1] - b[s][0]) if s in b else 0
    code = size('init') + size('text')
    data = size('zdata') + size('data')
    bss = size('bss')
    lines = [f'code {code} B, data {data} B, bss {bss} B, '
             f'image ends at 0x{img.end:03X}']
    if stack_top is not None:
        free = stack_top - img.end
        lines[0] += f'; {free} B left for the stack (top 0x{stack_top:03X})'
    return lines[0]


def write_studio(img, path, entry_sym='main', title=None):
    """TARA Studio-loadable .tara: instructions only, data as NOPs, plus a
    generated __init that stores non-zero data words, then JMPs to main."""
    labels = addr_labels(img)
    end = (img.end + 1) & ~1
    out = []
    out.append('; ' + '-' * 72)
    out.append(f'; {title or os.path.basename(path)}')
    out.append('; Generated by tara16-cc, ported from chibicc. Loads directly in TARA Studio.')
    out.append('; Data/bss words appear as NOP (=0x0000) placeholders at their real')
    out.append('; addresses; __init (at the end) stores the non-zero ones, then jumps to main.')
    out.append('; ' + '-' * 72)

    # names for branch targets: prefer an existing label, else synthesize
    def target_name(t):
        """A label at this address that can be written in assembly."""
        for n in labels.get(t, []):
            if re.match(r'^[A-Za-z_.$][\w.$]*$', n):
                return n
        return None
    synth = {}
    def name_for(t):
        """A name for a branch target, inventing one if it has no label."""
        n = target_name(t)
        if n:
            return n
        if t not in synth:
            synth[t] = f'.A{t:03X}'
        return synth[t]

    # collect branch targets we must label
    body = []
    code = sorted(img.insn_text.items())
    a = 0
    code_map = dict(code)
    init_needed = []
    crt0_call = img.symtab.get('__crt0_call')
    while a < end:
        if a in code_map:
            texts = code_map[a]
            for k, t in enumerate(texts):
                if isinstance(t, tuple):
                    m, r, tgt = t
                    nm = name_for(tgt)
                    if a == crt0_call and m == 'CALL':
                        nm = '__init'          # run the data initialiser first
                    t = f'{m} R{r}, {nm}' if r is not None else f'{m} {nm}'
                body.append((a + 2 * k, t))
            a += 2 * len(texts)
        else:
            w = (img.mem[a] << 8) | (img.mem[a + 1] if a + 1 < len(img.mem) else 0)
            body.append((a, None))
            if w:
                init_needed.append((a, w))
            a += 2
    # emit
    emitted_labels = set()
    for addr, t in body:
        for n in labels.get(addr, []):
            if re.match(r'^[A-Za-z_.$][\w.$]*$', n) and n not in emitted_labels:
                out.append(f'{n}:')
                emitted_labels.add(n)
        if addr in synth and synth[addr] not in emitted_labels:
            out.append(f'{synth[addr]}:')
            emitted_labels.add(synth[addr])
        if t is None:
            w = (img.mem[addr] << 8) | (img.mem[addr + 1] if addr + 1 < len(img.mem) else 0)
            out.append(f'        NOP                 ; data 0x{addr:03X} (init 0x{w:04X})' if w
                       else f'        NOP                 ; data 0x{addr:03X}')
        else:
            out.append(f'        {t}')
    # __init
    out.append('')
    out.append('; ---- __init: store initialised data (R0 = value, R1 = base) ----')
    out.append('__init:')
    r1 = None
    r0 = None
    for addr, w in init_needed:
        if r1 is None or not (-16 <= addr - r1 <= 14):
            want = addr + 16
            if r1 is not None and -128 <= want - r1 <= 127:
                out.append(f'        ADDI R1, {want - r1}')
            else:
                out.append(f'        LIL R1, {want & 0xFF}')
                if want >> 8:
                    out.append(f'        LIH R1, {want >> 8}')
            r1 = want
        if r0 != w:
            if w < 0x100:
                out.append(f'        LIL R0, {w}')
            elif r0 is not None and (r0 & 0xFF) == (w & 0xFF):
                out.append(f'        LIH R0, {w >> 8}')
            else:
                out.append(f'        LIL R0, {w & 0xFF}')
                out.append(f'        LIH R0, {w >> 8}')
            r0 = w
        out.append(f'        STW R0, {addr - r1}(R1)      ; [0x{addr:03X}] = 0x{w:04X}')
    out.append(f'        JMP {entry_sym}')
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')
    # size of __init in words (for the report)
    return sum(1 for l in out[out.index('__init:') + 1:] if l.strip() and not l.strip().startswith(';'))


def disasm(w):
    """One 16-bit word, written out as an instruction again."""
    op = (w >> 11) & 0x1F
    m = OP_NAME.get(op, f'.word 0x{w:04X}')
    rd, ra, rb = (w >> 8) & 7, (w >> 5) & 7, (w >> 2) & 7
    if m in F0:
        return m
    if m in F1:
        return f'{m} R{rd}, R{ra}, R{rb}'
    if m in F2:
        return f'{m} R{rd}, R{ra}'
    if m in F3:
        v = w & 0xFF
        return f'{m} R{rd}, {sext(v, 8) if m == "ADDI" else v}'
    if m in F4:
        return f'{m} R{rd}, {sext(w & 0x1F, 5)}(R{ra})'
    if m in F5:
        return f'{m} R{rd}, {sext(w & 0xFF, 8)}'
    if m in F6:
        return f'{m} {sext(w & 0x7FF, 11)}'
    if m in F7:
        return f'{m} R{rd}'
    return m


def live_source(prog):
    """The source text of the chunks that survived garbage collection, each
    preceded by its section directive (for a readable prog.s)."""
    out = []
    for c in prog.chunks:
        if not c.live:
            continue
        body = [l for l in c.lines
                if l.split(';', 1)[0].strip().lower() not in
                ('.text', '.data', '.zdata', '.bss', '.init')]
        out.append(f'        .{c.section}')
        out += body
    return '\n'.join(out) + '\n'


def assemble_text(text, filename='<input>', defines=None, gc=True, roots=('_start',)):
    """Assemble and link one text; returns the finished image."""
    prog = Program().parse(text, filename)
    img = link(prog, roots=roots, gc=gc, defines=defines)
    img.prog = prog
    return img


def main():
    """The assembler as its own command, for assembly written by hand."""
    import argparse
    ap = argparse.ArgumentParser(description='TARA16 assembler/linker')
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--hex', help='write $readmemh image (.hex)')
    ap.add_argument('--lst')
    ap.add_argument('--sym')
    ap.add_argument('--studio', help='write TARA Studio-loadable .tara')
    ap.add_argument('--no-gc', action='store_true')
    ap.add_argument('-D', action='append', default=[], metavar='SYM=VAL')
    ap.add_argument('--entry', default='main')
    args = ap.parse_args()
    text = ''
    for p in args.inputs:
        text += open(p).read() + '\n'
    defines = {}
    for d in args.D:
        k, v = d.split('=', 1)
        defines[k] = int(v, 0)
    try:
        img = assemble_text(text, args.inputs[0], defines, gc=not args.no_gc)
    except AsmError as e:
        print(f'tara16-as: error: {e}', file=sys.stderr)
        sys.exit(1)
    if args.hex:
        write_hex(img, args.hex)
    if args.lst:
        write_lst(img, args.lst)
    if args.sym:
        write_sym(img, args.sym)
    if args.studio:
        write_studio(img, args.studio, args.entry)
    print(summary(img))


if __name__ == '__main__':
    main()
