// Stable insertion sort for the emulator's 256-byte data area.
// Input/output contract: bytes 0x0400..0x04ff are sorted in place.
// Load or edit that memory before running this program.

#define ARRAY ((volatile unsigned char *)0x0400)
#define COUNT 256

int main(void) {
  for (unsigned i = 1; i < COUNT; i++) {
    unsigned char key = ARRAY[i];
    unsigned j = i;

    while (j != 0 && ARRAY[j - 1] > key) {
      ARRAY[j] = ARRAY[j - 1];
      j--;
    }
    ARRAY[j] = key;
  }
  return 0;
}
