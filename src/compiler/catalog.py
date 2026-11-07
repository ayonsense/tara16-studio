"""Teaching catalog shared by the compiler UI, documentation, and validation.

The 27 C sources are unmodified copies of ``compiler_web/src/examples``.
Metadata stays separate so the examples remain comparable with the WASM build.
Category and example order deliberately progress from arithmetic to games.
The older examples directly inside ``examples/`` are kept for compatibility but
are not catalog entries; only the five category folders form this library.
"""
from dataclasses import dataclass
from pathlib import Path


EXAMPLE_CATEGORIES: tuple[str, ...] = (
    "Basic", "Intermediate", "Advanced", "Display", "Games",
)
_EXAMPLES_ROOT = Path(__file__).resolve().parent / "examples"


@dataclass(frozen=True)
class Example:
    """One bundled C program and its student-facing usage contract.

    ``id`` is the stable source stem used by the web compiler. ``path`` is
    absolute and independent of the current working directory. Instruction and
    result fields describe the original source, not an assumed test outcome.
    """

    id: str
    title: str
    category: str
    path: Path
    description: str
    instructions: str
    expected_result: str


def _example(
    category: str, example_id: str, title: str, description: str,
    instructions: str, expected_result: str,
) -> Example:
    """Build an entry without reading or modifying its bundled C source."""
    return Example(
        id=example_id,
        title=title,
        category=category,
        path=_EXAMPLES_ROOT / category / f"{example_id}.c",
        description=description,
        instructions=instructions,
        expected_result=expected_result,
    )


