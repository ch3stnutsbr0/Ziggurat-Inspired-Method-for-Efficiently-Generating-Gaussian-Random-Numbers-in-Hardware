#ifndef PHILOX2X64_H
#define PHILOX2X64_H
#include <stdint.h>
/* Philox2x64-10 (Salmon et al., "Parallel random numbers: as easy as 1, 2, 3", SC 2011;
 * Random123). Counter-based: block = 10 rounds of (counter, key). One call returns
 * 128 bits as two independent 64-bit words; every bit is full quality (BigCrush-clean),
 * so words may be split into fields. Known-answer tests: c/tests/test_philox2x64.c. */
typedef struct { uint64_t v[2]; } philox2x64_block;
/* One block per call. Batching several counters per refill was measured slower on a
 * Ryzen 7 2700X: out-of-order execution already overlaps the next block's rounds. */
typedef struct { uint64_t ctr0, ctr1, key; } philox2x64_rng;

__extension__ typedef unsigned __int128 philox_u128;   /* GCC/Clang 64x64->128 multiply */
#define PHILOX2X64_M UINT64_C(0xD2B74407B1CE6E93)
#define PHILOX2X64_W UINT64_C(0x9E3779B97F4A7C15)

#ifdef PHILOX_COUNT_BLOCKS
extern uint64_t philox_blocks;
#endif

/* One round: (c0, c1) <- (hi(M*c0) ^ k_r ^ c1, lo(M*c0)), round key k_r = k + r*W.
 * The 10 rounds are written out: with a loop, GCC -O2 spent an extra register move per
 * round in some callers (measured +11 instructions per Trapezoid sample). */
#define PHILOX2X64_ROUND(r)                                                     \
    do {                                                                        \
        philox_u128 p_ = (philox_u128)PHILOX2X64_M * c0;                        \
        uint64_t hi_ = (uint64_t)(p_ >> 64);                                    \
        c0 = hi_ ^ (k + (uint64_t)(r) * PHILOX2X64_W) ^ c1;                     \
        c1 = (uint64_t)p_;                                                      \
    } while (0)

static inline philox2x64_block philox2x64_bijection(uint64_t c0, uint64_t c1, uint64_t k) {
    PHILOX2X64_ROUND(0); PHILOX2X64_ROUND(1); PHILOX2X64_ROUND(2); PHILOX2X64_ROUND(3);
    PHILOX2X64_ROUND(4); PHILOX2X64_ROUND(5); PHILOX2X64_ROUND(6); PHILOX2X64_ROUND(7);
    PHILOX2X64_ROUND(8); PHILOX2X64_ROUND(9);
    philox2x64_block b = {{c0, c1}};
    return b;
}

/* Next 128-bit block from the generator; the 128-bit counter steps by one. */
static inline philox2x64_block philox2x64_step(philox2x64_rng *r) {
    philox2x64_block b = philox2x64_bijection(r->ctr0, r->ctr1, r->key);
    if (++r->ctr0 == 0) ++r->ctr1;
    return b;
}

/* -DPHILOX_PRECOMPUTED: the samplers read blocks from a buffer filled beforehand with
 * philox2x64_step (same stream, no Philox work in the timed loop). The caller fills
 * philox_buf and resets philox_pos; no bounds check here (guard the buffer's end). */
#ifdef PHILOX_PRECOMPUTED
#include <stddef.h>
extern const philox2x64_block *philox_buf;
extern size_t philox_pos;
#endif

/* Next block used by the samplers. */
static inline philox2x64_block philox2x64_next(philox2x64_rng *r) {
#ifdef PHILOX_COUNT_BLOCKS
    ++philox_blocks;
#endif
#ifdef PHILOX_PRECOMPUTED
    (void)r;
    return philox_buf[philox_pos++];
#else
    return philox2x64_step(r);
#endif
}

/* Key from SplitMix64(seed); counter starts at zero. */
static inline void philox2x64_seed(philox2x64_rng *r, uint64_t seed) {
    uint64_t z = seed + PHILOX2X64_W;
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    r->key = z ^ (z >> 31);
    r->ctr0 = r->ctr1 = 0;
}
#endif
