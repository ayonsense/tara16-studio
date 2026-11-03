// 3x3 matrix multiplication using the same fixed layout as TARA Studio:
// A: nine bytes at 0x0400, B: nine bytes at 0x0420,
// C: nine 16-bit words at 0x0440.

static const unsigned char a_seed[9] = {
  1, 2, 3,
  4, 5, 6,
  7, 8, 9,
};

static const unsigned char b_seed[9] = {
  9, 8, 7,
  6, 5, 4,
  3, 2, 1,
};

int main(void) {
  volatile unsigned char *a = (volatile unsigned char *)0x0400;
  volatile unsigned char *b = (volatile unsigned char *)0x0420;
  volatile unsigned *c = (volatile unsigned *)0x0440;

  for (unsigned i = 0; i < 9; i++) {
    a[i] = a_seed[i];
    b[i] = b_seed[i];
  }

  for (unsigned row = 0; row < 3; row++) {
    for (unsigned column = 0; column < 3; column++) {
      unsigned sum = 0;
      for (unsigned k = 0; k < 3; k++)
        sum += a[row * 3 + k] * b[k * 3 + column];
      c[row * 3 + column] = sum;
    }
  }

  return c[0]; // 30; the full matrix is at 0x0440..0x0451
}
