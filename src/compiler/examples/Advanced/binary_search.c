// Binary search on a sorted byte array.
// The demo mirrors the TARA Studio example: it searches for 7 in
// [1, 3, 5, 7, 9, 11] stored at byte address 0x0400.

#define ARRAY ((volatile unsigned char *)0x0400)

static int binary_search(volatile unsigned char *a, unsigned count,
                         unsigned key) {
  unsigned low = 0;
  unsigned high = count;

  while (low < high) {
    unsigned mid = low + ((high - low) >> 1);
    unsigned value = a[mid];

    if (value == key)
      return mid;
    if (value < key)
      low = mid + 1;
    else
      high = mid;
  }
  return -1;
}

int main(void) {
  ARRAY[0] = 1;
  ARRAY[1] = 3;
  ARRAY[2] = 5;
  ARRAY[3] = 7;
  ARRAY[4] = 9;
  ARRAY[5] = 11;

  return binary_search(ARRAY, 6, 7); // 3
}
