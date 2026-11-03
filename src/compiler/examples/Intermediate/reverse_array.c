/* Reverse the 256 input bytes at 0x0400..0x04FF in place. */
int main(void) {
  volatile unsigned char *values = (volatile unsigned char *)0x0400;
  unsigned lo = 0;
  unsigned hi = 255;

  while (lo < hi) {
    unsigned char saved = values[lo];
    values[lo] = values[hi];
    values[hi] = saved;
    lo++;
    hi--;
  }

  return 0;
}
