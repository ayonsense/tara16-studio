// tara16.h -- TARA16 hardware for C programs (header-only; include once).
//
// Memory map (2 KB, byte addressed, 16-bit words are big-endian):
//   0x000 ...        your program: code, then globals (crt0 is at 0x000)
//   ... 0x5FD        the stack grows down from 0x5FE
//   0x5FF            game inputs, one-hot (read with TARA_KEYS / keys())
//   0x600 - 0x7FF    64 x 64 framebuffer, 1 bit per pixel, 8 pixels/byte,
//                    MSB = leftmost pixel, ROW 0 IS AT THE BOTTOM.
//
// Everything here is `static inline` or `static const`: code and tables
// you do not use are dropped by the linker, so including this costs nothing.
#ifndef TARA16_H
#define TARA16_H

#define SCREEN_W 64
#define SCREEN_H 64

#define TARA_FB   ((volatile unsigned char *)0x600)
#define TARA_KEYS (*(volatile unsigned char *)0x5FF)

#define KEY_UP    0x01
#define KEY_DOWN  0x02
#define KEY_LEFT  0x04
#define KEY_RIGHT 0x08
#define KEY_QUIT  0x10

// bit mask for pixel column x & 7 (a table: TARA16 shifts by constants only)
static const unsigned char tara_bit[8] = {0x80, 0x40, 0x20, 0x10,
                                          0x08, 0x04, 0x02, 0x01};

// byte address of pixel (x, y); x, y are unsigned so / and % are shifts
#define TARA_PIX(x, y) TARA_FB[((y) << 3) + ((x) >> 3)]

static inline void pset(unsigned x, unsigned y) { TARA_PIX(x, y) |= tara_bit[x & 7]; }
static inline void pclr(unsigned x, unsigned y) { TARA_PIX(x, y) &= ~tara_bit[x & 7]; }
static inline void pxor(unsigned x, unsigned y) { TARA_PIX(x, y) ^= tara_bit[x & 7]; }
static inline int  pget(unsigned x, unsigned y) { return (TARA_PIX(x, y) & tara_bit[x & 7]) != 0; }

// clear (or fill with a byte pattern) the whole screen
static inline void fill_screen(unsigned char pattern) {
  volatile unsigned char *p = TARA_FB;
  for (int i = 0; i < 512; i++)
    p[i] = pattern;
}
static inline void cls(void) { fill_screen(0); }

// horizontal / vertical lines and rectangles (inclusive corners)
static inline void hline(int x0, int x1, int y) {
  for (int x = x0; x <= x1; x++)
    pset(x, y);
}
static inline void vline(int x, int y0, int y1) {
  for (int y = y0; y <= y1; y++)
    pset(x, y);
}
static inline void rect(int x0, int y0, int x1, int y1) {
  hline(x0, x1, y0);
  hline(x0, x1, y1);
  vline(x0, y0, y1);
  vline(x1, y0, y1);
}

// ---- 3x5 digits: draw_digit / draw_num (numbers for scores) -------------
// Each digit is 15 bits: 5 rows (top first) of 3 pixels (MSB = left).
static const unsigned tara_digits[10] = {
  0x7B6F, 0x2C97, 0x73E7, 0x73CF, 0x5BC9, 0x79CF, 0x79EF, 0x7249, 0x7BEF, 0x7BCF,
};

// (x, y) is the TOP-left corner of the digit (screen row y grows upward).
static inline void draw_digit(int x, int y, unsigned d) {
  unsigned bits = tara_digits[d];
  for (int r = 0; r < 5; r++) {
    for (int c = 0; c < 3; c++) {
      if (bits & 0x4000)
        pset(x + c, y - r);
      else
        pclr(x + c, y - r);
      bits <<= 1;
    }
  }
}

// Right-aligned decimal number whose rightmost digit starts at column x.
static inline void draw_num(int x, int y, unsigned n) {
  do {
    draw_digit(x, y, n % 10);
    n /= 10;
    x -= 4;
  } while (n);
}

// ---- input and timing -----------------------------------------------------
static inline int keys(void) { return TARA_KEYS; }

// busy-wait: about 3 instructions per count
static inline void delay(unsigned n) {
  while (n)
    n--;
}

// stop the CPU (main's return also halts, with the value in R0)
static inline void halt(void) { asm("HLT"); }

// tiny 16-bit xorshift pseudo-random generator
static unsigned tara_seed = 0xACE1;
static inline unsigned rand16(void) {
  unsigned x = tara_seed;
  x ^= x << 7;
  x ^= x >> 9;
  x ^= x << 8;
  tara_seed = x;
  return x;
}

#endif
