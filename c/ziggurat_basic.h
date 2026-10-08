#ifndef ZIGGURAT_BASIC_H
#define ZIGGURAT_BASIC_H
#include "ziggurat_trapezoid.h"
/* Supported N: 8,16,32,64,128,256. Failure disables sampling. */
int zb_init(uint64_t seed, unsigned n);
/* Returns NAN before successful initialization or after a failed init. */
double zb_gaussian(void);
void zb_get_counters(zt_counters *out);
#endif
