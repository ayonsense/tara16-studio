# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.

"""
TARA Assembler
Converts TARA assembly text into 16-bit machine words.
Supports labels, comments (;), and all instruction formats.
"""

import re
from src.simulation.cpu import OP, FMT, sext

class AssemblerError(Exception):
    def __init__(self, msg, line=None):
        self.msg = msg
        self.line = line
        super().__init__(msg)

    def __str__(self):
        return f"Line {self.line}: {self.msg}" if self.line else self.msg


def parse_reg(tok):
    """Parse Rn or rn → integer 0-7."""
    tok = tok.strip().upper()
    if tok.startswith('R') and tok[1:].isdigit():
        n = int(tok[1:])
        if 0 <= n <= 7:
            return n
    raise AssemblerError(f"Invalid register '{tok}'")


def parse_int(tok, label_map=None, pc=None):
    """Parse a literal integer or label reference."""
    tok = tok.strip()
    if tok.startswith('0x') or tok.startswith('0X'):
        return int(tok, 16)
    if tok.startswith('0b') or tok.startswith('0B'):
        return int(tok, 2)
    if tok.lstrip('-').isdigit():
        return int(tok)
    if label_map is not None and tok in label_map:
        return label_map[tok]
    raise AssemblerError(f"Cannot parse value '{tok}'")


def parse_mem(tok):
    """Parse off(Rbase) → (offset_str, reg_str)."""
    m = re.match(r'^(-?\d+|0x[0-9a-fA-F]+)\(([Rr]\d)\)$', tok.strip())
    if not m:
        raise AssemblerError(f"Invalid memory operand '{tok}'")
    return m.group(1), m.group(2)


OPERAND_COUNTS = {
    'NOP': 0, 'HLT': 0, 'RET': 0,
    'ADD': 3, 'SUB': 3, 'MUL': 3, 'AND': 3, 'OR': 3, 'XOR': 3, 'SLT': 3,
    'MOV': 2, 'NOT': 2,
    'LIL': 2, 'LIH': 2, 'ADDI': 2, 'SHL': 2, 'SHR': 2,
    'LDW': 2, 'LDB': 2, 'STW': 2, 'STB': 2,
    'BZ': 2, 'BN': 2,
    'JMP': 1, 'CALL': 1,
    'PUSH': 1, 'POP': 1,
}


def _parse_operands(ops_str, mnem):
    operands = [o.strip() for o in ops_str.split(',') if o.strip()]
    expected = OPERAND_COUNTS[mnem]
    if len(operands) != expected:
        suffix = "" if expected == 1 else "s"
        raise AssemblerError(
            f"{mnem} expects {expected} operand{suffix}, got {len(operands)}"
        )
    return operands


def _validate_range(value, minimum, maximum, operand_name):
    if not minimum <= value <= maximum:
        raise AssemblerError(
            f"{operand_name} must be between {minimum} and {maximum}, got {value}"
        )
    return value


def _label_rel(target_s, iaddr, label_map):
    """Resolve a branch/jump target to a signed word-offset relative to iaddr+2."""
    if target_s in label_map:
        return (label_map[target_s] - (iaddr + 2)) // 2
    return parse_int(target_s, label_map)


def _encode_f0(op):
    return (op << 11)

def _encode_f1(op, rd, rA, rB):
    return (op << 11) | (rd << 8) | (rA << 5) | (rB << 2)

def _encode_f2(op, rd, rs):
    return (op << 11) | (rd << 8) | (rs << 5)

def _encode_f3(op, rd, imm8):
    imm8 = imm8 & 0xFF
    return (op << 11) | (rd << 8) | imm8

def _encode_f4(op, rdata, rbase, off5):
    off5 = off5 & 0x1F
    return (op << 11) | (rdata << 8) | (rbase << 5) | off5

def _encode_f5(op, rtest, rel8):
    rel8 = rel8 & 0xFF
    return (op << 11) | (rtest << 8) | rel8

def _encode_f6(op, rel11):
    rel11 = rel11 & 0x7FF
    return (op << 11) | rel11

def _encode_f7(op, rstk):
    return (op << 11) | (rstk << 8)


