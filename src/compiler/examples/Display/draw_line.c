// Turtle/LOGO-style line drawing with twelve headings, 30 degrees apart.
// Coordinates use three fractional bits so diagonal steps remain smooth.

#include <tara16.h>

static const int step_x[12] = {8, 7, 4, 0, -4, -7, -8, -7, -4, 0, 4, 7};
static const int step_y[12] = {0, 4, 7, 8, 7, 4, 0, -4, -7, -8, -7, -4};

static int turtle_x;
static int turtle_y;
static unsigned turtle_heading;

static void right(unsigned thirty_degree_steps) {
  turtle_heading += thirty_degree_steps;
  while (turtle_heading >= 12)
    turtle_heading -= 12;
}

static void forward(unsigned pixels) {
  while (pixels--) {
    if (turtle_x >= 0 && turtle_x < SCREEN_W * 8 &&
        turtle_y >= 0 && turtle_y < SCREEN_H * 8)
      pset(turtle_x >> 3, turtle_y >> 3);

    turtle_x += step_x[turtle_heading];
    turtle_y += step_y[turtle_heading];
  }
}

int main(void) {
  cls();
  turtle_x = 8 * 8;
  turtle_y = 3 * 8;
  turtle_heading = 0;

  forward(40);
  right(4);  // RT 120
  forward(24);
  right(4);  // RT 120
  forward(24);
  right(2);  // RT 60
  forward(18);
  return 0;
}
