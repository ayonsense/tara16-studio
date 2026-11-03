/* Compute 2^10 by repeated doubling. The result is 1024. */
int main(void) {
  int count = 10;
  int result = 1;

  while (count != 0) {
    result += result;
    count--;
  }

  return result;
}
