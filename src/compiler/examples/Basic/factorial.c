/* Compute 6! iteratively. The result is 720. */
int main(void) {
  int factor = 6;
  int result = 1;

  while (factor != 0) {
    result *= factor;
    factor--;
  }

  return result;
}
