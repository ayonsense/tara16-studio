// snake.c -- the classic game in C for TARA16 (compare with the hand-written
// Games/snake.tara). Steer with the arrow keys / WASD in TARA Studio's
// Display tab (or the Basys 3 buttons); QUIT (bit 4) ends the game.
//
//   ../tara16-cc snake.c            -> snake.tara : open in TARA Studio, Load,
//                                     Run at ~2-5 kHz, click the Display tab
//
// The framebuffer doubles as the collision map: a lit pixel ahead of the
// head is either food (we know where it is) or death.
#include <tara16.h>

#define MAXLEN 48
#define TOP 55                      // playfield rows 1..TOP-1; score above

unsigned char bx[MAXLEN], by[MAXLEN];   // body ring buffer
unsigned head, len;
unsigned fx, fy;                    // food
unsigned score;

void place_food(void) {
  do {
    fx = 2 + (rand16() & 31) + (rand16() & 15) + (rand16() & 7);   // 2..55
    fy = 2 + (rand16() & 31) + (rand16() & 15);                     // 2..48
  } while (pget(fx, fy));
  pset(fx, fy);
}

void show_score(void) {
  draw_num(60, 62, score);
}

int main() {
  cls();
  rect(0, 0, 63, TOP);                // arena wall
  show_score();

  unsigned x = 10, y = 20;
  int dx = 1, dy = 0;
  head = 0;
  len = 1;
  bx[0] = x;
  by[0] = y;
  pset(x, y);
  place_food();

  for (;;) {
    int k = keys();
    if (k & KEY_QUIT)
      break;
    if ((k & KEY_UP) && dy == 0)    { dx = 0; dy = 1; }
    if ((k & KEY_DOWN) && dy == 0)  { dx = 0; dy = -1; }
    if ((k & KEY_LEFT) && dx == 0)  { dx = -1; dy = 0; }
    if ((k & KEY_RIGHT) && dx == 0) { dx = 1; dy = 0; }

    x += dx;
    y += dy;
    int grow = 0;
    if (x == fx && y == fy) {
      grow = 1;
      score++;
      show_score();
    } else if (pget(x, y)) {
      break;                          // wall or tail: game over
    }

    if (!grow || len == MAXLEN) {     // erase the tail
      unsigned tail = head + MAXLEN + 1 - len;
      if (tail >= MAXLEN)
        tail -= MAXLEN;
      pclr(bx[tail], by[tail]);
    } else {
      len++;
    }
    if (++head == MAXLEN)
      head = 0;
    bx[head] = x;
    by[head] = y;
    pset(x, y);
    if (grow)
      place_food();
    delay(300);
  }
  // game over: invert the arena border as a signal, return the score
  for (unsigned i = 0; i < 64; i++)
    pxor(i, TOP);
  return score;
}
