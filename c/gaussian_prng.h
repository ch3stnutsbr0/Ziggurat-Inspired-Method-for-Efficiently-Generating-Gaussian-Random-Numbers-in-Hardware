#ifndef GAUSSIAN_PRNG_H
#define GAUSSIAN_PRNG_H
#include "prng.h"
#include "ziggurat_basic.h"
/* Initialization chooses a separately compiled copy of the existing sampler.
 * The returned Gaussian function is selected once outside the timing loop.
 * Original zb_/zt_ entry points continue to mean PCG32. Each compiled sampler
 * retains the existing singleton state and is not thread safe. */
int zb_init_prng(uint64_t seed, unsigned layers, prng_type type);
int zt_init_prng(uint64_t seed, unsigned layers, unsigned head, unsigned tail, prng_type type);
double (*zb_generator(prng_type type))(void);
double (*zt_generator(prng_type type))(void);
int zb_init_xoshiro256plus(uint64_t seed, unsigned layers);
double zb_gaussian_xoshiro256plus(void);
void zb_get_counters_xoshiro256plus(zt_counters *out);
int zt_init_xoshiro256plus(uint64_t seed, unsigned layers, unsigned head, unsigned tail);
double zt_gaussian_xoshiro256plus(void);
void zt_get_counters_xoshiro256plus(zt_counters *out);
#endif
