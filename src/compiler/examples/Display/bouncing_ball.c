// A ball bouncing around the 64x64 screen forever.
// Run at a few kHz and open the emulator's Display tab.

#include <tara16.h>

int main(void) {
  int x = 5, y = 40, dx = 1, dy = -1;
  cls();
  rect(0, 0, 63, 63);

  for (;;) {
    pset(x, y);
    delay(200);
    pclr(x, y);

    if (x + dx < 1 || x + dx > 62)
      dx = -dx;
    if (y + dy < 1 || y + dy > 62)
      dy = -dy;
    x += dx;
    y += dy;

    if (keys() & KEY_QUIT)
      break;
  }
  return 0;
}
