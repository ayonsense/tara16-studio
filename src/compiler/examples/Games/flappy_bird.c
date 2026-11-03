// Flappy Bird for the TARA16 64x64 display.
// Tap UP/W to flap; QUIT (bit 4) ends the game.
#include <tara16.h>

#define BIRD_X 10
#define PIPE_W 6
#define GAP_H 20

int bird_y, bird_vy, pipe_x, gap_lo;
unsigned score;

void draw_bird(int y, int on) {
  for (int r = 0; r < 2; r++)
    for (int x = BIRD_X; x < BIRD_X + 4; x++) {
      if (on) pset(x, y + r); else pclr(x, y + r);
    }
}

void pipe_column(int x, int on) {
  for (int y = 1; y < 64; y++)
    if (y < gap_lo || y >= gap_lo + GAP_H) {
      if (on) pset(x, y); else pclr(x, y);
    }
}

int main(void) {
  int flap = 0;
  cls();
  hline(0, 63, 0);
  bird_y = 31;
  bird_vy = 0;
  pipe_x = 58;
  gap_lo = 20;
  for (int i = 0; i < PIPE_W; i++) pipe_column(pipe_x + i, 1);
  draw_bird(bird_y, 1);

  for (;;) {
    int k = keys();
    if (k & KEY_QUIT) break;
    if ((k & KEY_UP) && !flap) bird_vy = 3;
    flap = (k & KEY_UP) != 0;

    draw_bird(bird_y, 0);
    bird_y += bird_vy;
    bird_vy--;
    if (bird_vy < -2) bird_vy = -2;

    if (pipe_x == 0) {
      for (int i = 0; i < PIPE_W; i++) pipe_column(i, 0);
      pipe_x = 58;
      gap_lo = 8 + ((gap_lo + 17) & 31);
      for (int i = 0; i < PIPE_W; i++) pipe_column(pipe_x + i, 1);
      score++;
    } else {
      pipe_column(pipe_x + PIPE_W - 1, 0);
      pipe_x--;
      pipe_column(pipe_x, 1);
    }

    if (bird_y < 1 || bird_y > 61) break;
    if (pipe_x <= BIRD_X + 3 && pipe_x + PIPE_W > BIRD_X &&
        (bird_y < gap_lo || bird_y + 1 >= gap_lo + GAP_H)) break;

    draw_bird(bird_y, 1);
    delay(180);
  }
  return score;
}
