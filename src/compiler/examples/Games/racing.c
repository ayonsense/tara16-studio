// Two-lane avoidance racing for the TARA16 64x64 display.
// Change lanes with LEFT/RIGHT (A/D); QUIT (bit 4) ends the game.
#include <tara16.h>

static const unsigned char car_shape[8] = {
  0xFF, 0xDB, 0x7E, 0x3C, 0x7E, 0x18, 0x3C, 0x18
};

void draw_scene(void) {
  for (int y = 0; y < 64; y++) {
    volatile unsigned char *row = TARA_FB + (y << 3);
    row[0] = (y & 2) ? 0x33 : 0xCC;
    row[1] = 0x80;
    row[2] = 0;
    row[3] = (y & 8) ? 0x01 : 0;
    row[4] = (y & 8) ? 0x80 : 0;
    row[5] = 0;
    row[6] = 0x01;
    row[7] = (y & 2) ? 0xCC : 0x33;
  }
}

void draw_car(int lane, int y, int downward, int on) {
  int col = lane ? 5 : 2;
  for (int r = 0; r < 8; r++) {
    unsigned char bits = on ? car_shape[downward ? 7 - r : r] : 0;
    TARA_FB[((y + r) << 3) + col] = bits;
  }
}

int move_enemy(int *lane, int *y, int player) {
  draw_car(*lane, *y, 1, 0);
  *y -= 2;
  if (*lane == player && *y < 12) return 1;
  if (*y <= 0) {
    *lane = 1 - *lane;
    *y = 56;
  }
  draw_car(*lane, *y, 1, 1);
  return 0;
}

int main(void) {
  int player = 0;
  int lane1 = 0, y1 = 56;
  int lane2 = 1, y2 = 34;
  unsigned score = 0;
  draw_scene();
  draw_car(player, 4, 0, 1);
  draw_car(lane1, y1, 1, 1);
  draw_car(lane2, y2, 1, 1);

  for (;;) {
    int k = keys();
    if (k & KEY_QUIT) break;
    if ((k & KEY_LEFT) && player != 0) {
      draw_car(player, 4, 0, 0);
      player = 0;
      draw_car(player, 4, 0, 1);
    } else if ((k & KEY_RIGHT) && player != 1) {
      draw_car(player, 4, 0, 0);
      player = 1;
      draw_car(player, 4, 0, 1);
    }

    if (move_enemy(&lane1, &y1, player)) break;
    if (move_enemy(&lane2, &y2, player)) break;
    score++;
    delay(300);
  }
  return score;
}
