// Single-paddle Ping Pong for the TARA16 64x64 display.
// Move with LEFT/RIGHT (A/D); QUIT (bit 4) ends the game.
#include <tara16.h>

#define BAT_W 12

void draw_ball(int x, int y, int on) {
  for (int r = 0; r < 2; r++)
    for (int c = 0; c < 2; c++) {
      if (on) pset(x + c, y + r); else pclr(x + c, y + r);
    }
}

void draw_bat(int x, int on) {
  for (int r = 1; r <= 3; r++)
    for (int c = 0; c < BAT_W; c++) {
      if (on) pset(x + c, r); else pclr(x + c, r);
    }
}

int main(void) {
  int x = 20, y = 30, vx = 1, vy = -1;
  int bat = 26;
  unsigned score = 0;
  cls();
  hline(0, 63, 63);
  vline(0, 0, 63);
  vline(63, 0, 63);
  draw_bat(bat, 1);
  draw_ball(x, y, 1);

  for (;;) {
    int k = keys();
    if (k & KEY_QUIT) break;
    if ((k & KEY_LEFT) && bat > 1) {
      draw_bat(bat, 0); bat--; draw_bat(bat, 1);
    } else if ((k & KEY_RIGHT) && bat < 51) {
      draw_bat(bat, 0); bat++; draw_bat(bat, 1);
    }

    draw_ball(x, y, 0);
    x += vx;
    y += vy;
    if (x <= 1) { x = 1; vx = 1; }
    if (x >= 61) { x = 61; vx = -1; }
    if (y >= 61) { y = 61; vy = -1; }
    if (y <= 4) {
      if (vy < 0 && x + 1 >= bat && x <= bat + BAT_W - 1) {
        y = 4;
        vy = 1;
        score++;
      } else {
        break;
      }
    }
    draw_ball(x, y, 1);
    delay(220);
  }
  return score;
}
