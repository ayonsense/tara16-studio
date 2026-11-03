// fib.c -- the smallest useful TARA16 C program.
// Compile:   ../tara16-cc fib.c --run        (prints main()'s return value)
// In TARA Studio: open fib.tara, Load, Run; the answer is in R0 when it halts.
int fib(int n) {
  return n < 2 ? n : fib(n - 1) + fib(n - 2);
}

int main() {
  return fib(12);     // 144 = 0x0090
}
