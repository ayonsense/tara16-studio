# Bundled TARA compiler

`tara16cc/` is copied unchanged from
`TARA16/compiler/compiler_python/tara16cc/` on 16 October 2026. The compiler
is pure Python and requires no installed C compiler, network connection, or
separate compiler checkout. Its headers and assembly runtime must remain
inside the package. The grouped library contains all 27 unmodified C sources
from `compiler_web/src/examples`, under Basic, Intermediate, Advanced, Display,
and Games. `catalog.py` holds their ordering, descriptions, run instructions,
and expected results. The original four root-level examples are preserved
for compatibility but are not duplicated in the selector. Generated build
outputs and bytecode caches are not included.

The upstream source is GPL-3.0-or-later, matching Studio's root `LICENSE`.
The parser and preprocessor follow chibicc's structure; Rui Ueyama's MIT
notice is preserved in `LICENSE.chibicc`. `UPSTREAM_README.md` is a verbatim
reference from the source compiler. Paths and commands in that reference
describe the original compiler checkout, not this Studio layout.

## Integration API

```python
from src.compiler import CompilationError, compile_source

result = compile_source(
    'int main(void) { return 42; }',
    source_path=None,       # original filename, for includes and diagnostics
    optimization=2,        # 0, 1, or 2
    use_mul=True,          # False for a TTL board without hardware MUL
)
if result.studio_compatible:
    print(result.assembly)  # pass this text to Studio's assembly editor
```

`service.py` saves the editor snapshot in a temporary directory and invokes
`sys.executable -m src.compiler.tara16cc` with a 30-second timeout. The source
file and any adjacent outputs are never changed. A saved document's parent
directory is added to the include search path; the package's standard headers
are always available. On success, all outputs are read into an immutable
`CompileResult`, and the temporary directory is removed. On failure,
`CompilationError` carries the compiler's diagnostic text. The API itself has
no Qt dependency and can be called from a GUI worker thread.

The result contains:

| Field | Meaning |
| --- | --- |
| `assembly` | `.tara`, ready for Studio's instruction-only assembler |
| `native_assembly` | `.s`, retaining compiler/linker directives and pseudo-ops |
| `hex_text` | `.hex`, the native machine image, one 16-bit word per line |
| `listing_text` | `.lst`, native addresses, words, and source instructions |
| `symbols_text` | `.sym`, native symbol addresses |
| `diagnostics` | Compiler messages and memory summary |
| `studio_error` | `None` when transfer is allowed; otherwise the reason to block it |

Use `.tara` for Assembly transfer. Native `.s` cannot be assembled by Studio.
The `.tara` exporter reserves data space with NOP instructions and appends an
initializer that writes nonzero globals before entering `main`. Consequently,
its image and instruction count can differ from the native HEX image, although
program behavior agrees. Listings and symbol output describe the native image.

The service reassembles `.tara` with Studio's actual assembler and requires its
complete image, including the initializer, to leave at least 32 bytes below
the default stack top `0x5FE`. If only this check fails, compilation still
returns the native artifacts so they can be exported. This minimum reserve
does not guarantee sufficient stack for recursion or large local arrays.

The integration compiles one C translation unit. It does not expose the
compiler CLI's multiple-input, custom macro, or stack-top flags. The bundled
CLI remains available for those uses:

```sh
python -m src.compiler.tara16cc path/to/program.c --run
python -m unittest discover -s tests -p test_compiler.py -v
```

The service requires the Python interpreter used to launch Studio; native
freezing would need a dedicated child-process launcher. When packaging Studio,
include `compiler/tara16cc/include/*.h`, `compiler/tara16cc/runtime/*.s`, the C
examples, and the notices/readmes alongside the Python modules.

## Updating the bundled copy

Replace `tara16cc/` with a clean copy of the upstream package, preserving its
headers and runtime; copy updated examples and attribution as needed. Keep
Studio-specific changes in `service.py`. Run the integration tests after each
update: they exercise initialized globals and strings, sibling headers,
unsaved sources, compiler diagnostics, optimization levels, software multiply,
native-versus-Studio execution, and oversized Studio initializers.

## Grouped C library

Read the project-root `C_PROGRAMS.md` for all example contracts and validation.
`tests/test_c_programs.py` executes every catalog program in both multiplication
modes on Studio's CPU. `tools/verify_compiler_wasm.mjs` additionally checks the
real Pyodide WebAssembly compiler against Studio; the saved JSON report contains
54 passing builds and byte-identical compiler-source evidence.
