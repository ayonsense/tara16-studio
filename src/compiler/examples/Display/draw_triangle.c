// Draw the catalog's filled 24-row triangle using byte-wide blocks.

#include <tara16.h>

int main(void) {
  cls();
  for (unsigned row = 0; row < 24; row++) {
    unsigned width = 1 + (row >> 2);
    unsigned first_column = 4 - (width >> 1);

    for (unsigned column = 0; column < width; column++)
      TARA_FB[((8 + row) << 3) + first_column + column] = 0xff;
  }
  return 0;
}
