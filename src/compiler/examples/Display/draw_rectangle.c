// Draw the catalog's filled 32x14 rectangle at pixel (16, 8).
// Its edges are byte-aligned, so four framebuffer bytes make each row.

#include <tara16.h>

int main(void) {
  cls();
  for (unsigned y = 8; y < 8 + 14; y++) {
    for (unsigned column = 2; column < 2 + 4; column++)
      TARA_FB[(y << 3) + column] = 0xff;
  }
  return 0;
}
