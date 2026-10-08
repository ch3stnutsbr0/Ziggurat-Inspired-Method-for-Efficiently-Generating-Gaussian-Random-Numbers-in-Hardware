#ifndef ZIGGURAT_BASIC_H
#define ZIGGURAT_BASIC_H
#include "ziggurat_trapezoid.h"
void zb_init(uint64_t seed);
double zb_gaussian(void);
void zb_get_counters(zt_counters *out);
#endif
