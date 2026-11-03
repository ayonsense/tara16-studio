/* Find 9 in the unsorted byte array at 0x0400. Its index is 3. */
int main(void) {
  volatile unsigned char *values = (volatile unsigned char *)0x0400;
  unsigned char key = 9;
  int index;

  values[0] = 5;
  values[1] = 8;
  values[2] = 1;
  values[3] = 9;
  values[4] = 3;
  values[5] = 7;

  for (index = 0; index < 6; index++)
    if (values[index] == key)
      return index;

  return -1;
}