EXAMPLES: tuple[Example, ...] = (
    _example(
        "Basic", "factorial", "Factorial",
        "Compute 6! with an iterative multiplication loop; introduces an accumulator and a countdown.",
        "Compile, send to TARA16 Assembly, load, and run. No input memory is needed. "
        "Change factor = 6 to explore other small nonnegative inputs; 16-bit arithmetic limits the result.",
        "The CPU halts with R0 = 720 (0x02D0).",
    ),
    _example(
        "Basic", "fibonacci", "Fibonacci",
        "Compute F(10) using the classic pair of running values, without recursion or an array.",
        "Compile, load, and run. No input memory is needed. The count variable selects the Fibonacci index; "
        "the supplied count = 10 starts with a = 0 and b = 1.",
        "The CPU halts with R0 = 55 (0x0037).",
    ),
    _example(
        "Basic", "sum_1_to_n", "Sum 1 to N",
        "Add the integers from 1 through 10 with a descending loop and a running sum.",
        "Compile, load, and run. No input memory is needed. Change value = 10 for another small positive limit.",
        "The CPU halts with R0 = 55 (0x0037).",
    ),
    _example(
        "Basic", "power_of_two", "Power of Two",
        "Compute 2^10 by repeated doubling; demonstrates exponentiation using addition alone.",
        "Compile, load, and run. No input memory is needed. count = 10 is the exponent; "
        "keep experiments within the target's 16-bit range.",
        "The CPU halts with R0 = 1024 (0x0400).",
    ),
    _example(
        "Basic", "count_set_bits", "Count Set Bits",
        "Count the 1 bits in unsigned 0xB3B5 using a mask and logical right shifts.",
        "Compile, load, and run. No input memory is needed. Change the unsigned value to inspect another 16-bit pattern.",
        "The CPU halts with R0 = 10 (0x000A).",
    ),
    _example(
        "Intermediate", "greatest_common_divisor", "Greatest Common Divisor",
        "Find gcd(48, 18) using Euclid's subtraction method and a two-way conditional.",
        "Compile, load, and run. No input memory is needed. Use positive a and b values when modifying this example; "
        "the subtraction loop does not handle a zero operand.",
        "The CPU halts with R0 = 6 (0x0006).",
    ),
    _example(
        "Intermediate", "collatz_steps", "Collatz Steps",
        "Count the transitions from 7 to 1 using the Collatz odd/even rule: 3n + 1 or n / 2.",
        "Compile, load, and run. No input memory is needed. value = 7 selects the starting point; "
        "other inputs must avoid overflow in the 16-bit unsigned sequence.",
        "The CPU halts with R0 = 16 (0x0010).",
    ),
    _example(
        "Intermediate", "prime_test", "Prime Test",
        "Test 17 for primality with trial division; a helper implements divisibility using repeated subtraction.",
        "Compile, load, and run. No input memory is needed. Change value = 17 to test another small nonnegative integer.",
        "The CPU halts with R0 = 1 (prime). Composite values and values below 2 return 0.",
    ),
    _example(
        "Intermediate", "first_n_primes", "First N Primes",
        "Generate the first ten primes and write them to a visible byte array in data memory.",
        "Compile, load, and run; the program supplies its own data. Inspect byte addresses 0x0400-0x0409 after halt.",
        "R0 = 10. Memory contains decimal 2, 3, 5, 7, 11, 13, 17, 19, 23, 29 "
        "(hex 02 03 05 07 0B 0D 11 13 17 1D).",
    ),
    _example(
        "Intermediate", "linear_search", "Linear Search",
        "Search an unsorted six-byte array for 9, returning its zero-based index.",
        "Compile, load, and run. The program writes [5, 8, 1, 9, 3, 7] at byte addresses 0x0400-0x0405. "
        "Edit key = 9 to try another search; preloaded values are overwritten.",
        "The CPU halts with R0 = 3. A missing key returns -1, shown as 0xFFFF in the register view.",
    ),
    _example(
        "Intermediate", "reverse_array", "Reverse Array",
        "Reverse all 256 bytes at 0x0400-0x04FF in place using two indices and swaps.",
        "Load the compiled program first, then fill byte addresses 0x0400-0x04FF with input before running. "
        "For a clear demonstration, use ascending bytes 00 through FF. The program does not seed this array.",
        "R0 = 0. The 256 input bytes appear in reverse order; input 00..FF becomes FF..00.",
    ),
    _example(
        "Advanced", "bubble_sort", "Bubble Sort",
        "Sort the 256-byte data area in ascending unsigned order using adjacent swaps (stable bubble sort).",
        "Load first, then supply 256 input bytes at 0x0400-0x04FF before running. "
        "The source does not initialise the array. Allow enough execution time for nested loops over all 256 values.",
        "R0 = 0. Bytes 0x0400-0x04FF contain the original values sorted in ascending order.",
    ),
    _example(
        "Advanced", "insertion_sort", "Insertion Sort",
        "Sort the 256-byte data area in ascending unsigned order by inserting each key into a sorted prefix (stable).",
        "Load first, then supply 256 input bytes at 0x0400-0x04FF before running. "
        "Try the same data as Bubble Sort to compare execution behavior; the source does not initialise the array.",
        "R0 = 0. Bytes 0x0400-0x04FF contain the original values sorted in ascending order.",
    ),
    _example(
        "Advanced", "selection_sort", "Selection Sort",
        "Sort the 256-byte data area by repeatedly selecting the smallest remaining unsigned byte.",
        "Load first, then supply 256 input bytes at 0x0400-0x04FF before running. "
        "Try the same data as the other sorts. This algorithm uses fewer swaps and is not stable.",
        "R0 = 0. Bytes 0x0400-0x04FF contain the original values sorted in ascending order.",
    ),
    _example(
        "Advanced", "binary_search", "Binary Search",
        "Search a sorted array using a shrinking half-open range and a midpoint calculated with a shift.",
        "Compile, load, and run. The program writes [1, 3, 5, 7, 9, 11] at 0x0400-0x0405 and searches for 7. "
        "To experiment, edit the final search argument; preloaded array values are overwritten.",
        "The CPU halts with R0 = 3. A missing key returns -1 (0xFFFF).",
    ),
    _example(
        "Advanced", "factorial_recursive", "Factorial Recursive",
        "Compute 5! with recursive calls; each call has its own stack frame and returns a partial product.",
        "Compile, load, and run. No input memory is needed. Compare the calls and stack use with Basic / Factorial. "
        "Use small inputs because both the 16-bit result and available stack space are limited.",
        "The CPU halts with R0 = 120 (0x0078).",
    ),
    _example(
        "Advanced", "matrix_multiplication", "Matrix Multiplication",
        "Multiply two 3 x 3 matrices with three nested loops, byte inputs, and 16-bit result words.",
        "Compile, load, and run. The program seeds row-major A = [1..9] at 0x0400-0x0408 and "
        "B = [9..1] at 0x0420-0x0428. Read nine big-endian words from 0x0440-0x0451 after halt.",
        "R0 = 30. Result rows are [30, 24, 18], [84, 69, 54], [138, 114, 90].",
    ),
    _example(
        "Display", "draw_line", "Draw Line",
        "Draw a Turtle / LOGO-style path with twelve possible headings and three fractional coordinate bits.",
        "Compile, load, and run, then open Display. The turtle starts at pixel (8, 3), moves 40, 24, 24, "
        "and 18 steps, and turns by 120, 120, and 60 degrees between the segments.",
        "R0 = 0. A four-segment line drawing remains in the 64 x 64 framebuffer.",
    ),
    _example(
        "Display", "draw_rectangle", "Draw Rectangle",
        "Draw a filled 32 x 14 rectangle by writing four byte-aligned framebuffer columns per row.",
        "Compile, load, and run, then open Display. The program clears the screen and writes the rectangle "
        "with its lower-left corner at (16, 8). Screen row zero is at the bottom.",
        "R0 = 0. Pixels x = 16..47, y = 8..21 are lit; the remaining framebuffer is clear.",
    ),
    _example(
        "Display", "draw_triangle", "Draw Triangle",
        "Draw a smooth filled triangle with 45-degree edges, using edge masks that grow one pixel per row.",
        "Compile, load, and run, then open Display. The program clears the screen and draws rows 43 down "
        "to 20. The apex is 2 pixels wide (x = 31..32); the base is 48 pixels wide (x = 8..55).",
        "R0 = 0. A centred triangle with smooth one-pixel steps remains on the screen.",
    ),
    _example(
        "Display", "draw_checkerboard", "Draw Checkerboard",
        "Fill the whole 64 x 64 screen with an alternating one-pixel checkerboard using direct byte writes.",
        "Compile, load, and run, then open Display. No input is required; every framebuffer byte is assigned.",
        "R0 = 0. Even rows contain eight 0xAA bytes; odd rows contain eight 0x55 bytes.",
    ),
    _example(
        "Display", "draw_spiral", "Draw Spiral",
        "Animate dashed rectangular rings inward, then erase the rings outward, repeating continuously.",
        "Compile, load, run at a few kHz, and open Display. Click the display canvas for keyboard input. "
        "Hold Q to quit; the key is checked after a complete inward/outward animation cycle.",
        "Dashed rings repeatedly fill and clear the screen. A recognised quit request ends the program with R0 = 0.",
    ),
    _example(
        "Display", "bouncing_ball", "Bouncing Ball",
        "Move a single pixel inside a rectangular border, reversing its velocity when it reaches an edge.",
        "Compile, load, run at a few kHz, and open Display. The ball begins at (5, 40). "
        "Click the display canvas and press Q to quit; otherwise the animation continues.",
        "A ball bounces inside the 64 x 64 border. Quitting returns R0 = 0.",
    ),
    _example(
        "Games", "snake", "Snake",
        "Steer a growing snake toward food; the framebuffer doubles as the wall/body collision map.",
        "Compile, load, run at about 2-5 kHz, and click the Display canvas. Use arrow keys or W/A/S/D to steer "
        "and Q to quit. Collect food while avoiding the border and your body; immediate reversal is blocked.",
        "The score is shown above the arena and returned in R0. The snake grows up to 48 cells; "
        "collision or Q ends play and inverts the arena's top border.",
    ),
    _example(
        "Games", "ping_pong", "Ping Pong",
        "Keep a bouncing 2 x 2 ball in play with a single 12-pixel paddle.",
        "Compile, load, run at a few kHz, and click the Display canvas. Move the paddle with Left/Right or A/D. "
        "Press Q to quit. Missing the paddle ends the game.",
        "Each paddle return adds one point. Collision with the open edge or Q stops play; R0 contains the score.",
    ),
    _example(
        "Games", "flappy_bird", "Flappy Bird",
        "Guide a small bird through moving pipe gaps with gravity and an edge-triggered flap input.",
        "Compile, load, run at a few kHz, and click the Display canvas. Tap Up or W to flap, releasing between taps; "
        "holding the key does not repeat the flap. Press Q to quit.",
        "The bird and six-pixel-wide pipes animate. Hitting a pipe or a vertical screen limit ends play. "
        "R0 returns the score, incremented whenever a pipe wraps to the right edge.",
    ),
    _example(
        "Games", "racing", "Racing",
        "Avoid two approaching cars on a two-lane road; sprites are written directly to the framebuffer.",
        "Compile, load, run at a few kHz, and click the Display canvas. Select the left lane with Left/A "
        "or the right lane with Right/D. Press Q to quit; a collision ends the game.",
        "A road and three cars are drawn. R0 returns the score, increased after each completed safe update.",
    ),
)


def load_example_groups() -> dict[str, tuple[Example, ...]]:
    """Return the complete library in teaching order, keyed by visible category.

    A new dictionary is returned per call; immutable entries and tuples can be
    shared safely by the compiler panel and validation tools.
    """
    return {
        category: tuple(example for example in EXAMPLES if example.category == category)
        for category in EXAMPLE_CATEGORIES
    }
