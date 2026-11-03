# tara16-cc — the same compiler, in Python

This folder holds `tara16cc`: a C compiler for the TARA16 teaching CPU,
written in Python and nothing else. No C compiler, no `make`, no build step —
`python3 tara16-cc prog.c` compiles, assembles, links and can run the program.

```
prog.c ──tara16cc──► prog.s ──tara16cc/asm.py──► prog.hex   Verilog $readmemh, FPGA
                                              └─► prog.tara  TARA Studio
```

It is the twin of `../compiler_chibicc`, which is the same compiler in C.
The two are held to instruction-for-instruction agreement: `tests/difftest.py`
compiles every program with both and compares the assembly function by
function. Read whichever you prefer; the Python one is here because it is the
one you can read in an afternoon.

## Quick start

Python 3.8 or later, and nothing else. There is no build step, no `make` and
no dependency to install: `tara16-cc` is a small script that runs the
`tara16cc` package sitting next to it.

```
cd TARA16/compiler/compiler_python
python3 tara16-cc examples/fib.c --run             # compile and run
python3 tara16-cc examples/display_demo.c --display
python3 tara16-cc examples/snake.c                 # open snake.tara in TARA Studio
python3 tests/run_tests.py                         # 31 test programs
```

## Making a `tara16-cc` of your own

Python reads the compiler's source on every run, so the folder above *is* the
working compiler and there is no binary waiting to be built. To give it to
somebody else, package it. The three commands differ in what the receiving
machine must already have.

| what you get | built with | needs Python | size |
|---|---|---|---|
| the folder, as it stands | nothing | yes | — |
| a `tara16-cc` command | `pip install` | yes | — |
| one file you can copy | `zipapp` | yes | 330 KB |
| a native executable | PyInstaller | no | about 30 MB |

All four compile to byte-identical images. Packaging changes how the compiler
is delivered, never what it produces.

**A command on your path.** Copies the package, its runtime and its headers
into your Python environment:

```
python3 -m pip install .              # from this folder
cd ~ && echo 'int main(void) { return 7 * 6; }' > q.c
tara16-cc q.c -o q.hex --run          # main() returned 42
```

Use `pip install -e .` instead if you intend to change the compiler: the
command then runs the files in this folder, so edits take effect at once.
`python3 -m pip uninstall tara16-cc` undoes either.

**One file you can copy.** A zipapp is a single executable archive. Copy it to
any machine with Python 3.8 and it runs — nothing to install, nothing to
unpack. This is the smallest useful thing to hand to a class:

```
rm -rf build && mkdir build && cp -r tara16cc build/
find build -name '__pycache__' -prune -exec rm -rf {} +
python3 -m zipapp build -m "tara16cc.driver:main" \
        -o tara16-cc.pyz -p "/usr/bin/env python3"
chmod +x tara16-cc.pyz

./tara16-cc.pyz examples/fib.c --run
```

The staging folder is needed because `zipapp` archives the *contents* of the
folder it is given, and `tara16cc` must stay a package inside the archive.
`bundled_dir` in `driver.py` unpacks the runtime and the headers at startup,
because an `open()` on a file inside a zip does not work.

**A binary that needs no Python.** PyInstaller bundles an interpreter with the
compiler. The receiving machine needs nothing at all; the price is the size:

```
python3 -m pip install pyinstaller
printf 'from tara16cc.driver import main\nimport sys\nsys.exit(main())\n' > entry.py
pyinstaller --onefile --name tara16-cc \
    --add-data "tara16cc/runtime:tara16cc/runtime" \
    --add-data "tara16cc/include:tara16cc/include" entry.py

dist/tara16-cc examples/fib.c --run
```

The two `--add-data` arguments are not optional: without them the runtime and
headers are left out and the compiler fails on the first program. Use `;`
instead of `:` in them on Windows.

Section 0 of [**Writing a Compiler for 2 KB**](doc/writing-a-compiler.html)
covers all of this at more length.

## The documentation

Two pages, both self-contained and needing no network.

| | |
|---|---|
| [`doc/writing-a-compiler.html`](doc/writing-a-compiler.html) | **Writing a Compiler for 2 KB** — the ideas, stage by stage, with the 2 KB budget as the constraint behind every design choice. Contains a pipeline explorer: one program shown as C, tokens, tree, instructions and machine words, where clicking a line of C shows what it became at every other stage. |
| [`doc/reading-the-source.html`](doc/reading-the-source.html) | **Reading the Source** — the code itself: all seventeen files in reading order, with every one of the 388 classes and functions named, placed and explained. |

Every listing in them is extracted from the sources and every number is
measured, so neither page can drift from the compiler
([`doc/README.md`](doc/README.md) says how to rebuild them).

## How to read it

Four stages, in the order the text moves through them, and one pass between
the last two. Each file is meant to be read on its own, start to finish.

| | | |
|---|---|---|
| `lex.py` | 241 lines | text → tokens |
| `pp.py` | 511 | `#include`, `#define`, `#if` — token list in, token list out |
| `parse.py` | 1804 | tokens → a tree, with every C rule checked and every conversion made explicit |
| `inline.py` | 446 | tree → tree: small functions copied into the places that call them |
| `codegen/` | 3108 | the tree → TARA16 instructions |

and around them:

| | |
|---|---|
| `ctype.py` | the type system: sizes, promotions, struct and bit-field layout |
| `node.py` | the two data structures: `Node` (a piece of program) and `Obj` (a variable or function) |
| `diag.py` | error messages with the source line and a caret |
| `opt.py` | one switch per optimization |
| `dump.py` | `--dump-ast`: print the tree the code generator is given |
| `asm.py` | the assembler and linker |
| `sim.py` | a TARA16 in 220 lines, so `--run` needs nothing else |
| `driver.py` | the command line |

