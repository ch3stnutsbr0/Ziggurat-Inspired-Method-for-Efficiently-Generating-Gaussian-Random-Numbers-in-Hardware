#include "xoshiro256plus.h"
/* SplitMix64 reference: https://prng.di.unimi.it/splitmix64.c */
static uint64_t splitmix64_next(uint64_t *state) {
    uint64_t z = (*state += UINT64_C(0x9e3779b97f4a7c15));
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
}
void xoshiro256plus_seed(xoshiro256plus_rng *r, uint64_t seed) {
    for (unsigned i = 0; i < 4; ++i) r->s[i] = splitmix64_next(&seed);
    /* Defensive guard against the absorbing zero state. SplitMix64's bijective
     * output on four distinct inputs already prevents this for every seed. */
    if (!(r->s[0] | r->s[1] | r->s[2] | r->s[3])) r->s[0] = 1;
}
