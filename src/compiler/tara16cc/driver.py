# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. GPL-3.0-or-later.
"""The command line: compile, assemble, link, run.

    tara16-cc prog.c [more.c ...] [extra.s ...] [-o prog.hex] [options]

    prog.c ---- tara16cc ----> prog.s ---+
    runtime/crt0.s ---------------------+--- tara16cc.asm --> prog.hex
    runtime/libtara16.s ----------------+    (assembler,      prog.tara
                                             linker)         prog.lst .sym
Options
    --run            run on the built-in TARA16; print main()'s value
    --display        (with --run) print the 64x64 screen as text
    --png FILE       (with --run) save the screen as a PNG (needs Pillow)
    --keys N         (with --run) the game-input byte at 0x5FF
    --max N          (with --run) instruction limit (default 5,000,000)
    -mno-mul         no MUL instruction (TARA16-TTL board)
    --stack-top A    initial SP (default 0x5FE)
    --lines          mark each instruction with the line of C it came from
    -S               stop after writing prog.s
    -I DIR, -D X=Y   passed to the preprocessor
    --no-gc          keep unreferenced functions and data
    -O0 -O1 -O2      how many optimizations to use (default -O2)
    -fno-NAME        switch one idea off (see --help-opts)
    --dump-ast [FN]  print the tree the code generator receives
    -q               quiet
"""
import os
import sys

from . import asm as AS
from .codegen import gen_program
from .diag import CompileError
from .lex import convert_numbers
from .opt import Options
from .parse import Parser
from .pp import preprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def bundled_dir(here):
    """Where include/ and runtime/ live; unpacked first if this is a zipapp."""
    if os.path.isdir(os.path.join(here, 'include')):
        return here                  # an ordinary folder: read them in place
    zip_path, inner = here, ''       # inside a .pyz: find the zip above us
    while not os.path.isfile(zip_path):
        parent, tail = os.path.split(zip_path)
        if parent == zip_path:
            return here              # reached the root without finding one
        zip_path, inner = parent, (tail + '/' + inner if inner else tail)
    import atexit
    import shutil
    import tempfile
    import zipfile
    out = tempfile.mkdtemp(prefix='tara16cc-')
    atexit.register(shutil.rmtree, out, True)
    want = (inner + '/include/', inner + '/runtime/')
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.startswith(want):
                z.extract(name, out)
    return os.path.join(out, inner)


BUNDLE = bundled_dir(HERE)
INCLUDE = os.path.join(BUNDLE, 'include')
CRT0 = os.path.join(BUNDLE, 'runtime', 'crt0.s')
LIB = os.path.join(BUNDLE, 'runtime', 'libtara16.s')


def compile_file(path, opt, include_paths, defines, dump_ast=None):
    """One .c file to assembly text."""
    toks = convert_numbers(preprocess(path, include_paths, defines))
    parser = Parser(toks, opt)
    prog = parser.parse()
    text = gen_program(prog, opt, path)
    if dump_ast is not None:
        # after code generation, so the weights and registers are filled in
        from .dump import dump_program
        dump_program(prog, dump_ast, sys.stderr)
    return text


