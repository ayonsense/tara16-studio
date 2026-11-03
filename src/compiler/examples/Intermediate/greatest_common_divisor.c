/* Find gcd(48, 18) with Euclid's subtraction method. The result is 6. */
int main(void) {
  int a = 48;
  int b = 18;

  while (a != b) {
    if (a > b)
      a -= b;
    else
      b -= a;
  }

  return a;
}
