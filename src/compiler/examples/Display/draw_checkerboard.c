// Paint a one-pixel checkerboard over the whole 64x64 framebuffer.

#include <tara16.h>

int main(void) {
  for (unsigned y = 0; y < SCREEN_H; y++) {
    unsigned char pattern = (y & 1) ? 0x55 : 0xaa;
    for (unsigned column = 0; column < 8; column++)
      TARA_FB[(y << 3) + column] = pattern;
  }
  return 0;
}
