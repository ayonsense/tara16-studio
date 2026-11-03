/* Test 17 for primality by trial division. The result is 1 (prime). */
static int divides(unsigned value, unsigned divisor) {
  while (value >= divisor)
    value -= divisor;
  return value == 0;
}

int main(void) {
  unsigned value = 17;
  unsigned divisor;

  if (value < 2)
    return 0;
  for (divisor = 2; divisor < value; divisor++)
    if (divides(value, divisor))
      return 0;

  return 1;
}
