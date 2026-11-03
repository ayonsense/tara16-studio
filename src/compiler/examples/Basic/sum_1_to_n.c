/* Add the integers from 1 through 10. The result is 55. */
int main(void) {
  int value = 10;
  int sum = 0;

  while (value != 0) {
    sum += value;
    value--;
  }

  return sum;
}