The back end is five files, one concern each:

| | |
|---|---|
| `codegen/target.py` | the machine: registers, the instruction buffer, addresses |
| `codegen/expr.py` | expressions — values, calls, comparisons, arithmetic |
| `codegen/stmt.py` | statements — control flow, `switch`, `return` |
| `codegen/func.py` | whole functions: weights, live ranges, registers, frame, prologue, epilogue, data |
| `codegen/peephole.py` | the clean-up pass |

A good first path through the compiler: `diag.py`, `node.py`, `ctype.py`,
`lex.py`, then `codegen/target.py` — and only then `parse.py` and
`codegen/expr.py`, the two large ones.

## Every optimization is a switch

The code generator has a plain mode and an optimizing mode, and each idea in
the optimizing mode can be switched off by name. So "what is this idea worth?"
is a command, not an editing session:

```
python3 tara16-cc examples/snake.c -O0             # nothing but the plain translation
python3 tara16-cc examples/snake.c -fno-regvars    # everything except register variables
python3 tara16-cc --help-opts                      # the list
python3 tests/ablate.py                            # measure them all
```

On the 31 test programs and on Snake (2 KB is the whole machine), as
`tests/ablate.py` prints them:

| off | tests | vs `-O2` | snake |
|---|---:|---:|---:|
| — (`-O2`, the default) | 6052 B | | 1248 B |
| `-O0` (all of them) | 10472 B | +73.0% | **over 2 KB** |
| `-O1` | 6352 B | +5.0% | 1290 B |
| `--no-gc` (keep unused code) | 15430 B | +155.0% | **over 2 KB** |
| `-fno-regvars` | 7528 B | +24.4% | **over 2 KB** |
| `-fno-compound-fix` | 6958 B | +15.0% | 1452 B |
| `-fno-steer` | 6730 B | +11.2% | 1324 B |
| `-fno-savetrim` | 6324 B | +4.5% | 1260 B |
| `-fno-peephole` | 6290 B | +3.9% | 1260 B |
| `-fno-inline` | 6288 B | +3.9% | 1228 B |
| `-fno-live` | 6286 B | +3.9% | 1424 B |
| `-fno-order` | 6090 B | +0.6% | 1252 B |
| `-fno-epilogues` | 6084 B | +0.5% | 1280 B |
| `-fno-zero-page` | 6082 B | +0.5% | 1308 B |
| `-fno-cse` | 6072 B | +0.3% | 1254 B |
| `-mno-mul` (the TTL board) | 7396 B | +22.2% | 1248 B |

Snake does not fit at `-O0`. That is the point of the whole back end.

Two of the switches are about time as much as space. `-flive` lets variables
that are never alive together share a register, which keeps more of them out
of memory. `-finline` copies small functions into their callers: over the test
programs that saves bytes, because most of the copies are smaller than the
calls they replace, but it makes snake 20 bytes larger, because it copies
helpers into loops. What it buys is speed — in a Flappy Bird game that draws
with `pset`, about a fifth fewer cycles per frame. Both are off with
`-fno-live` and `-fno-inline`; `-O1` turns inlining off too. The C compiler
next door has `-fno-inline` as well.

## The dialect in five lines

* `int`, `short`, `unsigned` and pointers are 16 bits; plain `char` is unsigned.
* `long`, `float`, `double`, variadic functions, VLAs, `alloca`, computed
  `goto`, atomics and thread-local storage are rejected with a clear message.
* Everything else is there: structs, unions, bit-fields, enums, function
  pointers, `switch`, `goto`, recursion, string literals, initializers.
* Headers: `tara16.h` (pixels, keys, digits, random numbers), `stdint.h`,
  `stdbool.h`, `stddef.h`, `limits.h`. No C library.
* Code, data and stack share 1.5 KB; the screen takes the top 512 bytes.

## Folders

```
tara16-cc            the command (python3 tara16-cc ...)
tara16cc/            the compiler
tara16cc/codegen/    the back end
tara16cc/runtime/    crt0.s (start-up), libtara16.s (divide, shifts, __icall, ...)
tara16cc/include/    tara16.h and the small standard headers
examples/            fib, display_demo, bounce, snake
tests/               test programs and the four checkers below
```

## Verification

| | |
|---|---|
| `tests/run_tests.py` | every test program three ways: on `sim.py`, with `-mno-mul`, and on the golden simulator when `python-sim` is found above this folder |
| `tests/difftest.py` | the same program through both compilers, compared function by function; `--fuzz N` does it on random programs |
| `tests/fuzz_expr.py` | random expression-heavy programs against a Python model of C's 16-bit rules |
| `tests/fuzz_prog.py` | the same for whole programs: statements, loops, `switch`, arrays, pointers, calls |
| `tests/ablate.py` | every optimization switch, checked for size *and* for still giving the right answer |
| `doc/tools/lab.py` | the same, plus every listing in the tutorial; refuses to publish numbers if any answer is wrong |

All 31 test programs and all four examples compile to the same instructions as
the C compiler next door.

## Later: `pip install tara16-cc` from PyPI

Installing from this folder already works, as above. Publishing it so that
`pip install tara16-cc` works on a machine that has never seen this repository
is a matter of filling in the metadata in `pyproject.toml` and uploading: the
layout is already a package, with `__main__.py`, the runtime and the headers
all inside `tara16cc/`.

## Licence

GPL-3.0-or-later. The parser and preprocessor follow the structure of
[chibicc](https://github.com/rui314/chibicc) by Rui Ueyama (MIT licence).
