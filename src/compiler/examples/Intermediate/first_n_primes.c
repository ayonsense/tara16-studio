/* Generate the first 10 primes at byte addresses 0x0400..0x0409. */
static int divides(unsigned value, unsigned divisor) {
  while (value >= divisor)
    value -= divisor;
  return value == 0;
}

static int is_prime(unsigned value) {
  unsigned divisor;

  if (value < 2)
    return 0;
  for (divisor = 2; divisor < value; divisor++)
    if (divides(value, divisor))
      return 0;
  return 1;
}

int main(void) {
  volatile unsigned char *output = (volatile unsigned char *)0x0400;
  unsigned candidate = 2;
  int count = 0;

  while (count < 10) {
    if (is_prime(candidate)) {
      output[count] = candidate;
      count++;
    }
    candidate++;
  }

  return count;
}