def main(argv=None):
    """The command line: parse the options, run the pipeline, report."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or '-h' in argv or '--help' in argv:
        print(__doc__)
        return 0
    if '--help-opts' in argv:
        print('optimizations (all on at -O2):')
        for name in Options.NAMES:
            print(f'  -fno-{name.replace("_", "-"):<14} {Options.HELP[name]}')
        return 0
    out = None
    run = display = quiet = only_s = False
    png = None
    keys = None
    max_steps = 5_000_000
    stack_top = 0x5FE
    srcs = []
    include_paths = []
    defines = []
    dump_ast = None
    opt = Options(2)
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '-o':
            i += 1
            out = argv[i]
        elif a == '--run':
            run = True
        elif a == '--display':
            display = run = True
        elif a == '--png':
            i += 1
            png = argv[i]
            run = True
        elif a == '--keys':
            i += 1
            keys = int(argv[i], 0)
        elif a == '--max':
            i += 1
            max_steps = int(argv[i])
        elif a == '--stack-top':
            i += 1
            stack_top = int(argv[i], 0)
        elif a == '--lines':
            opt.lines = True
        elif a == '-S':
            only_s = True
        elif a == '--no-gc':
            opt.gc = False
        elif a == '-q':
            quiet = True
        elif a == '--dump-ast':
            dump_ast = '*'
            if i + 1 < len(argv) and not argv[i + 1].startswith('-') and \
                    not argv[i + 1].endswith(('.c', '.s')):
                i += 1
                dump_ast = argv[i]
        elif a in ('-mno-mul', '-mmul'):
            opt.mul = a == '-mmul'
        elif a in ('-O0', '-O1', '-O2', '-O3', '-Os'):
            opt.set_level(0 if a == '-O0' else 1 if a == '-O1' else 2)
        elif a.startswith('-fno-') or a.startswith('-f'):
            name = a[5:] if a.startswith('-fno-') else a[2:]
            if not opt.set(name.replace('-', '_'), not a.startswith('-fno-')):
                sys.exit(f'tara16-cc: unknown option {a} (see --help-opts)')
        elif a in ('-I', '-D'):
            i += 1
            (include_paths if a == '-I' else defines).append(argv[i])
        elif a.startswith('-I'):
            include_paths.append(a[2:])
        elif a.startswith('-D'):
            defines.append(a[2:])
        elif a.endswith(('.c', '.s', '.tara')):
            srcs.append(a)
        else:
            sys.exit(f'tara16-cc: unknown argument {a!r} (see --help)')
        i += 1
    if not srcs:
        sys.exit('tara16-cc: no input files')
    base = os.path.splitext(out or srcs[0])[0]
    out = base + '.hex'
    include_paths = include_paths + [INCLUDE]

    # 1. compile the C files
    parts = [('runtime/crt0.s', open(CRT0).read())]
    nc = 0
    for src in srcs:
        if not src.endswith('.c'):
            parts.append((src, open(src).read()))
            continue
        try:
            text = compile_file(src, opt, include_paths, defines, dump_ast)
        except CompileError as e:
            print(str(e), file=sys.stderr)
            return 1
        if nc:
            # every file numbers its own labels from zero: keep them apart
            import re
            text = re.sub(r'(?<![\w.$])\.(L\.\.|T)(\d+)\b',
                          lambda m: f'.{m.group(1)}{nc}_{m.group(2)}', text)
        nc += 1
        parts.append((src, text))
    parts.append(('runtime/libtara16.s', open(LIB).read()))

    combined = ''.join(f'\n; ======== {name} ========\n{text}'
                       for name, text in parts)
    with open(base + '.s', 'w') as f:
        f.write(combined)
    if only_s:
        return 0

    # 2. assemble and link
    try:
        img = AS.assemble_text(combined, base + '.s',
                               defines={'__stack_top': stack_top}, gc=opt.gc)
    except AS.AsmError as e:
        print(f'tara16-cc: {e}', file=sys.stderr)
        return 1
    with open(base + '.s', 'w') as f:
        f.write(f'; {os.path.basename(base)}.s -- generated by tara16-cc, '
                f'ported from chibicc; only the code and data that were '
                f'linked are shown\n')
        f.write(f'        .equ __stack_top, 0x{stack_top:03X}\n')
        f.write(AS.live_source(img.prog))
    if img.end > stack_top - 32:
        print(f'tara16-cc: program too big: image ends at 0x{img.end:03X}, '
              f'leaving {stack_top - img.end} bytes for the stack '
              f'(stack top 0x{stack_top:03X})', file=sys.stderr)
        return 1
    AS.write_hex(img, out)
    AS.write_lst(img, base + '.lst')
    AS.write_sym(img, base + '.sym')
    init_words = AS.write_studio(img, base + '.tara', 'main',
                                 title=os.path.basename(srcs[0]))
    studio_end = ((img.end + 1) & ~1) + 2 * init_words
    if not quiet:
        print(f'{os.path.basename(out)}: ' + AS.summary(img, stack_top) +
              f'; Studio .tara adds {init_words} init instruction'
              f'{"" if init_words == 1 else "s"}')
    if studio_end > 0x5FE:
        print(f'tara16-cc: warning: {os.path.basename(base)}.tara ends at '
              f'0x{studio_end:03X} (its __init code reaches the keyboard byte '
              f'0x5FF / framebuffer); load the .hex image instead',
              file=sys.stderr)

    # 3. run it
    if run:
        from . import sim
        words = [(img.mem[a] << 8) | (img.mem[a + 1] if a + 1 < len(img.mem) else 0)
                 for a in range(0, (img.end + 1) & ~1, 2)]
        cpu, n, min_sp = sim.run(words, max_steps, keys, stack_limit=img.end)
        r0 = cpu.reg[0] & 0xFFFF
        s0 = r0 - 0x10000 if r0 & 0x8000 else r0
        if cpu.error:
            print(f'ERROR: {cpu.error}')
        elif not cpu.halted:
            print(f'did not halt within {n} instructions')
        print(f'main() returned {s0} (0x{r0:04X}) after {n} instructions; '
              f'stack used {stack_top - min_sp} bytes')
        if display:
            print(sim.display_text(cpu))
        if png:
            sim.display_png(cpu, png)
        if cpu.error or not cpu.halted:
            return 1
    return 0
