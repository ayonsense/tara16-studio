# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""Stage 3: the parser and type checker.

A recursive-descent parser, one method per grammar rule, in the usual C
precedence order:

    assign -> conditional -> logor -> logand -> bitor -> bitxor -> bitand
           -> equality -> relational -> shift -> add -> mul -> cast
           -> unary -> postfix -> primary

It does the semantic work at the same time: every node gets a type, the
usual arithmetic conversions become explicit CAST nodes, `a[i]` becomes
`*(a + i)`, `x += e` becomes `x = x + e`, and an initializer becomes either
a byte image (globals) or a list of assignments (locals).

The result is a list of Obj: the functions and the global variables.
"""
from .ctype import (Member, Type, array_of, enum_type, find_member,
                    func_type, get_common_type, is_aggregate, is_array_like,
                    is_integer, layout_struct, norm, pointer_to,
                    struct_type, ty_bool, ty_char, ty_int, ty_schar, ty_short,
                    ty_size_t, ty_uchar, ty_uint, ty_ushort, ty_void, type_name)
from .diag import error_at
from .node import Node, Obj

# storage-class flags returned by declspec()
S_TYPEDEF, S_STATIC, S_EXTERN, S_INLINE = 1, 2, 4, 8


class VarScope:
    """What one name means in one scope: a variable, a typedef, an enum."""
    __slots__ = ('var', 'type_def', 'enum_ty', 'enum_val')

    def __init__(self):
        self.var = None
        self.type_def = None
        self.enum_ty = None
        self.enum_val = None


class Parser:
    """Turns the token list into a tree, checking every rule of C."""
    def __init__(self, toks, opt=None):
        self.toks = toks
        self.i = 0
        self.opt = opt
        self.globals = []
        self.scopes = [{}]          # name -> VarScope
        self.tags = [{}]            # struct/union/enum tags
        self.locals = None
        self.cur_fn = None
        self.gotos = []
        self.labels = []
        self.brk_label = None
        self.cont_label = None
        self.cur_switch = None
        self.uid = 0
        self.strings = 0
        self.loop_depth = 0         # loops around the current statement

    # ------------------------------------------------------------ tokens
    @property
    def tok(self):
        """The token under consideration."""
        return self.toks[self.i]

    def at(self, text, k=0):
        """Is the token k ahead spelled `text`?"""
        t = self.toks[min(self.i + k, len(self.toks) - 1)]
        return t.kind in ('ident', 'keyword', 'punct') and t.text == text

    def consume(self, text):
        """Step over the token if it is `text`, and say whether we did."""
        if self.at(text):
            self.i += 1
            return True
        return False

    def expect(self, text):
        """Step over `text`, or report that it was missing."""
        if not self.consume(text):
            error_at(self.tok.pos, f"expected '{text}'")

    def next(self):
        """Take the token under consideration and step past it."""
        t = self.toks[self.i]
        self.i += 1
        return t

    def unique(self, prefix='.L'):
        """A name nothing else will use, for a label or a hidden variable."""
        self.uid += 1
        return f'{prefix}{self.uid}'

    # ------------------------------------------------------------ scopes
    def enter_scope(self):
        """Enter a block: its names and tags are forgotten on the way out."""
        self.scopes.append({})
        self.tags.append({})

    def leave_scope(self):
        """Leave the innermost block, forgetting its names and tags."""
        self.scopes.pop()
        self.tags.pop()

    def push_scope(self, name):
        """Introduce a name in the innermost scope."""
        sc = VarScope()
        self.scopes[-1][name] = sc
        return sc

    def find_var(self, name):
        """What this name means, from the innermost scope outwards."""
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return None

    def find_tag(self, name):
        """What this struct, union or enum tag means."""
        for sc in reversed(self.tags):
            if name in sc:
                return sc[name]
        return None

    def is_typename(self, tok=None):
        """Is this token the name of a type? The lexer hack, done here."""
        tok = tok or self.tok
        if tok.kind not in ('ident', 'keyword'):
            return False
        if tok.text in TYPE_KEYWORDS:
            return True
        sc = self.find_var(tok.text)
        return bool(sc and sc.type_def)

    # ------------------------------------------------------------ objects
    def new_lvar(self, name, ty, tok=None):
        """Make a local variable and put it in the innermost scope."""
        var = Obj(name, ty, is_local=True)
        var.tok = tok
        var.loop_depth = self.loop_depth
        if name:
            self.push_scope(name).var = var
        if self.locals is not None:
            self.locals.append(var)
        return var

    def new_gvar(self, name, ty, tok=None):
        """Make a global variable and put it in the file scope."""
        var = Obj(name, ty)
        var.tok = tok
        var.is_definition = True
        self.push_scope(name).var = var
        self.globals.append(var)
        return var

    def new_string(self, data, tok):
        """Make the hidden array a string literal lives in."""
        self.strings += 1
        var = Obj(f'.L..str{self.strings}', array_of(ty_char, len(data)))
        var.tok = tok
        var.init_data = bytes(data)
        var.is_definition = True
        var.is_static = True
        self.globals.append(var)
        return var

    # ============================================================== program
    def parse(self):
        """Parse a whole file: the globals and functions it defines."""
        while self.tok.kind != 'eof':
            base, storage = self.declspec()
            if storage & S_TYPEDEF:
                self.parse_typedef(base)
                continue
            if self.consume(';'):
                continue
            ty, name_tok = self.declarator(base)
            if ty.kind == 'func':
                if self.at('{'):
                    self.function(ty, name_tok, storage)
                    continue
                self.declare_function(ty, name_tok, storage)
                while self.consume(','):
                    ty2, nt2 = self.declarator(base)
                    self.declare_function(ty2, nt2, storage)
                self.expect(';')
                continue
            self.global_variable(base, ty, name_tok, storage)
        for v in self.globals:
            if v.is_root:
                self.mark_live(v)
        # reverse order here too, for the same reason
        self.globals.reverse()
        return self.globals

    def mark_live(self, var):
        """Mark var, and every function it names, as worth generating."""
        if not var.is_function or var.is_live:
            return
        var.is_live = True
        for name in var.refs:
            sc = self.scopes[0].get(name)
            if sc and sc.var and sc.var.is_function:
                self.mark_live(sc.var)

    def declare_function(self, ty, name_tok, storage):
        """Record a function declared but not defined here."""
        if name_tok is None:
            error_at(self.tok.pos, 'function name omitted')
        fn = Obj(name_tok.text, ty)
        fn.tok = name_tok
        fn.is_function = True
        fn.is_definition = False
        fn.is_static = bool(storage & S_STATIC)
        old = self.find_var(fn.name)
        if not (old and old.var and old.var.is_function):
            self.push_scope(fn.name).var = fn
            self.globals.append(fn)

    def global_variable(self, base, ty, name_tok, storage):
        """Parse a global declaration, with any initializer."""
        first = True
        while True:
            if not first:
                ty, name_tok = self.declarator(base)
            first = False
            if name_tok is None:
                error_at(self.tok.pos, 'variable name omitted')
            name = name_tok.text
            old = self.find_var(name)
            if old and old.var and not old.var.is_local and old.var.init_data is None:
                var = old.var            # a second declaration of the same object
                var.ty = ty
            else:
                var = self.new_gvar(name, ty, name_tok)
            var.is_static = bool(storage & S_STATIC)
            var.is_definition = not (storage & S_EXTERN)
            if self.consume('='):
                self.gvar_initializer(var)
            if self.consume(';'):
                return
            self.expect(',')

    def parse_typedef(self, base):
        """Record one or more typedef names."""
        while True:
            if self.consume(';'):
                return
            ty, name_tok = self.declarator(base)
            if name_tok is None:
                error_at(self.tok.pos, 'typedef name omitted')
            self.push_scope(name_tok.text).type_def = ty
            if self.consume(';'):
                return
            self.expect(',')

    # ============================================================== types
    def declspec(self, allow_storage=True):
        """Parse declaration specifiers: `static unsigned int`, `struct S`, ..."""
        VOID, BOOL, CHAR, SHORT, INT, OTHER, SIGNED, UNSIGNED = (
            1 << 0, 1 << 2, 1 << 4, 1 << 6, 1 << 8, 1 << 10, 1 << 12, 1 << 14)
        ty = ty_int
        counter = 0
        storage = 0
        atomic = False
        while self.is_typename() or self.tok.text in STORAGE_KEYWORDS:
            tok = self.tok
            text = tok.text
            if text in ('typedef', 'static', 'extern', 'inline', 'register',
                        'auto', '_Noreturn'):
                if not allow_storage:
                    error_at(tok.pos, 'storage class not allowed here')
                self.i += 1
                storage |= {'typedef': S_TYPEDEF, 'static': S_STATIC,
                            'extern': S_EXTERN, 'inline': S_INLINE}.get(text, 0)
                continue
            if text in ('const', 'volatile', 'restrict', '__restrict',
                        '__volatile__', '_Noreturn'):
                self.i += 1
                continue
            if text == '_Thread_local':
                error_at(tok.pos, 'TARA16: thread-local storage is not supported')
            if text == '_Atomic':
                self.i += 1
                atomic = True
                if self.consume('('):
                    ty = self.typename()
                    self.expect(')')
                    counter += OTHER
                continue
            if text == '_Alignas':
                self.i += 1
                self.expect('(')
                if self.is_typename():
                    self.typename()
                else:
                    self.const_expr()
                self.expect(')')
                continue
            if text in ('long',):
                error_at(tok.pos, "TARA16: 'long' is not supported (int is 16 bits "
                                  'on TARA16; there is no 32-bit arithmetic yet)')
            if text in ('float', 'double'):
                error_at(tok.pos, 'TARA16: floating point is not supported')
            if text in ('struct', 'union'):
                self.i += 1
                ty = self.struct_union_decl('struct' if text == 'struct' else 'union')
                counter += OTHER
                continue
            if text == 'enum':
                self.i += 1
                ty = self.enum_specifier()
                counter += OTHER
                continue
            if text == 'typeof':
                self.i += 1
                ty = self.typeof_specifier()
                counter += OTHER
                continue
            sc = self.find_var(text)
            if counter == 0 and sc and sc.type_def:
                self.i += 1
                ty = sc.type_def
                counter += OTHER
                continue
            if text in ('void', '_Bool', 'char', 'short', 'int', 'signed',
                        '__signed__', 'unsigned'):
                self.i += 1
                counter += {'void': VOID, '_Bool': BOOL, 'char': CHAR,
                            'short': SHORT, 'int': INT, 'signed': SIGNED,
                            '__signed__': SIGNED, 'unsigned': UNSIGNED}[text]
            else:
                break
            table = {
                VOID: ty_void, BOOL: ty_bool,
                CHAR: ty_char, SIGNED + CHAR: ty_schar, UNSIGNED + CHAR: ty_uchar,
                SHORT: ty_short, SHORT + INT: ty_short, SIGNED + SHORT: ty_short,
                SIGNED + SHORT + INT: ty_short,
                UNSIGNED + SHORT: ty_ushort, UNSIGNED + SHORT + INT: ty_ushort,
                INT: ty_int, SIGNED: ty_int, SIGNED + INT: ty_int,
                UNSIGNED: ty_uint, UNSIGNED + INT: ty_uint,
            }
            if counter not in table:
                error_at(tok.pos, 'invalid combination of type specifiers')
            ty = table[counter]
        if atomic:
            ty = ty.copy()
            ty.is_atomic = True
        return ty, storage

    def typeof_specifier(self):
        """GNU typeof(x): the type of an expression, without evaluating it."""
        self.expect('(')
        if self.is_typename():
            ty = self.typename()
        else:
            ty = self.assign().ty
        self.expect(')')
        return ty

    def struct_union_decl(self, kind):
        """Parse `struct S { ... }`, or a use of a tag declared before."""
        tag = None
        if self.tok.kind == 'ident' and not self.at('{'):
            tag = self.next()
        if tag and not self.at('{'):
            found = self.find_tag(tag.text)
            if found:
                return found
            ty = struct_type(kind)          # an incomplete type, for now
            ty.tag = tag.text
            self.tags[-1][tag.text] = ty
            return ty
        self.expect('{')
        ty = self.tags[-1].get(tag.text) if tag else None
        if ty is None or ty.kind != kind:
            ty = struct_type(kind)
        ty.members = []
        ty.size, ty.align = 0, 1
        if tag:
            ty.tag = tag.text
            self.tags[-1][tag.text] = ty
        idx = 0
        while not self.consume('}'):
            base, _ = self.declspec(allow_storage=False)
            if self.consume(';'):
                if is_aggregate(base):      # an anonymous struct member
                    mem = Member(None, base)
                    mem.idx = idx
                    idx += 1
                    ty.members.append(mem)
                continue
            while True:
                mty, name_tok = self.declarator(base)
                mem = Member(name_tok.text if name_tok else None, mty,
                             name_tok.pos if name_tok else None)
                if self.consume(':'):
                    mem.is_bitfield = True
                    mem.bit_width = self.const_expr()
                    if mem.bit_width < 0 or mem.bit_width > mty.size * 8:
                        error_at(self.tok.pos, 'invalid bit-field width')
                mem.idx = idx
                idx += 1
                ty.members.append(mem)
                if not self.consume(','):
                    break
            self.expect(';')
        layout_struct(ty)
        return ty

    def enum_specifier(self):
        """Parse an enum, giving every constant its value."""
        tag = None
        if self.tok.kind == 'ident' and not self.at('{'):
            tag = self.next()
        if tag and not self.at('{'):
            found = self.find_tag(tag.text)
            if not found:
                error_at(tag.pos, f'unknown enum type {tag.text}')
            return found
        self.expect('{')
        ty = enum_type()
        val = 0
        while not self.consume('}'):
            name = self.next()
            if name.kind != 'ident':
                error_at(name.pos, 'expected an enumeration constant')
            if self.consume('='):
                val = self.const_expr()
            sc = self.push_scope(name.text)
            sc.enum_ty = ty
            sc.enum_val = val
            val += 1
            if not self.consume(','):
                self.expect('}')
                break
        if tag:
            ty.tag = tag.text
            self.tags[-1][tag.text] = ty
        return ty

    def declarator(self, ty):
        """Parse `*x`, `x[3]`, `(*f)(int)` ... Returns (type, name token)."""
        while self.consume('*'):
            ty = pointer_to(ty)
            while self.tok.text in ('const', 'volatile', 'restrict', '__restrict'):
                self.i += 1
        if self.consume('('):
            # `(*f)(int)`: skip the inner declarator, parse the suffix to get
            # the real type, then parse the inner declarator again with it
            start = self.i
            self.declarator(Type('int', 2, 2))
            self.expect(')')
            ty = self.type_suffix(ty)
            after = self.i
            self.i = start
            ty2, name = self.declarator(ty)
            self.i = after
            return ty2, name
        name = None
        if self.tok.kind == 'ident' and not self.is_typename():
            name = self.next()
        ty = self.type_suffix(ty)
        return ty, name

    def abstract_declarator(self, ty):
        """A declarator with no name, as in a cast or a parameter."""
        while self.consume('*'):
            ty = pointer_to(ty)
            while self.tok.text in ('const', 'volatile', 'restrict', '__restrict'):
                self.i += 1
        if self.at('(') and (self.at('*', 1) or self.at('(', 1) or
                             self.at('[', 1) or self.at(')', 1)):
            start = self.i + 1
            self.i += 1
            self.abstract_declarator(Type('int', 2, 2))
            self.expect(')')
            ty = self.type_suffix(ty)
            after = self.i
            self.i = start
            ty2, _ = self.abstract_declarator(ty)
            self.i = after
            return ty2, None
        ty = self.type_suffix(ty)
        return ty, None

    def skip_parens(self):
        """self.i is just after '('; move past the matching ')'."""
        self.skip_to_matching()

    def skip_to_matching(self):
        """Step over a balanced run of brackets."""
        depth = 0
        while True:
            t = self.tok
            if t.kind == 'eof':
                error_at(t.pos, 'unbalanced parentheses')
            if t.text == '(':
                depth += 1
            elif t.text == ')':
                if depth == 0:
                    self.i += 1
                    return
                depth -= 1
            self.i += 1

    def type_suffix(self, ty):
        """What follows a declarator: (params) or [length]."""
        if self.consume('('):
            return self.func_params(ty)
        if self.consume('['):
            return self.array_dimensions(ty)
        return ty

    def array_dimensions(self, ty):
        """The [length] part, which may be empty or a constant."""
        while self.tok.text in ('static', 'restrict', '__restrict'):
            self.i += 1
        if self.consume(']'):
            ty = self.type_suffix(ty)
            return array_of(ty, 0)          # [] : length comes from the initializer
        tok = self.tok
        n = self.const_expr()
        self.expect(']')
        ty = self.type_suffix(ty)
        if n < 0:
            error_at(tok.pos, 'array of negative size')
        return array_of(ty, n)

    def func_params(self, return_ty):
        """The (parameter list) part, and the function type it makes."""
        params = []
        variadic = False
        if self.at('void') and self.at(')', 1):
            self.i += 2
            return func_type(return_ty, params)
        while not self.consume(')'):
            if params:
                self.expect(',')
            if self.consume('...'):
                self.expect(')')
                variadic = True
                break
            base, _ = self.declspec(allow_storage=False)
            ty, name_tok = self.declarator(base)
            if ty.kind == 'array':          # a parameter of array type is a pointer
                ty = pointer_to(ty.base)
            elif ty.kind == 'func':
                ty = pointer_to(ty)
            p = Obj(name_tok.text if name_tok else '', ty)
            p.tok = name_tok
            params.append(p)
        fty = func_type(return_ty, params, variadic)
        if variadic:
            error_at(self.tok.pos, 'TARA16: variadic functions are not supported')
        return fty

    def typename(self):
        """A type written on its own, as in a cast or in sizeof."""
        base, _ = self.declspec(allow_storage=False)
        ty, _ = self.abstract_declarator(base)
        return ty

    # ============================================================ functions
    def function(self, ty, name_tok, storage):
        name = name_tok.text
        old = self.find_var(name)
        if old and old.var and old.var.is_function and old.var.is_definition:
            error_at(name_tok.pos, f'redefinition of {name}')
        fn = old.var if (old and old.var and old.var.is_function) else None
        if fn is None:
            fn = Obj(name, ty)
            fn.is_function = True
            self.push_scope(name).var = fn
            self.globals.append(fn)
        fn.ty = ty
        fn.tok = name_tok
        fn.is_definition = True
        fn.is_static = bool(storage & S_STATIC)
        fn.is_inline = bool(storage & S_INLINE)
        fn.is_root = not (fn.is_static and fn.is_inline)
        fn.locals = []
        self.locals = fn.locals
        self.cur_fn = fn
        self.gotos, self.labels = [], []
        self.enter_scope()
        # a function returning a struct takes a hidden pointer as argument 0
        params = []
        if is_aggregate(ty.return_ty):
            hidden = self.new_lvar('', pointer_to(ty.return_ty), name_tok)
            params.append(hidden)
        for p in ty.params:
            if not p.name:
                error_at(name_tok.pos, 'parameter name omitted')
            params.append(self.new_lvar(p.name, p.ty, p.tok))
        fn.params = params
        for k, p in enumerate(params):
            p.argidx = k
        nparams = len(fn.locals)
        self.expect('{')
        body = Node('BLOCK', name_tok)
        body.body = self.compound_stmt()
        fn.body = body
        self.resolve_gotos()
        self.leave_scope()
        # Put the body's variables in reverse declaration order, ahead of the
        # parameters. Register allocation and frame layout may visit the
        # variables in any order, but they break ties by position, so fixing
        # the order fixes the code they produce -- and this is the order the C
        # compiler in ../compiler_chibicc uses, which keeps the two compilers'
        # output identical and so lets tests/difftest.py compare them.
        fn.locals = fn.locals[nparams:][::-1] + fn.locals[:nparams]
        self.locals = None
        self.cur_fn = None

    def resolve_gotos(self):
        """Match every goto with its label, now that all are known."""
        for g in self.gotos:
            for lab in self.labels:
                if g.label == lab.label:
                    g.unique_label = lab.unique_label
                    break
            else:
                error_at(g.tok.pos, f'use of undeclared label {g.label}')

    # ============================================================ statements
    def compound_stmt(self):
        """Statements and declarations up to the closing '}'."""
        stmts = []
        self.enter_scope()
        while not self.consume('}'):
            if self.tok.kind == 'eof':
                error_at(self.tok.pos, "expected '}'")
            if (self.is_typename() or self.tok.text in STORAGE_KEYWORDS) and \
                    not self.at(':', 1):
                base, storage = self.declspec()
                if storage & S_TYPEDEF:
                    self.parse_typedef(base)
                    continue
                if storage & S_STATIC:
                    self.static_local(base)
                    continue
                if storage & S_EXTERN:
                    while not self.consume(';'):
                        ty, name_tok = self.declarator(base)
                        if name_tok:
                            v = Obj(name_tok.text, ty)
                            v.is_definition = False
                            v.is_function = ty.kind == 'func'
                            self.push_scope(name_tok.text).var = v
                            self.globals.append(v)
                        self.consume(',')
                    continue
                node = self.declaration(base)
                if node:
                    stmts.append(node)
                continue
            stmts.append(self.stmt())
        self.leave_scope()
        return stmts

    def static_local(self, base):
        """A `static` local: a global that only one function can name."""
        while True:
            ty, name_tok = self.declarator(base)
            if ty.kind == 'func':
                self.declare_function(ty, name_tok, S_STATIC)
                if self.consume(';'):
                    return
                self.expect(',')
                continue
            var = Obj(f'{self.cur_fn.name}.{name_tok.text}.{self.unique("")}', ty)
            var.tok = name_tok
            var.is_definition = True
            var.is_static = True
            self.globals.append(var)
            self.push_scope(name_tok.text).var = var
            if self.consume('='):
                self.gvar_initializer(var)
            if self.consume(';'):
                return
            self.expect(',')

    def declaration(self, base):
        """Local declarations; returns a statement that runs the initializers."""
        exprs = []
        while not self.consume(';'):
            ty, name_tok = self.declarator(base)
            if ty.kind == 'void':
                error_at(name_tok.pos if name_tok else self.tok.pos,
                         'variable declared void')
            if name_tok is None:
                error_at(self.tok.pos, 'variable name omitted')
            if ty.kind == 'func':
                self.declare_function(ty, name_tok, 0)
                if not self.consume(','):
                    self.expect(';')
                    break
                continue
            var = self.new_lvar(name_tok.text, ty, name_tok)
            if self.consume('='):
                exprs.append(self.lvar_initializer(var, name_tok))
            if var.ty.size < 0:
                error_at(name_tok.pos, 'variable has incomplete type')
            if not self.consume(','):
                self.expect(';')
                break
        if not exprs:
            return None
        node = Node('BLOCK', self.tok)
        node.body = [self.expr_stmt_node(e) for e in exprs]
        return node

    def expr_stmt_node(self, expr):
        """Wrap an expression as a statement."""
        n = Node('EXPR_STMT', expr.tok)
        n.lhs = expr
        return n

    def stmt(self):
        """Parse one statement, whatever kind it is."""
        tok = self.tok
        if self.consume('return'):
            node = Node('RETURN', tok)
            if self.consume(';'):
                node.lhs = None
                return node
            exp = self.expr()
            self.expect(';')
            rty = self.cur_fn.ty.return_ty
            if not is_aggregate(rty):
                exp = self.new_cast(exp, rty)
            node.lhs = exp
            return node
        if self.consume('if'):
            node = Node('IF', tok)
            self.expect('(')
            node.cond = self.expr()
            self.expect(')')
            node.then = self.stmt()
            if self.consume('else'):
                node.els = self.stmt()
            return node
        if self.consume('switch'):
            node = Node('SWITCH', tok)
            self.expect('(')
            node.cond = self.expr()
            self.expect(')')
            node.case_next = []
            old_switch, old_brk = self.cur_switch, self.brk_label
            self.cur_switch = node
            node.brk_label = self.brk_label = self.unique('.Lswbrk')
            node.then = self.stmt()
            # The tests are emitted in this order, and any order is correct.
            # Last label first is the order the C compiler in
            # ../compiler_chibicc uses, so the two agree instruction for
            # instruction.
            node.case_next.reverse()
            self.cur_switch, self.brk_label = old_switch, old_brk
            return node
        if self.consume('case'):
            if not self.cur_switch:
                error_at(tok.pos, 'stray case')
            node = Node('CASE', tok)
            node.begin = node.end = self.const_expr()
            if self.consume('...'):
                node.end = self.const_expr()
                if node.end < node.begin:
                    error_at(tok.pos, 'empty case range')
            self.expect(':')
            node.unique_label = self.unique('.Lcase')
            node.lhs = self.stmt()
            self.cur_switch.case_next.append(node)
            return node
        if self.consume('default'):
            if not self.cur_switch:
                error_at(tok.pos, 'stray default')
            node = Node('CASE', tok)
            self.expect(':')
            node.unique_label = self.unique('.Ldefault')
            node.lhs = self.stmt()
            self.cur_switch.default_case = node
            return node
        if self.consume('for'):
            node = Node('FOR', tok)
            self.expect('(')
            self.enter_scope()
            old_brk, old_cont = self.brk_label, self.cont_label
            node.brk_label = self.brk_label = self.unique('.Lbrk')
            node.cont_label = self.cont_label = self.unique('.Lcont')
            if self.is_typename() or self.tok.text in STORAGE_KEYWORDS:
                base, _ = self.declspec()
                node.init = self.declaration(base)
            elif not self.consume(';'):
                node.init = self.expr_stmt()
            self.loop_depth += 1
            if not self.at(';'):
                node.cond = self.expr()
            self.expect(';')
            if not self.at(')'):
                node.inc = self.expr()
            self.expect(')')
            node.then = self.stmt()
            self.loop_depth -= 1
            self.brk_label, self.cont_label = old_brk, old_cont
            self.leave_scope()
            return node
        if self.consume('while'):
            node = Node('FOR', tok)
            self.expect('(')
            self.loop_depth += 1
            node.cond = self.expr()
            self.expect(')')
            old_brk, old_cont = self.brk_label, self.cont_label
            node.brk_label = self.brk_label = self.unique('.Lbrk')
            node.cont_label = self.cont_label = self.unique('.Lcont')
            node.then = self.stmt()
            self.loop_depth -= 1
            self.brk_label, self.cont_label = old_brk, old_cont
            return node
        if self.consume('do'):
            node = Node('DO', tok)
            old_brk, old_cont = self.brk_label, self.cont_label
            node.brk_label = self.brk_label = self.unique('.Lbrk')
            node.cont_label = self.cont_label = self.unique('.Lcont')
            self.loop_depth += 1
            node.then = self.stmt()
            self.brk_label, self.cont_label = old_brk, old_cont
            self.expect('while')
            self.expect('(')
            node.cond = self.expr()
            self.loop_depth -= 1
            self.expect(')')
            self.expect(';')
            return node
        if self.consume('goto'):
            if self.consume('*'):
                error_at(tok.pos, 'TARA16: labels-as-values are not supported')
            node = Node('GOTO', tok)
            node.label = self.next().text
            self.expect(';')
            self.gotos.append(node)
            return node
        if self.consume('break'):
            if not self.brk_label:
                error_at(tok.pos, 'stray break')
            node = Node('GOTO', tok)
            node.unique_label = self.brk_label
            self.expect(';')
            return node
        if self.consume('continue'):
            if not self.cont_label:
                error_at(tok.pos, 'stray continue')
            node = Node('GOTO', tok)
            node.unique_label = self.cont_label
            self.expect(';')
            return node
        if self.tok.kind == 'ident' and self.at(':', 1):
            node = Node('LABEL', tok)
            node.label = self.next().text
            self.i += 1                       # ':'
            node.unique_label = self.unique(f'.L.{node.label}.')
            node.lhs = self.stmt()
            self.labels.append(node)
            return node
        if self.tok.text in ('asm', '__asm__'):
            self.i += 1
            while self.tok.text in ('volatile', '__volatile__', 'inline'):
                self.i += 1
            self.expect('(')
            if self.tok.kind != 'str':
                error_at(self.tok.pos, 'expected an assembly string')
            node = Node('ASM', tok)
            node.asm_str = self.next().data[:-1].decode()
            self.expect(')')
            self.expect(';')
            return node
        if self.consume('{'):
            node = Node('BLOCK', tok)
            node.body = self.compound_stmt()
            return node
        return self.expr_stmt()

    def expr_stmt(self):
        """A statement that is just an expression, or an empty one."""
        tok = self.tok
        if self.consume(';'):
            node = Node('BLOCK', tok)
            node.body = []
            return node
        node = Node('EXPR_STMT', tok)
        node.lhs = self.expr()
        self.expect(';')
        return node

    # ============================================================ expressions
    def expr(self):
        node = self.assign()
        if self.at(','):
            tok = self.next()
            rhs = self.expr()
            n = Node('COMMA', tok, rhs.ty)
            n.lhs, n.rhs = node, rhs
            return n
        return node

    def const_expr(self):
        """An expression that must have a value now, at compile time."""
        return self.eval(self.conditional())

    def assign(self):
        """The assignment level, which groups to the right."""
        node = self.conditional()
        tok = self.tok
        if self.consume('='):
            return self.new_assign(node, self.assign(), tok)
        for op, kind in (('+=', 'ADD'), ('-=', 'SUB'), ('*=', 'MUL'),
                         ('/=', 'DIV'), ('%=', 'MOD'), ('&=', 'BITAND'),
                         ('|=', 'BITOR'), ('^=', 'BITXOR'), ('<<=', 'SHL'),
                         ('>>=', 'SHR')):
            if self.consume(op):
                return self.to_assign(kind, node, self.assign(), tok)
        return node

    def conditional(self):
        """The ?: level."""
        cond = self.logor()
        tok = self.tok
        if not self.consume('?'):
            return cond
        if self.consume(':'):                  # GNU `a ?: b`
            then = cond
            els = self.conditional()
            node = Node('COND', tok)
            node.cond = cond
            node.then, node.els = then, els
            node.ty = get_common_type(then.ty, els.ty)
            return node
        then = self.expr()
        self.expect(':')
        els = self.conditional()
        node = Node('COND', tok)
        node.cond = cond
        if then.ty.kind == 'void' or els.ty.kind == 'void':
            node.ty = ty_void
        elif is_aggregate(then.ty):
            node.ty = then.ty
        elif then.ty.base or els.ty.base:
            node.ty = then.ty if then.ty.base else els.ty
            then = self.new_cast(then, node.ty)
            els = self.new_cast(els, node.ty)
        else:
            node.ty = get_common_type(then.ty, els.ty)
            then = self.new_cast(then, node.ty)
            els = self.new_cast(els, node.ty)
        node.then, node.els = then, els
        return node

    def _binary_chain(self, sub, ops):
        """One precedence level made of several operators."""
        node = sub()
        while True:
            for text, kind in ops:
                if self.at(text):
                    tok = self.next()
                    node = self.new_binary_typed(kind, node, sub(), tok)
                    break
            else:
                return node

    def logor(self):
        """The || level."""
        node = self.logand()
        while self.at('||'):
            tok = self.next()
            n = Node('LOGOR', tok, ty_int)
            n.lhs, n.rhs = node, self.logand()
            node = n
        return node

    def logand(self):
        """The && level."""
        node = self.bitor()
        while self.at('&&'):
            tok = self.next()
            n = Node('LOGAND', tok, ty_int)
            n.lhs, n.rhs = node, self.bitor()
            node = n
        return node

    def bitor(self):
        """The | level."""
        node = self.bitxor()
        while self.at('|') and not self.at('||'):
            tok = self.next()
            node = self.new_binary_typed('BITOR', node, self.bitxor(), tok)
        return node

    def bitxor(self):
        """The ^ level."""
        node = self.bitand()
        while self.at('^'):
            tok = self.next()
            node = self.new_binary_typed('BITXOR', node, self.bitand(), tok)
        return node

    def bitand(self):
        """The & level."""
        node = self.equality()
        while self.at('&') and not self.at('&&'):
            tok = self.next()
            node = self.new_binary_typed('BITAND', node, self.equality(), tok)
        return node

    def equality(self):
        """The == and != level."""
        return self._binary_chain(self.relational, (('==', 'EQ'), ('!=', 'NE')))

    def relational(self):
        """The four comparisons, two of which swap their operands."""
        node = self.shift()
        while True:
            if self.at('<'):
                tok = self.next()
                node = self.new_binary_typed('LT', node, self.shift(), tok)
            elif self.at('<='):
                tok = self.next()
                node = self.new_binary_typed('LE', node, self.shift(), tok)
            elif self.at('>'):
                tok = self.next()
                node = self.new_binary_typed('LT', self.shift(), node, tok)
            elif self.at('>='):
                tok = self.next()
                node = self.new_binary_typed('LE', self.shift(), node, tok)
            else:
                return node

    def shift(self):
        """The << and >> level."""
        node = self.add()
        while True:
            if self.at('<<'):
                tok = self.next()
                node = self.new_shift('SHL', node, self.add(), tok)
            elif self.at('>>'):
                tok = self.next()
                node = self.new_shift('SHR', node, self.add(), tok)
            else:
                return node

    def add(self):
        """The + and - level, where pointers are scaled."""
        node = self.mul()
        while True:
            if self.at('+'):
                tok = self.next()
                node = self.new_add(node, self.mul(), tok)
            elif self.at('-'):
                tok = self.next()
                node = self.new_sub(node, self.mul(), tok)
            else:
                return node

    def mul(self):
        """The *, / and % level."""
        node = self.cast()
        while True:
            for text, kind in (('*', 'MUL'), ('/', 'DIV'), ('%', 'MOD')):
                if self.at(text):
                    tok = self.next()
                    node = self.new_binary_typed(kind, node, self.cast(), tok)
                    break
            else:
                return node

    def cast(self):
        """A cast, or the unary level below it."""
        if self.at('(') and self.is_typename(self.toks[self.i + 1]):
            tok = self.tok
            self.i += 1
            ty = self.typename()
            self.expect(')')
            if self.at('{'):                    # compound literal
                return self.compound_literal(ty, tok)
            node = self.new_cast(self.cast(), ty)
            node.tok = tok
            return node
        return self.unary()

    def compound_literal(self, ty, tok):
        """A (struct S){...}: an unnamed variable with an initializer."""
        if self.locals is None:
            var = self.new_gvar(self.unique('.Lcompound'), ty, tok)
            var.is_static = True
            self.gvar_initializer(var)
            return self.new_var_node(var, tok)
        var = self.new_lvar('', ty, tok)
        init = self.lvar_initializer(var, tok)
        node = Node('COMMA', tok)
        node.lhs = init
        node.rhs = self.new_var_node(var, tok)
        node.ty = var.ty
        return node

    def unary(self):
        """A sign, a ~, a !, a *, a &, a ++ or a --."""
        tok = self.tok
        if self.consume('+'):
            return self.cast()
        if self.consume('-'):
            operand = self.cast()
            node = Node('NEG', tok)
            node.lhs = self.promote(operand)
            node.ty = node.lhs.ty
            return node
        if self.consume('&'):
            operand = self.cast()
            if operand.kind == 'MEMBER' and operand.member.is_bitfield:
                error_at(tok.pos, 'cannot take the address of a bit-field')
            if operand.kind == 'VAR' and operand.var.is_function:
                operand.var.ind_stub = True
            node = Node('ADDR', tok)
            node.lhs = operand
            node.ty = pointer_to(operand.ty)
            return node
        if self.consume('*'):
            operand = self.cast()
            return self.new_deref(operand, tok)
        if self.consume('!'):
            node = Node('NOT', tok, ty_int)
            node.lhs = self.cast()
            return node
        if self.consume('~'):
            operand = self.promote(self.cast())
            node = Node('BITNOT', tok, operand.ty)
            node.lhs = operand
            return node
        if self.consume('++'):
            operand = self.unary()
            return self.to_assign('ADD', operand, self.new_num(1, tok), tok)
        if self.consume('--'):
            operand = self.unary()
            return self.to_assign('SUB', operand, self.new_num(1, tok), tok)
        if self.tok.text in ('sizeof', '_Alignof', '_Alignas'):
            return self.sizeof_expr()
        if self.tok.text == '__attribute__':
            self.i += 1
            self.expect('(')
            self.i -= 1
            self.i += 1
            self.skip_to_matching()
            return self.unary()
        return self.postfix()

    def sizeof_expr(self):
        """sizeof and _Alignof, of a type or of an expression."""
        tok = self.next()
        if self.at('(') and self.is_typename(self.toks[self.i + 1]):
            self.i += 1
            ty = self.typename()
            self.expect(')')
            val = ty.size if tok.text == 'sizeof' else ty.align
            return self.new_num(val, tok, ty_size_t)
        node = self.unary()
        val = node.ty.size if tok.text == 'sizeof' else node.ty.align
        return self.new_num(val, tok, ty_size_t)

    def postfix(self):
        """What follows a primary: [], (), ., ->, ++ and --."""
        node = self.primary()
        while True:
            tok = self.tok
            if self.consume('('):
                node = self.funcall(node, tok)
                continue
            if self.consume('['):
                idx = self.expr()
                self.expect(']')
                node = self.new_deref(self.new_add(node, idx, tok), tok)
                continue
            if self.consume('.'):
                node = self.struct_ref(node, self.next(), tok)
                continue
            if self.consume('->'):
                node = self.new_deref(node, tok)
                node = self.struct_ref(node, self.next(), tok)
                continue
            if self.consume('++'):
                node = self.new_inc_dec(node, tok, 'ADD')
                continue
            if self.consume('--'):
                node = self.new_inc_dec(node, tok, 'SUB')
                continue
            return node

    def primary(self):
        """A constant, a name, a string, or a parenthesised expression."""
        tok = self.tok
        if self.at('(') and self.at('{', 1):
            # GNU statement expression: ({ ...; value; })
            self.i += 2
            node = Node('STMT_EXPR', tok)
            node.body = self.compound_stmt()
            self.expect(')')
            node.ty = ty_void
            if node.body and node.body[-1].kind == 'EXPR_STMT':
                node.ty = node.body[-1].lhs.ty
            return node
        if self.consume('('):
            node = self.expr()
            self.expect(')')
            return node
        if tok.kind == 'num':
            self.i += 1
            return self.new_num(tok.val, tok, ty_uint if tok.unsigned else ty_int)
        if tok.kind == 'str':
            self.i += 1
            data = tok.data
            while self.tok.kind == 'str':         # adjacent literals join
                data = data[:-1] + self.next().data
            var = self.new_string(data, tok)
            return self.new_var_node(var, tok)
        if tok.text == 'sizeof' and tok.kind == 'keyword':
            return self.sizeof_expr()
        if tok.kind == 'ident':
            self.i += 1
            sc = self.find_var(tok.text)
            if sc is None or (sc.var is None and sc.enum_ty is None):
                if self.at('('):
                    error_at(tok.pos, f'implicit declaration of a function {tok.text}')
                error_at(tok.pos, f'undefined variable {tok.text}')
            if sc.enum_ty:
                return self.new_num(sc.enum_val, tok, ty_int)
            var = sc.var
            if var.is_function:
                # `static inline` helpers live in headers, and a program uses
                # only a few of them. Note who mentions whom now; parse() then
                # keeps the ones a real function can reach.
                if self.cur_fn:
                    self.cur_fn.refs.append(var.name)
                else:
                    var.is_root = True
                if not self.at('('):
                    var.ind_stub = True          # its address is being taken
            return self.new_var_node(var, tok)
        error_at(tok.pos, 'expected an expression')

    def funcall(self, fn, tok):
        """A call: check the arguments and convert them to the parameters."""
        if fn.kind == 'VAR' and fn.var.name == 'alloca':
            error_at(tok.pos, 'TARA16: alloca is not supported')
        if fn.ty.kind == 'func':
            fty = fn.ty
        elif fn.ty.base and fn.ty.base.kind == 'func':
            fty = fn.ty.base
        else:
            error_at(tok.pos, 'not a function')
        node = Node('FUNCALL', tok, fty.return_ty)
        node.lhs = fn
        node.func_ty = fty
        args = []
        k = 0
        while not self.consume(')'):
            if args:
                self.expect(',')
            arg = self.assign()
            if k < len(fty.params):
                pty = fty.params[k].ty
                if is_aggregate(pty):
                    if not is_aggregate(arg.ty):
                        error_at(arg.tok.pos, 'passing a scalar for a struct parameter')
                else:
                    arg = self.new_cast(arg, pty)
            elif arg.ty.kind in ('char', 'bool', 'short'):
                arg = self.new_cast(arg, ty_int)
            args.append(arg)
            k += 1
        if fty.params and len(args) != len(fty.params):
            error_at(tok.pos, f'expected {len(fty.params)} arguments, got {len(args)}')
        node.args = args
        if is_aggregate(fty.return_ty):
            if self.locals is None:
                error_at(tok.pos, 'struct-returning call outside a function')
            node.ret_buffer = self.new_lvar('', fty.return_ty, tok)
        return node

    def struct_ref(self, node, name_tok, tok):
        """Reach a member of a struct or union."""
        if not is_aggregate(node.ty):
            error_at(tok.pos, 'not a struct or union')
        if node.ty.members is None:
            error_at(tok.pos, 'incomplete struct type')
        path = find_member(node.ty, name_tok.text)
        if not path:
            error_at(name_tok.pos, f'no member named {name_tok.text}')
        for mem in path:
            n = Node('MEMBER', tok, mem.ty)
            n.lhs = node
            n.member = mem
            node = n
        return node

    # ---------------------------------------------------- node constructors
    def new_num(self, val, tok, ty=ty_int):
        """A constant node, with the value narrowed to its type."""
        n = Node('NUM', tok, ty)
        n.val = norm(ty, val)
        return n

    def new_var_node(self, var, tok):
        """A tree node that names a variable."""
        n = Node('VAR', tok, var.ty)
        n.var = var
        return n

    def new_cast(self, expr, ty):
        """A conversion, dropped when the type is already right."""
        if expr.ty is ty:
            return expr
        n = Node('CAST', expr.tok, ty)
        n.lhs = expr
        return n

    def new_deref(self, operand, tok):
        """A *p node, with the type it points at."""
        if operand.ty.base is None:
            error_at(tok.pos, 'invalid pointer dereference')
        if operand.ty.base.kind == 'void':
            error_at(tok.pos, 'dereferencing a void pointer')
        n = Node('DEREF', tok, operand.ty.base)
        n.lhs = operand
        return n

    def to_bool(self, node):
        """Convert to _Bool, which is 0 or 1 and nothing else."""
        if node.ty.kind == 'bool':
            return node
        return self.new_cast(node, ty_bool)

    def promote(self, node):
        """Integer promotion: types narrower than int become int."""
        ty = node.ty
        if is_integer(ty) and (ty.size < 2 or ty.kind in ('short', 'enum', 'bool')):
            return self.new_cast(node, ty_uint if (ty.size == 2 and ty.is_unsigned)
                                 else ty_int)
        return node

    def new_binary_typed(self, kind, lhs, rhs, tok):
        """A binary node, with both sides converted to a common type."""
        if kind in ('EQ', 'NE', 'LT', 'LE'):
            if lhs.ty.base or rhs.ty.base:
                ty = lhs.ty if lhs.ty.base else rhs.ty
                lhs = self.new_cast(lhs, ty)
                rhs = self.new_cast(rhs, ty)
            else:
                self.check_arith(lhs, rhs, tok)
                ty = get_common_type(lhs.ty, rhs.ty)
                lhs = self.new_cast(lhs, ty)
                rhs = self.new_cast(rhs, ty)
            n = Node(kind, tok, ty_int)
            n.lhs, n.rhs = lhs, rhs
            return n
        self.check_arith(lhs, rhs, tok)
        ty = get_common_type(lhs.ty, rhs.ty)
        n = Node(kind, tok, ty)
        n.lhs = self.new_cast(lhs, ty)
        n.rhs = self.new_cast(rhs, ty)
        return n

    def check_arith(self, lhs, rhs, tok):
        """Reject operands arithmetic cannot be applied to."""
        for side in (lhs, rhs):
            if is_aggregate(side.ty) or side.ty.kind == 'void':
                error_at(tok.pos, f'invalid operand of type {type_name(side.ty)}')

    def new_shift(self, kind, lhs, rhs, tok):
        """A shift, where only the left side is promoted."""
        lhs = self.promote(lhs)
        rhs = self.promote(rhs)
        n = Node(kind, tok, lhs.ty)
        n.lhs, n.rhs = lhs, rhs
        return n

    def new_add(self, lhs, rhs, tok):
        """An addition, scaling the integer when one side is a pointer."""
        if lhs.ty.base and rhs.ty.base:
            error_at(tok.pos, 'invalid operands: pointer + pointer')
        if not lhs.ty.base and rhs.ty.base:
            lhs, rhs = rhs, lhs
        if lhs.ty.base:                          # pointer + integer
            size = lhs.ty.base.size
            scaled = self.new_binary_typed('MUL', self.new_cast(rhs, ty_int),
                                           self.new_num(size, tok), tok)
            n = Node('ADD', tok, pointer_to(lhs.ty.base))
            n.lhs = self.new_cast(lhs, n.ty)
            n.rhs = self.new_cast(scaled, n.ty)
            return n
        return self.new_binary_typed('ADD', lhs, rhs, tok)

    def new_sub(self, lhs, rhs, tok):
        """A subtraction, including pointer minus pointer."""
        if lhs.ty.base and is_integer(rhs.ty):   # pointer - integer
            size = lhs.ty.base.size
            scaled = self.new_binary_typed('MUL', self.new_cast(rhs, ty_int),
                                           self.new_num(size, tok), tok)
            n = Node('SUB', tok, pointer_to(lhs.ty.base))
            n.lhs = self.new_cast(lhs, n.ty)
            n.rhs = self.new_cast(scaled, n.ty)
            return n
        if lhs.ty.base and rhs.ty.base:          # pointer - pointer
            size = lhs.ty.base.size
            diff = Node('SUB', tok, ty_int)
            diff.lhs = self.new_cast(lhs, ty_int)
            diff.rhs = self.new_cast(rhs, ty_int)
            return self.new_binary_typed('DIV', diff, self.new_num(size, tok), tok)
        return self.new_binary_typed('SUB', lhs, rhs, tok)

    def new_assign(self, lhs, rhs, tok):
        """An assignment, converting the value to the target type."""
        self.check_lvalue(lhs, tok)
        if lhs.ty.is_atomic:
            error_at(tok.pos, 'TARA16: atomics are not supported')
        if is_aggregate(lhs.ty):
            if lhs.ty.kind != rhs.ty.kind or lhs.ty.size != rhs.ty.size:
                error_at(tok.pos, 'incompatible struct assignment')
        else:
            rhs = self.new_cast(rhs, lhs.ty)
        n = Node('ASSIGN', tok, lhs.ty)
        n.lhs, n.rhs = lhs, rhs
        return n

    def check_lvalue(self, node, tok):
        """Reject an assignment to something that is not a place."""
        if node.kind == 'VAR' and node.var.is_function:
            error_at(tok.pos, 'cannot assign to a function')
        if node.kind not in ('VAR', 'DEREF', 'MEMBER'):
            error_at(tok.pos, 'not an lvalue')
        if is_array_like(node.ty):
            error_at(tok.pos, 'cannot assign to an array')

    def simple_lvalue(self, node):
        """Can this lvalue be evaluated twice, cheaply and safely?"""
        if node.kind == 'VAR':
            return True
        if node.kind == 'DEREF':
            return node.lhs.kind == 'VAR'
        if node.kind == 'MEMBER':
            return self.simple_lvalue(node.lhs)
        return False

    def clone_lvalue(self, node):
        """A second copy of an lvalue, for rewriting `x += e`."""
        if node.kind == 'VAR':
            return self.new_var_node(node.var, node.tok)
        if node.kind == 'DEREF':
            n = Node('DEREF', node.tok, node.ty)
            n.lhs = self.clone_lvalue(node.lhs)
            return n
        if node.kind == 'MEMBER':
            n = Node('MEMBER', node.tok, node.ty)
            n.lhs = self.clone_lvalue(node.lhs)
            n.member = node.member
            return n
        raise AssertionError('clone_lvalue')

    def to_assign(self, kind, lhs, rhs, tok):
        """`A op= B`. For a plain lvalue this is `A = A op B` (TARA16: no
        pointer temporary, so A can stay in a register). Otherwise the
        address of A is computed once into a temporary pointer."""
        self.check_lvalue(lhs, tok)
        if lhs.ty.is_atomic:
            error_at(tok.pos, 'TARA16: atomics are not supported')
        use_simple = self.simple_lvalue(lhs) and (self.opt is None or
                                                  self.opt.compound_fix)
        if use_simple:
            again = self.clone_lvalue(lhs)
            if kind in ('ADD', 'SUB') and lhs.ty.base:
                value = (self.new_add(again, rhs, tok) if kind == 'ADD'
                         else self.new_sub(again, rhs, tok))
            elif kind in ('SHL', 'SHR'):
                value = self.new_shift(kind, again, rhs, tok)
            else:
                value = self.new_binary_typed(kind, again, rhs, tok)
            return self.new_assign(lhs, value, tok)
        # general case: tmp = &A;  *tmp = *tmp op B
        var = self.new_lvar('', pointer_to(lhs.ty), tok)
        addr = Node('ADDR', tok, pointer_to(lhs.ty))
        addr.lhs = lhs
        expr1 = self.new_assign(self.new_var_node(var, tok), addr, tok)
        deref1 = self.new_deref(self.new_var_node(var, tok), tok)
        deref2 = self.new_deref(self.new_var_node(var, tok), tok)
        if kind in ('ADD', 'SUB') and lhs.ty.base:
            value = (self.new_add(deref2, rhs, tok) if kind == 'ADD'
                     else self.new_sub(deref2, rhs, tok))
        elif kind in ('SHL', 'SHR'):
            value = self.new_shift(kind, deref2, rhs, tok)
        else:
            value = self.new_binary_typed(kind, deref2, rhs, tok)
        expr2 = self.new_assign(deref1, value, tok)
        n = Node('COMMA', tok, lhs.ty)
        n.lhs, n.rhs = expr1, expr2
        return n

    def new_inc_dec(self, node, tok, kind):
        """`x++` is `(x += 1) - 1`: the value is the one from before."""
        one = self.new_num(1, tok)
        assign = self.to_assign(kind, node, one, tok)
        back = (self.new_sub(assign, self.new_num(1, tok), tok) if kind == 'ADD'
                else self.new_add(assign, self.new_num(1, tok), tok))
        return self.new_cast(back, node.ty)

    # ------------------------------------------------------- initializers
    def initializer_list(self, ty, var=None):
        """Parse an initializer and return a nested structure:
        a scalar Node, or a list of (index_or_member, sub) pairs."""
        if ty.kind == 'array' and self.tok.kind == 'str' and \
                ty.base.size == 1:
            tok = self.next()
            data = list(tok.data)
            if ty.array_len == 0:
                ty.array_len = len(data)
                ty.size = len(data) * ty.base.size
            items = []
            for k, b in enumerate(data[:ty.array_len]):
                items.append((k, self.new_num(b, tok, ty.base)))
            return items
        if not self.at('{'):
            return self.assign()
        self.expect('{')
        items = []
        if ty.kind == 'array':
            idx = 0
            while not self.consume('}'):
                if items:
                    self.expect(',')
                    if self.consume('}'):
                        break
                if self.consume('['):            # designator [k] =
                    idx = self.const_expr()
                    self.expect(']')
                    self.consume('=')
                if ty.array_len and idx >= ty.array_len:
                    error_at(self.tok.pos, 'too many initializers')
                items.append((idx, self.initializer_list(ty.base)))
                idx += 1
            if ty.array_len == 0:
                ty.array_len = max((k for k, _ in items), default=-1) + 1
                ty.size = ty.array_len * ty.base.size
            return items
        if is_aggregate(ty):
            k = 0
            while not self.consume('}'):
                if items:
                    self.expect(',')
                    if self.consume('}'):
                        break
                if self.consume('.'):            # designator .name =
                    name = self.next().text
                    path = find_member(ty, name)
                    if not path:
                        error_at(self.tok.pos, f'no member named {name}')
                    mem = path[0]
                    k = ty.members.index(mem)
                    self.consume('=')
                if k >= len(ty.members):
                    error_at(self.tok.pos, 'too many initializers')
                mem = ty.members[k]
                items.append((mem, self.initializer_list(mem.ty)))
                k += 1
                if ty.kind == 'union':
                    while not self.consume('}'):
                        self.i += 1
                    break
            return items
        # a scalar in braces: { expr }
        val = self.assign()
        self.consume(',')
        self.expect('}')
        return val

    def lvar_initializer(self, var, tok):
        """Local initializer: clear the object, then assign each element."""
        init = self.initializer_list(var.ty, var)
        zero = Node('MEMZERO', tok, var.ty)
        zero.var = var
        assigns = []
        self.walk_init(init, var.ty, self.new_var_node(var, tok), assigns, tok)
        node = None
        for a in assigns:
            if node is None:
                node = a
            else:
                n = Node('COMMA', tok, a.ty)
                n.lhs, n.rhs = node, a
                node = n
        if node is None:
            node = Node('NULL_EXPR', tok, ty_void)
        comma = Node('COMMA', tok, node.ty)
        comma.lhs, comma.rhs = zero, node
        return comma

    def walk_init(self, init, ty, lvalue, out, tok):
        """Visit every leaf of a braced initializer in order."""
        if isinstance(init, list):
            for key, sub in init:
                if isinstance(key, int):
                    target = self.new_deref(
                        self.new_add(lvalue, self.new_num(key, tok), tok), tok)
                    self.walk_init(sub, ty.base, target, out, tok)
                else:
                    n = Node('MEMBER', tok, key.ty)
                    n.lhs = lvalue
                    n.member = key
                    self.walk_init(sub, key.ty, n, out, tok)
            return
        if is_aggregate(ty) and is_aggregate(init.ty):
            out.append(self.new_assign(lvalue, init, tok))
            return
        out.append(self.new_assign(lvalue, init, tok))

    def gvar_initializer(self, var):
        """Turn a global initializer into bytes and relocations."""
        init = self.initializer_list(var.ty, var)
        data = bytearray(var.ty.size)
        rel = []
        self.write_init(init, var.ty, 0, data, rel)
        var.init_data = bytes(data)
        var.rel = rel

    def write_init(self, init, ty, off, data, rel):
        """Write one initializer leaf into the bytes of a global."""
        if isinstance(init, list):
            for key, sub in init:
                if isinstance(key, int):
                    self.write_init(sub, ty.base, off + key * ty.base.size, data, rel)
                elif key.is_bitfield:
                    self.write_bitfield(sub, key, off, data)
                else:
                    self.write_init(sub, key.ty, off + key.offset, data, rel)
            return
        if is_aggregate(ty):
            error_at(init.tok.pos, 'invalid initializer for a struct')
        val, label, addend = self.eval_rel(init)
        if label:
            if ty.size != 2:
                error_at(init.tok.pos, 'pointer initializer must be 2 bytes')
            rel.append((off, label, addend))
            return
        val = norm(ty, val) & 0xFFFF
        if ty.size == 1:
            data[off] = val & 0xFF
        else:
            data[off] = (val >> 8) & 0xFF       # TARA16 is big-endian
            data[off + 1] = val & 0xFF

    def write_bitfield(self, init, mem, off, data):
        """Write one bit-field of a global initializer into its byte."""
        val = self.eval(init)
        base = off + mem.offset
        size = mem.ty.size
        cur = 0
        for k in range(size):
            cur = (cur << 8) | data[base + k]
        mask = (1 << mem.bit_width) - 1
        cur &= ~(mask << mem.bit_offset) & ((1 << (size * 8)) - 1)
        cur |= (val & mask) << mem.bit_offset
        for k in range(size):
            data[base + size - 1 - k] = (cur >> (8 * k)) & 0xFF

    # -------------------------------------------------- constant evaluation
    def eval(self, node):
        """The number a constant expression stands for, or an error."""
        val, label, _ = self.eval_rel(node)
        if label:
            error_at(node.tok.pos, 'not a compile-time constant')
        return val

    def eval_rel(self, node):
        """Evaluate a constant expression. Returns (value, label, addend);
        `label` is set for the address of a global (`&x`, `arr + 2`, `f`)."""
        k = node.kind
        if k == 'NUM':
            return norm(node.ty, node.val), None, 0
        if k == 'CAST':
            v, lab, add = self.eval_rel(node.lhs)
            if lab:
                return v, lab, add
            return norm(node.ty, v), None, 0
        if k in ('ADD', 'SUB', 'MUL', 'DIV', 'MOD', 'BITAND', 'BITOR',
                 'BITXOR', 'SHL', 'SHR', 'EQ', 'NE', 'LT', 'LE'):
            a, lab, add = self.eval_rel(node.lhs)
            b, lab2, add2 = self.eval_rel(node.rhs)
            if lab2:
                if k != 'ADD' or lab:
                    error_at(node.tok.pos, 'invalid constant expression')
                return 0, lab2, add2 + a
            if lab:
                if k == 'ADD':
                    return 0, lab, add + b
                if k == 'SUB':
                    return 0, lab, add - b
                error_at(node.tok.pos, 'invalid constant expression')
            uns = node.ty.is_unsigned
            if uns:
                a &= 0xFFFF
                b &= 0xFFFF
            if k == 'ADD':
                v = a + b
            elif k == 'SUB':
                v = a - b
            elif k == 'MUL':
                v = a * b
            elif k == 'DIV':
                if b == 0:
                    error_at(node.tok.pos, 'division by zero in a constant')
                v = (a // b) if uns else int(a / b)
            elif k == 'MOD':
                if b == 0:
                    error_at(node.tok.pos, 'division by zero in a constant')
                v = (a % b) if uns else a - int(a / b) * b
            elif k == 'BITAND':
                v = a & b
            elif k == 'BITOR':
                v = a | b
            elif k == 'BITXOR':
                v = a ^ b
            elif k == 'SHL':
                v = a << (b & 15)
            elif k == 'SHR':
                v = (a & 0xFFFF) >> (b & 15) if uns else a >> (b & 15)
            elif k == 'EQ':
                v = 1 if a == b else 0
            elif k == 'NE':
                v = 1 if a != b else 0
            elif k == 'LT':
                v = 1 if a < b else 0
            else:
                v = 1 if a <= b else 0
            return norm(node.ty, v), None, 0
        if k == 'NEG':
            v, lab, _ = self.eval_rel(node.lhs)
            if lab:
                error_at(node.tok.pos, 'invalid constant expression')
            return norm(node.ty, -v), None, 0
        if k == 'BITNOT':
            v, lab, _ = self.eval_rel(node.lhs)
            if lab:
                error_at(node.tok.pos, 'invalid constant expression')
            return norm(node.ty, ~v), None, 0
        if k == 'NOT':
            v, lab, _ = self.eval_rel(node.lhs)
            return (0 if (v or lab) else 1), None, 0
        if k in ('LOGAND', 'LOGOR'):
            a, la, _ = self.eval_rel(node.lhs)
            b, lb, _ = self.eval_rel(node.rhs)
            a = 1 if (a or la) else 0
            b = 1 if (b or lb) else 0
            return (a and b) if k == 'LOGAND' else (a or b), None, 0
        if k == 'COND':
            c, lab, _ = self.eval_rel(node.cond)
            return self.eval_rel(node.then if (c or lab) else node.els)
        if k == 'COMMA':
            return self.eval_rel(node.rhs)
        if k == 'ADDR':
            return self.eval_addr(node.lhs)
        if k == 'VAR':
            if is_array_like(node.ty) or node.ty.kind == 'func':
                return self.eval_addr(node)
            error_at(node.tok.pos, 'not a compile-time constant')
        if k == 'MEMBER':
            if is_array_like(node.ty):
                return self.eval_addr(node)
        error_at(node.tok.pos, 'not a compile-time constant')

    def eval_addr(self, node):
        """The address a constant expression names, as label plus offset."""
        if node.kind == 'VAR':
            if node.var.is_local:
                error_at(node.tok.pos, 'not a compile-time constant')
            name = (f'__ind_{node.var.name}' if node.var.is_function
                    else node.var.name)
            return 0, name, 0
        if node.kind == 'DEREF':
            return self.eval_rel(node.lhs)
        if node.kind == 'MEMBER':
            v, lab, add = self.eval_addr(node.lhs)
            return v, lab, add + node.member.offset
        if node.kind == 'CAST':
            return self.eval_addr(node.lhs)
        error_at(node.tok.pos, 'invalid address constant')


TYPE_KEYWORDS = set('''void _Bool char short int long float double signed
__signed__ unsigned const volatile auto register restrict __restrict
__volatile__ _Alignas _Atomic _Thread_local struct union enum typedef static
extern inline typeof'''.split())
STORAGE_KEYWORDS = set('typedef static extern inline register auto _Thread_local '
                       '_Noreturn'.split())


# the whole front end, as one call
def parse(toks, opt=None):
    return Parser(toks, opt).parse()
