# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Stage 2: the preprocessor.

It reads the token list of one file and writes a new token list in which
every `#include` has been pasted in, every macro has been expanded, and
every `#if` has kept or dropped its branch. The parser never sees a `#`.

Macro expansion uses the standard *hide set* rule: a token produced while
expanding macro M carries M in its hide set and is never expanded by M
again, so `#define f(x) f(x)` terminates.
"""
import os

from .diag import error_at
from .lex import Token, convert_number, tokenize

BUILTIN = {
    '__tara16__': '1', '__TARA16__': '1',
    '__CHAR_UNSIGNED__': '1', '__BIG_ENDIAN__': '1',
    '__SIZEOF_INT__': '2', '__SIZEOF_SHORT__': '2', '__SIZEOF_POINTER__': '2',
    '__STDC__': '1', '__STDC_HOSTED__': '0', '__STDC_VERSION__': '201112L',
    '__tara16cc__': '1',
}


class Macro:
    """One #define: its name, its parameters if any, its replacement."""
    __slots__ = ('name', 'params', 'body', 'is_func')

    def __init__(self, name, body, params=None):
        self.name = name
        self.body = body            # list of Token
        self.params = params        # list of names, or None for object macros
        self.is_func = params is not None


class Preprocessor:
    """Runs the directives and expands the macros of one file."""
    def __init__(self, include_paths, defines=None):
        self.paths = list(include_paths)
        self.macros = {}
        for name, text in BUILTIN.items():
            self.define_text(f'{name} {text}')
        for d in (defines or []):
            self.define_text(d.replace('=', ' ', 1) if '=' in d else d + ' 1')
        self.included = []          # file names, for diagnostics

    # ---- defining macros from the command line -------------------------
    def define_text(self, text):
        """Define a macro from a -D option, with or without a value."""
        toks = tokenize('<command line>', text)[:-1]
        if not toks:
            return
        name = toks[0].text
        self.macros[name] = Macro(name, toks[1:])

    # ---- the main loop --------------------------------------------------
    # The input is one list of tokens. When a macro expands, its replacement
    # list is spliced into that list in place of the invocation, so the
    # result is rescanned automatically; hide sets stop the recursion.
    def run(self, toks):
        """Expand a token list (which must end with an 'eof' token)."""
        inp = list(toks)
        out = []
        cond = []
        i = 0
        while i < len(inp) - 1:
            tok = inp[i]
            if tok.bol and tok.is_('#'):
                i = self._directive(inp, i, cond)
                continue
            if cond and not cond[-1][0]:
                i += 1                           # inside a false #if
                continue
            j, repl = self._try_expand(inp, i)
            if repl is not None:
                inp[i:j] = repl
                continue
            out.append(tok)
            i += 1
        if cond:
            error_at(cond[-1][1], 'unterminated #if')
        out.append(inp[-1])
        return out

    # ---- directives -----------------------------------------------------
    def _line_end(self, toks, i):
        """Where the current directive line ends."""
        j = i
        while j < len(toks) - 1 and not toks[j].bol:
            j += 1
        return j

    def _directive(self, inp, at, cond):
        """inp[at] is '#'. Handles one directive line; returns the next index."""
        i = at + 1
        if i >= len(inp) - 1 or inp[i].bol:
            return i                             # a lone '#'
        d = inp[i].text
        pos = inp[i].pos
        end = self._line_end(inp, i + 1)
        args = inp[i + 1:end]
        live = not cond or cond[-1][0]

        if d == 'include':
            if not live:
                return end
            sub = self._include_tokens(args, pos)
            inp[at:end] = sub                    # paste the file in place
            return at
        if d == 'define':
            if live:
                self._define(args, pos)
        elif d == 'undef':
            if live and args:
                self.macros.pop(args[0].text, None)
        elif d == 'if':
            cond.append(((live and self._eval(args, pos) != 0), pos, live, False))
        elif d in ('ifdef', 'ifndef'):
            if not args:
                error_at(pos, f'#{d} needs a macro name')
            have = args[0].text in self.macros
            take = have if d == 'ifdef' else not have
            cond.append(((live and take), pos, live, False))
        elif d == 'elif':
            if not cond:
                error_at(pos, '#elif without #if')
            state, p, outer, taken = cond[-1]
            taken = taken or state
            cond[-1] = ((outer and not taken and self._eval(args, p) != 0), p, outer, taken)
        elif d == 'else':
            if not cond:
                error_at(pos, '#else without #if')
            state, p, outer, taken = cond[-1]
            cond[-1] = ((outer and not (taken or state)), p, outer, taken or state)
        elif d == 'endif':
            if not cond:
                error_at(pos, '#endif without #if')
            cond.pop()
        elif d == 'error':
            if live:
                error_at(pos, '#error ' + ' '.join(t.text for t in args))
        elif d in ('warning', 'pragma', 'line'):
            pass
        elif inp[i].kind == 'num':
            pass                                 # a line marker
        elif live:
            error_at(pos, f'unknown directive #{d}')
        return end

    def _include_tokens(self, args, pos):
        """Find an included file and tokenize it."""
        if args and args[0].kind == 'str':
            name, local = args[0].text[1:-1], True
        elif args and args[0].is_('<'):
            parts, j = [], 1
            while j < len(args) and not args[j].is_('>'):
                parts.append(args[j].text)
                j += 1
            name, local = ''.join(parts), False
        else:
            args = self._expand_all(args)
            return self._include_tokens(args, pos) if args else error_at(
                pos, '#include needs a file name')
        dirs = [os.path.dirname(pos.file.name) or '.'] if local else []
        dirs += self.paths
        for d in dirs:
            path = os.path.join(d, name)
            if os.path.exists(path):
                self.included.append(path)
                with open(path, encoding='utf-8', errors='replace') as f:
                    sub = tokenize(path, f.read())
                return sub[:-1]                  # drop the file's eof
        error_at(pos, f'{name}: cannot open file: No such file or directory')

    def _define(self, args, pos):
        """Record a #define, object-like or function-like."""
        if not args:
            error_at(pos, '#define needs a name')
        name = args[0].text
        rest = args[1:]
        if rest and rest[0].is_('(') and not rest[0].space:
            params, j = [], 1
            while j < len(rest) and not rest[j].is_(')'):
                if rest[j].is_(','):
                    j += 1
                    continue
                if rest[j].is_('...'):
                    error_at(rest[j].pos, 'TARA16: variadic macros are not supported')
                params.append(rest[j].text)
                j += 1
            if j >= len(rest):
                error_at(pos, 'unterminated macro parameter list')
            self.macros[name] = Macro(name, rest[j + 1:], params)
        else:
            self.macros[name] = Macro(name, rest)

    # ---- macro expansion -------------------------------------------------
    def _try_expand(self, inp, i):
        """If inp[i] starts a macro invocation, return (end index, replacement).
        Otherwise return (i, None)."""
        tok = inp[i]
        if tok.kind != 'ident' or tok.text not in self.macros or tok.text in tok.hide:
            return i, None
        m = self.macros[tok.text]
        if not m.is_func:
            return i + 1, self._subst(m, {}, tok)
        j = i + 1
        if j >= len(inp) or not inp[j].is_('('):
            return i, None                       # a name, not a call
        argv, j = self._read_args(inp, j, m, tok)
        return j, self._subst(m, argv, tok)

    def _expand_all(self, toks):
        """Fully expand a detached token list (macro arguments, #if lines)."""
        if not toks:
            return []
        inp = list(toks) + [Token('eof', '', toks[0].pos)]
        out = []
        i = 0
        while i < len(inp) - 1:
            j, repl = self._try_expand(inp, i)
            if repl is not None:
                inp[i:j] = repl
                continue
            out.append(inp[i])
            i += 1
        return out

    def _read_args(self, toks, j, m, tok):
        """toks[j] is '('. Returns ({param: tokens}, index after ')')."""
        j += 1
        args, cur, depth = [], [], 0
        while True:
            if j >= len(toks) - 1:
                error_at(tok.pos, f'unterminated argument list for {m.name}')
            t = toks[j]
            if depth == 0 and t.is_(')'):
                break
            if depth == 0 and t.is_(','):
                args.append(cur)
                cur = []
                j += 1
                continue
            if t.is_('(') or t.is_('['):
                depth += 1
            elif t.is_(')') or t.is_(']'):
                depth -= 1
            cur.append(t)
            j += 1
        args.append(cur)
        if len(args) == 1 and not args[0] and not m.params:
            args = []
        if len(args) != len(m.params):
            error_at(tok.pos, f'{m.name} takes {len(m.params)} argument(s), '
                              f'{len(args)} given')
        return dict(zip(m.params, args)), j + 1

    def _subst(self, m, argv, at):
        """Build the replacement list: arguments substituted, # and ## applied."""
        out = []
        body = m.body
        i = 0
        while i < len(body):
            t = body[i]
            # '#param' -> a string literal holding the argument's text
            if t.is_('#') and i + 1 < len(body) and body[i + 1].text in argv:
                text = ' '.join(x.text for x in argv[body[i + 1].text])
                s = Token('str', '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"',
                          t.pos, t.bol, t.space)
                s.data = text.encode() + b'\0'
                out.append(s)
                i += 2
                continue
            # 'a ## b' -> one token
            if i + 1 < len(body) and body[i + 1].is_('##') and i + 2 < len(body):
                left = [x.copy() for x in argv.get(t.text, [t])]
                right = [x.copy() for x in argv.get(body[i + 2].text, [body[i + 2]])]
                if left and right:
                    out.extend(left[:-1])
                    joined = tokenize('<paste>', left[-1].text + right[0].text)[:-1]
                    for x in joined:
                        x.pos = t.pos
                        out.append(x)
                    out.extend(right[1:])
                else:
                    out.extend(left + right)
                i += 3
                continue
            if t.kind == 'ident' and t.text in argv:
                arg = argv[t.text]
                expanded = self._expand_all(arg)
                for k, x in enumerate(expanded):
                    y = x.copy()
                    if k == 0:
                        y.space = t.space
                    out.append(y)
                i += 1
                continue
            out.append(t.copy())
            i += 1
        hide = at.hide | {m.name}
        for t in out:
            t.hide = t.hide | hide
            t.pos = at.pos
            t.bol = False
        if out:
            out[0].bol = at.bol
            out[0].space = at.space
        return out

    # ---- #if expressions -------------------------------------------------
    def _eval(self, args, pos):
        """Evaluate a #if expression: expand it, then read it as a number."""
        toks = []
        i = 0
        args = list(args)
        while i < len(args):
            t = args[i]
            if t.kind == 'ident' and t.text == 'defined':
                j = i + 1
                paren = j < len(args) and args[j].is_('(')
                if paren:
                    j += 1
                if j >= len(args):
                    error_at(pos, 'defined needs a macro name')
                name = args[j].text
                j += 1
                if paren:
                    if j >= len(args) or not args[j].is_(')'):
                        error_at(pos, 'defined( needs )')
                    j += 1
                num = Token('num', '1' if name in self.macros else '0', t.pos)
                num.val = 1 if name in self.macros else 0
                toks.append(num)
                i = j
                continue
            toks.append(t)
            i += 1
        toks = self._expand_all(toks) if toks else []
        for t in toks:
            if t.kind == 'ident':
                t.kind, t.text, t.val, t.data = 'num', '0', 0, True  # undefined -> 0
            elif t.kind == 'num':
                convert_number(t)
        return _ConstExpr(toks, pos).parse()


