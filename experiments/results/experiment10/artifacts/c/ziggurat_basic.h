#ifndef ZIGGURAT_BASIC_H
#define ZIGGURAT_BASIC_H
#include "ziggurat_trapezoid.h"
#include "pcg_rng.h"
/* Supported N: 8,16,32,64,128,256. Failure disables sampling. */
int zb_init(uint64_t seed, unsigned n);
/* Returns NAN before successful initialization or after a failed init. */
double zb_gaussian(void);
void zb_get_counters(zt_counters *out);
void zb_get_prng_profile(pcg_profile_counts *initialization, pcg_profile_counts *sampling);
int zb_init_profiled(uint64_t seed, unsigned n);
double zb_gaussian_profiled(void);
void zb_get_prng_profile_profiled(pcg_profile_counts *initialization, pcg_profile_counts *sampling);
#endif