def assemble(source):
    """
    Assemble source text → (words, listing, errors)
      words  : list of (byte_addr, 16-bit int)
      listing: list of dict per assembled instruction
      errors : list of AssemblerError
    """
    lines = source.splitlines()
    errors = []
    label_map = {}        # label → byte address
    parsed = []           # list of (lineno, addr, mnemonic, operands_str, original)

    # ── Pass 1: strip comments, collect labels, count addresses ───────────────
    addr = 0
    for lineno, raw in enumerate(lines, 1):
        line = raw.split(';')[0].strip()
        if not line:
            continue

        # Extract label(s)
        while ':' in line:
            colon = line.index(':')
            label = line[:colon].strip()
            if label:
                label_map[label] = addr
            line = line[colon+1:].strip()

        if not line:
            continue

        parts = line.split(None, 1)
        mnem = parts[0].upper()
        ops  = parts[1].strip() if len(parts) > 1 else ''

        if mnem not in OP:
            errors.append(AssemblerError(f"Unknown mnemonic '{mnem}'", lineno))
            continue

        parsed.append((lineno, addr, mnem, ops, raw.rstrip()))
        addr += 2

    # ── Pass 2: encode instructions ───────────────────────────────────────────
    words   = []
    listing = []

    for (lineno, iaddr, mnem, ops_str, original) in parsed:
        opcode = OP[mnem]
        word = 0
        err = None

        try:
            operands = _parse_operands(ops_str, mnem)
            if mnem in ('NOP', 'HLT', 'RET'):
                word = _encode_f0(opcode)

            elif mnem in ('ADD', 'SUB', 'MUL', 'AND', 'OR', 'XOR', 'SLT'):
                # rd, rA, rB
                rd = parse_reg(operands[0])
                rA = parse_reg(operands[1])
                rB = parse_reg(operands[2])
                word = _encode_f1(opcode, rd, rA, rB)

            elif mnem in ('MOV', 'NOT'):
                # rd, rs
                rd = parse_reg(operands[0])
                rs = parse_reg(operands[1])
                word = _encode_f2(opcode, rd, rs)

            elif mnem in ('LIL', 'LIH', 'ADDI'):
                rd = parse_reg(operands[0])
                imm = parse_int(operands[1], label_map)

                if mnem == 'ADDI':
                    imm = _validate_range(imm, -128, 127, 'ADDI immediate')
                else:
                    imm = _validate_range(imm, -128, 255, f'{mnem} immediate')

                word = _encode_f3(opcode, rd, imm)

            elif mnem in ('SHL', 'SHR'):
                # rd, shamt
                rd = parse_reg(operands[0])
                shamt = parse_int(operands[1], label_map)
                shamt = _validate_range(shamt, 0, 31, 'shift amount')
                word = _encode_f3(opcode, rd, shamt)

            elif mnem in ('LDW', 'LDB'):
                # rd, off(rbase)
                rd = parse_reg(operands[0])
                off_s, base_s = parse_mem(operands[1])
                off = parse_int(off_s, label_map)
                off = _validate_range(off, -16, 15, 'memory offset')
                rbase = parse_reg(base_s)
                word = _encode_f4(opcode, rd, rbase, off)

            elif mnem in ('STW', 'STB'):
                # rs, off(rbase)
                rs = parse_reg(operands[0])
                off_s, base_s = parse_mem(operands[1])
                off = parse_int(off_s, label_map)
                off = _validate_range(off, -16, 15, 'memory offset')
                rbase = parse_reg(base_s)
                word = _encode_f4(opcode, rs, rbase, off)

            elif mnem in ('BZ', 'BN'):
                rtest = parse_reg(operands[0])
                rel = _label_rel(operands[1], iaddr, label_map)
                rel = _validate_range(rel, -128, 127, 'branch offset')
                word = _encode_f5(opcode, rtest, rel)

            elif mnem in ('JMP', 'CALL'):
                rel = _label_rel(operands[0], iaddr, label_map)
                rel = _validate_range(rel, -1024, 1023, 'jump offset')
                word = _encode_f6(opcode, rel)

            elif mnem in ('PUSH', 'POP'):
                rs = parse_reg(operands[0])
                word = _encode_f7(opcode, rs)

            else:
                raise AssemblerError(f"Unhandled mnemonic '{mnem}'")

        except (AssemblerError, ValueError, IndexError) as e:
            if not isinstance(e, AssemblerError):
                e = AssemblerError(str(e))
            e.line = lineno
            errors.append(e)
            err = e
            word = 0xDEAD

        words.append((iaddr, word))
        listing.append({
            'lineno': lineno,
            'addr': iaddr,
            'word': word,
            'mnem': mnem,
            'ops': ops_str,
            'original': original,
            'error': bool(err),
        })

    return words, listing, errors, label_map
