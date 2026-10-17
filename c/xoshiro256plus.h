#ifndef XOSHIRO256PLUS_H
#define XOSHIRO256PLUS_H
#include <stdint.h>
/* Blackman/Vigna xoshiro256+ 1.0 (public domain):
 * https://prng.di.unimi.it/xoshiro256plus.c
 * Seed before use; SplitMix64 initialization guarantees a nonzero state.
 * Inline stepping avoids a call for each uniform in Gaussian hot paths. */
typedef struct { uint64_t s[4]; } xoshiro256plus_rng;
void xoshiro256plus_seed(xoshiro256plus_rng *r, uint64_t seed);
static inline uint64_t xoshiro256plus_next(xoshiro256plus_rng *r) {
#ifdef ZT_TEST_PRNG_STEPS
    extern uint64_t zt_test_prng_steps;
    ++zt_test_prng_steps;
#endif
    const uint64_t result = r->s[0] + r->s[3];
    const uint64_t t = r->s[1] << 17;
    r->s[2] ^= r->s[0];
    r->s[3] ^= r->s[1];
    r->s[1] ^= r->s[2];
    r->s[0] ^= r->s[3];
    r->s[2] ^= t;
    r->s[3] = (r->s[3] << 45) | (r->s[3] >> 19);
    return result;
}
static inline double xoshiro256plus_uniform(xoshiro256plus_rng *r) {
    return (double)(xoshiro256plus_next(r) >> 11) * 0x1.0p-53;
}
#endif
