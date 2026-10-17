#ifndef PRNG_H
#define PRNG_H
#include "pcg_rng.h"
#include "xoshiro256plus.h"
typedef enum { PRNG_PCG32 = 0, PRNG_XOSHIRO256PLUS = 1 } prng_type;
/* Return 0 for an unsupported name; do not silently change the stream. */
int prng_parse(const char *name, prng_type *type);
const char *prng_name(prng_type type);
/* Compile-time uniform adapter: no branch or pointer dispatch per draw. */
#ifdef ZT_XOSHIRO_BUILD
typedef xoshiro256plus_rng sampler_rng;
#define sampler_seed xoshiro256plus_seed
#define sampler_uniform xoshiro256plus_uniform
#else
typedef pcg_rng sampler_rng;
#define sampler_seed pcg_seed
#define sampler_uniform pcg_uniform
#endif
#endif
