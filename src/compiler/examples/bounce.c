// bounce.c -- a ball bouncing around the 64x64 screen, forever.
// Open bounce.tara in TARA Studio, Load, Run at a few kHz, Display tab.
// Try: ../tara16-cc bounce.c --display --max 200000
#include <tara16.h>

int main() {
  int x = 5, y = 40, dx = 1, dy = -1;
  cls();
  rect(0, 0, 63, 63);
  for (;;) {
    pset(x, y);            // draw, wait, erase, move
    delay(200);
    pclr(x, y);
    if (x + dx < 1 || x + dx > 62) dx = -dx;
    if (y + dy < 1 || y + dy > 62) dy = -dy;
    x += dx;
    y += dy;
    if (keys() & KEY_QUIT)
      break;
  }
  return 0;
}
