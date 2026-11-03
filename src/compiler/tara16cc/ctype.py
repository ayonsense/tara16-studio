# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""The TARA16 C type system.

Sizes are what a 16-bit machine can afford:

    char 1 (UNSIGNED)   signed char 1   _Bool 1
    short 2   int 2   unsigned 2   enum 2   every pointer 2

There is no `long`, no `float` and no `double`; the parser rejects them.
`int` is therefore the widest type, which makes the usual arithmetic
conversions short: anything narrower than 2 bytes becomes `int`, and if one
side of a binary operator is `unsigned`, the result is `unsigned`.
"""


def align_to(n, align):
    """The next multiple of `align` at or above n."""
    return (n + align - 1) // align * align


class Member:
    """One field of a struct or union: its type, offset and bit position."""
    __slots__ = ('name', 'ty', 'offset', 'align', 'is_bitfield', 'bit_offset',
                 'bit_width', 'idx', 'tok')

    def __init__(self, name, ty, tok=None):
        self.name = name
        self.ty = ty
        self.tok = tok
        self.offset = 0
        self.align = ty.align
        self.is_bitfield = False
        self.bit_offset = 0
        self.bit_width = 0
        self.idx = 0


class Type:
    """A C type. Pointers and arrays point at the type they are made of."""
    __slots__ = ('kind', 'size', 'align', 'is_unsigned', 'base', 'array_len',
                 'members', 'tag', 'return_ty', 'params', 'is_variadic',
                 'is_atomic', 'is_const')

    def __init__(self, kind, size, align, is_unsigned=False):
        self.kind = kind
        self.size = size
        self.align = align
        self.is_unsigned = is_unsigned
        self.base = None            # pointer / array element type
        self.array_len = 0
        self.members = None         # struct / union
        self.tag = None
        self.return_ty = None       # function
        self.params = None
        self.is_variadic = False
        self.is_atomic = False
        self.is_const = False

    def copy(self):
        """A duplicate, so a qualifier can be added without touching others."""
        t = Type(self.kind, self.size, self.align, self.is_unsigned)
        for f in Type.__slots__:
            setattr(t, f, getattr(self, f))
        return t

    def __repr__(self):
        return type_name(self)


ty_void = Type('void', 1, 1)
ty_bool = Type('bool', 1, 1, True)
ty_char = Type('char', 1, 1, True)      # TARA16: plain char is unsigned
ty_schar = Type('char', 1, 1, False)    # explicit `signed char`
ty_uchar = Type('char', 1, 1, True)
ty_short = Type('short', 2, 2)
ty_ushort = Type('short', 2, 2, True)
ty_int = Type('int', 2, 2)
ty_uint = Type('int', 2, 2, True)
ty_size_t = ty_uint
ty_ptrdiff_t = ty_int

INT_KINDS = ('bool', 'char', 'short', 'int', 'enum')


def is_integer(ty):
    """Is this a type arithmetic works on directly (including enums)?"""
    return ty.kind in INT_KINDS


def is_scalar(ty):
    """Is this a single value -- a number or a pointer?"""
    return is_integer(ty) or ty.kind == 'ptr'


def is_aggregate(ty):
    """Is this a struct or union, copied rather than moved?"""
    return ty.kind in ('struct', 'union')


def is_array_like(ty):
    """Is this an array, which decays to a pointer in most expressions?"""
    return ty.kind == 'array'


def is_schar(ty):
    """Is this `signed char`, the one type a byte load must sign-extend?"""
    return ty.kind == 'char' and not ty.is_unsigned


def pointer_to(base):
    """The type "pointer to base"."""
    t = Type('ptr', 2, 2, True)
    t.base = base
    return t


def array_of(base, length):
    """The type "array of `length` base", with its size worked out."""
    t = Type('array', base.size * length, base.align)
    t.base = base
    t.array_len = length
    return t


def func_type(return_ty, params=None, variadic=False):
    """The type "function returning return_ty"."""
    t = Type('func', 1, 1)
    t.return_ty = return_ty
    t.params = params or []
    t.is_variadic = variadic
    return t


def enum_type():
    """A fresh enum type, which behaves as an int."""
    t = Type('enum', 2, 2)
    return t


def struct_type(kind='struct'):
    """A fresh, still empty struct or union type."""
    t = Type(kind, 0, 1)
    t.members = []
    return t


def type_name(ty):
    """A readable name, for error messages and the AST dump."""
    if ty is None:
        return '?'
    if ty.kind == 'ptr':
        return type_name(ty.base) + '*'
    if ty.kind == 'array':
        return f'{type_name(ty.base)}[{ty.array_len}]'
    if ty.kind == 'func':
        return f'{type_name(ty.return_ty)}()'
    if ty.kind in ('struct', 'union'):
        return f'{ty.kind} {ty.tag or "<anonymous>"}'
    if ty.kind == 'char':
        return 'char' if ty.is_unsigned else 'signed char'
    if ty.kind == 'enum':
        return 'enum'
    if ty.kind == 'bool':
        return '_Bool'
    return ('unsigned ' if ty.is_unsigned else '') + ty.kind


def get_common_type(ty1, ty2):
    """The type both operands of a binary operator are converted to."""
    if ty1.base:
        return pointer_to(ty1.base)
    # integer promotion: anything narrower than int becomes int
    if ty1.size < 2 or ty1.kind in ('short', 'enum', 'bool'):
        ty1 = ty_uint if (ty1.size == 2 and ty1.is_unsigned) else ty_int
    if ty2.size < 2 or ty2.kind in ('short', 'enum', 'bool'):
        ty2 = ty_uint if (ty2.size == 2 and ty2.is_unsigned) else ty_int
    if ty1.is_unsigned or ty2.is_unsigned:
        return ty_uint
    return ty_int


def norm(ty, v):
    """A constant of type ty, wrapped to its width (TARA16 is 16-bit)."""
    v = int(v)
    if ty.kind == 'bool':
        return 1 if v else 0
    if ty.size == 1:
        v &= 0xFF
        return v if ty.is_unsigned else (v - 0x100 if v & 0x80 else v)
    v &= 0xFFFF
    if ty.is_unsigned or ty.kind == 'ptr':
        return v
    return v - 0x10000 if v & 0x8000 else v


def layout_struct(ty):
    """Give every member an offset; compute size and alignment."""
    bits = 0
    for mem in ty.members:
        if ty.kind == 'union':
            mem.offset = 0
            if mem.is_bitfield:
                mem.bit_offset = 0
            ty.size = max(ty.size, mem.ty.size)
            ty.align = max(ty.align, mem.align)
            continue
        if mem.is_bitfield and mem.bit_width == 0:
            bits = align_to(bits, mem.ty.size * 8)       # start a new unit
        elif mem.is_bitfield:
            sz = mem.ty.size
            if bits // (sz * 8) != (bits + mem.bit_width - 1) // (sz * 8):
                bits = align_to(bits, sz * 8)            # would straddle
            mem.offset = (bits // 8) // sz * sz
            mem.bit_offset = bits % (sz * 8)
            bits += mem.bit_width
        else:
            bits = align_to(bits, mem.align * 8)
            mem.offset = bits // 8
            bits += mem.ty.size * 8
        ty.align = max(ty.align, mem.align)
    if ty.kind != 'union':
        ty.size = align_to(bits, ty.align * 8) // 8
    else:
        ty.size = align_to(ty.size, ty.align)


def find_member(ty, name):
    """Find a member by name, looking through anonymous struct/union members."""
    for mem in ty.members or []:
        if mem.name == name:
            return [mem]
        if mem.name is None and is_aggregate(mem.ty):
            path = find_member(mem.ty, name)
            if path:
                return [mem] + path
    return None
