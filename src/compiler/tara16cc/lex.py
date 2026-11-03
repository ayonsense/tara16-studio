# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Stage 1: turn C source text into a list of tokens.

A token is a word, a number, a string, or a punctuator, plus two flags the
preprocessor needs: `bol` (first token on its line) and `space` (there was
white space in front of it).

Integer constants follow the TARA16 rule: they must fit in 16 bits, and a
value above 0x7FFF (or a `u` suffix) has type `unsigned int`. An `l` suffix
is accepted and ignored, because there is no 32-bit type.
"""
from .diag import Pos, SourceFile, error_at

KEYWORDS = set('''
auto break case char const continue default do else enum extern for goto if
inline int long register restrict return short signed sizeof static struct
switch typedef union unsigned void volatile while _Alignas _Alignof _Atomic
_Bool _Noreturn _Thread_local asm __asm__ __attribute__ __restrict __inline
__volatile__ __signed__ typeof
'''.split())

# longest first: the scanner takes the first match
PUNCT = [
    '<<=', '>>=', '...',
    '->', '++', '--', '<<', '>>', '<=', '>=', '==', '!=', '&&', '||',
    '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '##',
    '+', '-', '*', '/', '%', '&', '|', '^', '!', '~', '=', '<', '>',
    '(', ')', '[', ']', '{', '}', '.', ',', ';', ':', '?', '#',
]

ESCAPES = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13, 'e': 27,
           '0': 0, '\\': 92, "'": 39, '"': 34, '?': 63}


class Token:
    """One word, number, string or punctuator, and where it came from."""
    __slots__ = ('kind', 'text', 'val', 'unsigned', 'data', 'pos', 'bol', 'space', 'hide')

    def __init__(self, kind, text, pos, bol=False, space=False):
        self.kind = kind          # 'ident' 'keyword' 'num' 'str' 'punct' 'eof'
        self.text = text
        self.val = 0              # 'num': the value
        self.unsigned = False     # 'num': has type unsigned int
        self.data = None          # 'str': the bytes, NUL included
        self.pos = pos
        self.bol = bol
        self.space = space
        self.hide = frozenset()   # macros this token must not be expanded by

    def is_(self, text):
        """Is this the punctuator, keyword or name spelled `text`?"""
        return self.text == text and self.kind in ('punct', 'ident', 'keyword')

    def copy(self):
        """A duplicate, for the preprocessor to give its own hide set."""
        t = Token(self.kind, self.text, self.pos, self.bol, self.space)
        t.val, t.unsigned, t.data, t.hide = self.val, self.unsigned, self.data, self.hide
        return t

    def __repr__(self):
        return f'<{self.kind} {self.text!r}>'


def _read_escape(s, i, pos):
    """s[i] is the character after a backslash. Returns (value, next index)."""
    c = s[i]
    if c == 'x':
        i += 1
        v = 0
        if i >= len(s) or s[i] not in '0123456789abcdefABCDEF':
            error_at(pos, 'invalid hex escape')
        while i < len(s) and s[i] in '0123456789abcdefABCDEF':
            v = v * 16 + int(s[i], 16)
            i += 1
        return v & 0xFF, i
    if c in '01234567':
        v = 0
        n = 0
        while i < len(s) and s[i] in '01234567' and n < 3:
            v = v * 8 + int(s[i], 8)
            i += 1
            n += 1
        return v & 0xFF, i
    return ESCAPES.get(c, ord(c)), i + 1


def tokenize(name, text):
    """Tokenize one file. Returns a list of Tokens ending with an 'eof'."""
    text = text.replace('\r\n', '\n')
    src = SourceFile(name, text)
    toks = []
    i, line, bol, space = 0, 1, True, False
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
            bol, space = True, False
            continue
        if c in ' \t\f\v':
            i += 1
            space = True
            continue
        if c == '\\' and i + 1 < n and text[i + 1] == '\n':
            i += 2                      # a line continuation joins two lines
            line += 1
            space = True
            continue
        if text.startswith('//', i):
            i = text.find('\n', i)
            if i < 0:
                break
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                error_at(Pos(src, line, i), 'unterminated block comment')
            line += text.count('\n', i, end)
            i = end + 2
            space = True
            continue
        pos = Pos(src, line, i)
        if c.isdigit() or (c == '.' and i + 1 < n and text[i + 1].isdigit()):
            j = i
            while j < n and (text[j].isalnum() or text[j] == '_' or text[j] == '.' or
                             (text[j] in '+-' and text[j - 1] in 'eEpP' and j > i and
                              text[i:i + 2].lower() != '0x')):
                j += 1
            # numbers are converted after preprocessing (convert_numbers),
            # so that an unused macro like 201112L is not an error
            toks.append(Token('num', text[i:j], pos, bol, space))
            i = j
        elif c.isalpha() or c == '_':
            j = i
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            toks.append(Token('ident', text[i:j], pos, bol, space))
            i = j
        elif c == '"':
            j = i + 1
            out = bytearray()
            while True:
                if j >= n or text[j] == '\n':
                    error_at(pos, 'unterminated string literal')
                if text[j] == '"':
                    break
                if text[j] == '\\':
                    v, j = _read_escape(text, j + 1, pos)
                    out.append(v)
                else:
                    out.extend(text[j].encode('utf-8'))
                    j += 1
            out.append(0)
            tok = Token('str', text[i:j + 1], pos, bol, space)
            tok.data = bytes(out)
            toks.append(tok)
            i = j + 1
        elif c == "'":
            j = i + 1
            if j >= n:
                error_at(pos, 'unterminated character constant')
            if text[j] == '\\':
                v, j = _read_escape(text, j + 1, pos)
            else:
                v = ord(text[j])
                j += 1
            if j >= n or text[j] != "'":
                error_at(pos, 'unterminated character constant')
            tok = Token('num', text[i:j + 1], pos, bol, space)
            # a character constant has type int; its value is that of a
            # (signed) char, so '\xff' is -1
            tok.val = v - 256 if 128 <= v < 256 else v
            tok.data = True                # already converted
            toks.append(tok)
            i = j + 1
        else:
            for p in PUNCT:
                if text.startswith(p, i):
                    toks.append(Token('punct', p, pos, bol, space))
                    i += len(p)
                    break
            else:
                error_at(pos, f'invalid character {c!r}')
        bol, space = False, False
    toks.append(Token('eof', '', Pos(src, line, min(i, n)), bol, space))
    return toks


def convert_number(tok):
    """Give a 'num' token its value and signedness (idempotent)."""
    if tok.data is not None:
        return tok
    tok.data = True
    s = tok.text
    low = s.lower()
    base, body = 10, s
    if low.startswith('0x'):
        base, body = 16, s[2:]
    elif low.startswith('0b') and len(s) > 2 and s[2] in '01':
        base, body = 2, s[2:]
    elif s.startswith('0') and len(s) > 1:
        base, body = 8, s          # the leading 0 is itself an octal digit,
                                   # which keeps `0u` and `0L` working
    if '.' in s or (base != 16 and 'e' in low) or (base == 16 and 'p' in low):
        error_at(tok.pos, 'TARA16: floating point is not supported')
    digits = '0123456789abcdef'[:base]
    j = 0
    while j < len(body) and body[j].lower() in digits:
        j += 1
    num, suffix = body[:j], body[j:].lower()
    if not num or set(suffix) - set('ul'):
        error_at(tok.pos, f'invalid number {s!r}')
    val = int(num, base)
    if val > 0xFFFF:
        error_at(tok.pos, 'TARA16: integer constant does not fit in 16 bits')
    tok.val = val
    tok.unsigned = 'u' in suffix or val > 0x7FFF
    return tok


def convert_numbers(toks):
    """Finish the token list once the preprocessor has had its turn.

    Numbers get their value, and the words C reserves stop being ordinary
    identifiers. This cannot happen while scanning: a macro may be named
    after a keyword, and a number may be written in a form only a
    conditional will ever look at.
    """
    for t in toks:
        if t.kind == 'num':
            convert_number(t)
        elif t.kind == 'ident' and t.text in KEYWORDS:
            t.kind = 'keyword'
    return toks


def tokenize_file(path):
    """Read a file from disk and tokenize it."""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return tokenize(path, f.read())
