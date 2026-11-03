// display_demo.c -- TARA16 framebuffer demo: a frame, a diagonal, and the
// number of primes below 1000 drawn with the 3x5 digit font.
//   ../tara16-cc display_demo.c --display      (text rendering of the screen)
// or open display_demo.tara in TARA Studio and look at the Display tab.
#include <tara16.h>

// count primes below n by trial division (uses the runtime divider)
int count_primes(int n) {
  int count = 0;
  for (int p = 2; p < n; p++) {
    int prime = 1;
    for (int d = 2; d * d <= p; d++)
      if (p % d == 0) {
        prime = 0;
        break;
      }
    count += prime;
  }
  return count;
}

int main() {
  cls();
  rect(0, 0, 63, 63);                 // screen border
  for (unsigned i = 4; i < 60; i++)   // a diagonal
    pset(i, i);
  int n = count_primes(1000);         // 168
  draw_num(40, 50, n);
  return n;
}
