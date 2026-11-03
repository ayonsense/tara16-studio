/* Compute F(10) with the classic two-value iteration. The result is 55. */
int main(void) {
  int a = 0;
  int b = 1;
  int count = 10;

  while (count != 0) {
    int next = a + b;
    a = b;
    b = next;
    count--;
  }

  return a;
}
