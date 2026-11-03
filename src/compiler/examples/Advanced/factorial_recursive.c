// Recursive factorial: each call gets its own stack frame.

static int factorial(int n) {
  if (n <= 1)
    return 1;
  return n * factorial(n - 1);
}

int main(void) {
  return factorial(5); // 120
}
