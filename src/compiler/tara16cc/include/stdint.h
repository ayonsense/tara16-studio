#ifndef __STDINT_H
#define __STDINT_H
// TARA16: there is no 32-bit type (no `long`), so only 8/16-bit types exist.
typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef int int16_t;
typedef unsigned int uint16_t;
typedef int intptr_t;
typedef unsigned int uintptr_t;
#define INT8_MIN (-128)
#define INT8_MAX 127
#define UINT8_MAX 255
#define INT16_MIN (-32767 - 1)
#define INT16_MAX 32767
#define UINT16_MAX 65535u
#endif
