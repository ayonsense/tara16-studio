/* Count the set bits in 0xB3B5. The result is 10. */
int main(void) {
  unsigned value = 0xB3B5u;
  int count = 0;

  while (value != 0) {
    count += value & 1u;
    value >>= 1;
  }

  return count;
}
