// Stable bubble sort for the emulator's 256-byte data area.
// Input/output contract: bytes 0x0400..0x04ff are sorted in place.
// Load or edit that memory before running this program.

#define ARRAY ((volatile unsigned char *)0x0400)
#define COUNT 256

int main(void) {
  for (unsigned last = COUNT - 1; last != 0; last--) {
    for (unsigned i = 0; i < last; i++) {
      unsigned char left = ARRAY[i];
      unsigned char right = ARRAY[i + 1];
      if (left > right) {
        ARRAY[i] = right;
        ARRAY[i + 1] = left;
      }
    }
  }
  return 0;
}
