/* Count the Collatz steps from 7 to 1. The result is 16. */
int main(void) {
  unsigned value = 7;
  int steps = 0;

  while (value != 1) {
    if (value & 1u)
      value = value + value + value + 1;
    else
      value >>= 1;
    steps++;
  }

  return steps;
}
