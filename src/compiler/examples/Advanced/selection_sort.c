// Selection sort for the emulator's 256-byte data area.
// Input/output contract: bytes 0x0400..0x04ff are sorted in place.
// Load or edit that memory before running this program.

#define ARRAY ((volatile unsigned char *)0x0400)
#define COUNT 256

int main(void) {
  for (unsigned i = 0; i < COUNT - 1; i++) {
    unsigned least = i;

    for (unsigned j = i + 1; j < COUNT; j++) {
      if (ARRAY[j] < ARRAY[least])
        least = j;
    }

    if (least != i) {
      unsigned char value = ARRAY[i];
      ARRAY[i] = ARRAY[least];
      ARRAY[least] = value;
    }
  }
  return 0;
}
