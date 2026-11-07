// Draw a smooth filled triangle: 24 rows tall, 48-pixel base, apex at the top.
// Each row is one pixel wider on both sides, so the edges are 45-degree lines.
// Only the two edge bytes of a row are partly lit; the bytes between are 0xff.

#include <tara16.h>

int main(void) {
  cls();
  unsigned left = (43 << 3) + 3;  // byte of the apex's left pixel (x = 31, y = 43)
  unsigned right = left + 1;      // byte of its right pixel (x = 32)
  unsigned left_mask = 0x01;      // x = 31 is the last pixel of its byte
  unsigned right_mask = 0x80;     // x = 32 is the first pixel of its byte

  for (unsigned row = 0; row < 24; row++) {
    TARA_FB[left] = left_mask;
    for (unsigned column = left + 1; column < right; column++)
      TARA_FB[column] = 0xff;
    TARA_FB[right] = right_mask;

    left -= 8;  // next row down the screen
    right -= 8;

    // Widen each edge by one pixel. A full edge byte moves the edge out a byte.
    if (left_mask == 0xff) {
      left--;
      left_mask = 0x01;
    } else {
      left_mask = (left_mask << 1) | 1;
    }
    if (right_mask == 0xff) {
      right++;
      right_mask = 0x80;
    } else {
      right_mask = (right_mask >> 1) | 0x80;
    }
  }
  return 0;
}
