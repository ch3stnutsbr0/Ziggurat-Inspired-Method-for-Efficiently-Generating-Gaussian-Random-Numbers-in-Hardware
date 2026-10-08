#ifndef PCG_RNG_H
#define PCG_RNG_H
#include <stdint.h>
/* Shared PCG-XSH-RR 64/32 and identical 53-bit uniforms for both algorithms. */
typedef struct { uint64_t state, inc; } pcg_rng;
static inline uint32_t pcg_next(pcg_rng *r) {
    uint64_t old=r->state;
    r->state=old*6364136223846793005ULL+r->inc;
    uint32_t x=(uint32_t)(((old>>18u)^old)>>27u), rot=(uint32_t)(old>>59u);
    return (x>>rot)|(x<<((-rot)&31));
}
static inline void pcg_seed(pcg_rng *r,uint64_t seed) {
    r->state=0; r->inc=(seed<<1u)|1u; (void)pcg_next(r);
    r->state+=seed ^ 0x9e3779b97f4a7c15ULL; (void)pcg_next(r);
}
static inline double pcg_uniform(pcg_rng *r) {
    uint32_t a=pcg_next(r)>>5, b=pcg_next(r)>>6;
    return ((double)a*67108864.0+(double)b)/9007199254740992.0;
}
#endif