class _ConstExpr:
    """A tiny constant-expression evaluator for #if (64-bit, like C)."""

    def __init__(self, toks, pos):
        self.t = toks
        self.i = 0
        self.pos = pos

    def peek(self):
        """The text of the token under consideration."""
        return self.t[self.i].text if self.i < len(self.t) else ''

    def take(self, text):
        """Step over the token if it is this one."""
        if self.peek() == text:
            self.i += 1
            return True
        return False

    def parse(self):
        """Evaluate the whole expression, and check it is used up."""
        v = self.cond()
        if self.i != len(self.t):
            error_at(self.pos, 'trailing tokens in #if')
        return v

    def cond(self):
        """The ?: level."""
        c = self.logor()
        if self.take('?'):
            a = self.cond()
            if not self.take(':'):
                error_at(self.pos, '? without :')
            b = self.cond()
            return a if c else b
        return c

    def logor(self):
        """The || level."""
        v = self.logand()
        while self.take('||'):
            v = 1 if (self.logand() or v) else 0
        return v

    def logand(self):
        """The && level."""
        v = self.bitor()
        while self.take('&&'):
            v = 1 if (self.bitor() and v) else 0
        return v

    def bitor(self):
        """The | level."""
        v = self.bitxor()
        while self.take('|'):
            v |= self.bitxor()
        return v

    def bitxor(self):
        """The ^ level."""
        v = self.bitand()
        while self.take('^'):
            v ^= self.bitand()
        return v

    def bitand(self):
        """The & level."""
        v = self.equality()
        while self.take('&'):
            v &= self.equality()
        return v

    def equality(self):
        """The == and != level."""
        v = self.relational()
        while True:
            if self.take('=='):
                v = 1 if v == self.relational() else 0
            elif self.take('!='):
                v = 1 if v != self.relational() else 0
            else:
                return v

    def relational(self):
        """The <, <=, > and >= level."""
        v = self.shift()
        while True:
            if self.take('<'):
                v = 1 if v < self.shift() else 0
            elif self.take('>'):
                v = 1 if v > self.shift() else 0
            elif self.take('<='):
                v = 1 if v <= self.shift() else 0
            elif self.take('>='):
                v = 1 if v >= self.shift() else 0
            else:
                return v

    def shift(self):
        """The << and >> level."""
        v = self.add()
        while True:
            if self.take('<<'):
                v <<= self.add()
            elif self.take('>>'):
                v >>= self.add()
            else:
                return v

    def add(self):
        """The + and - level."""
        v = self.mul()
        while True:
            if self.take('+'):
                v += self.mul()
            elif self.take('-'):
                v -= self.mul()
            else:
                return v

    def mul(self):
        """The *, / and % level."""
        v = self.unary()
        while True:
            if self.take('*'):
                v *= self.unary()
            elif self.take('/'):
                d = self.unary()
                v = 0 if d == 0 else int(v / d)
            elif self.take('%'):
                d = self.unary()
                v = 0 if d == 0 else v - int(v / d) * d
            else:
                return v

    def unary(self):
        """A sign, a ~, a !, a number, or a parenthesised expression."""
        if self.take('-'):
            return -self.unary()
        if self.take('+'):
            return self.unary()
        if self.take('!'):
            return 0 if self.unary() else 1
        if self.take('~'):
            return ~self.unary()
        if self.take('('):
            v = self.cond()
            if not self.take(')'):
                error_at(self.pos, '( without )')
            return v
        if self.i < len(self.t) and self.t[self.i].kind == 'num':
            v = self.t[self.i].val
            self.i += 1
            return v
        error_at(self.pos, 'invalid #if expression')


def preprocess(path, include_paths, defines=None):
    """Tokenize a file and run the preprocessor over it."""
    pp = Preprocessor(include_paths, defines)
    with open(path, encoding='utf-8', errors='replace') as f:
        toks = tokenize(path, f.read())
    return pp.run(toks)
