// Animate dashed rectangular rings inward, then erase them outward.

#include <tara16.h>

static void plot(int x, int y, int color) {
  if (color)
    pset(x, y);
  else
    pclr(x, y);
}

static void draw_ring(int layer, int color) {
  int high = 63 - layer;

  for (int x = layer; x <= high; x += 2) {
    plot(x, layer, color);
    plot(x, high, color);
  }
  for (int y = layer + 2; y < high; y += 2) {
    plot(layer, y, color);
    plot(high, y, color);
  }
  delay(30);
}

int main(void) {
  cls();
  for (;;) {
    for (int layer = 0; layer < 32; layer++)
      draw_ring(layer, 1);
    for (int layer = 31; layer >= 0; layer--)
      draw_ring(layer, 0);

    if (keys() & KEY_QUIT)
      break;
  }
  return 0;
}
