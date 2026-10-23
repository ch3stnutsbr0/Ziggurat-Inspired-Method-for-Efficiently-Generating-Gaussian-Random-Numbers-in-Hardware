#ifndef PCG_RNG_H
#define PCG_RNG_H
#include <stdint.h>
#include <limits.h>
#include <stddef.h>
/* Shared PCG-XSH-RR 64/32 and identical 53-bit uniforms for both algorithms. */
typedef struct {
    uint64_t uniform_calls, pcg32_calls;
    int overflow;
} pcg_profile_counts;
typedef struct {
    pcg_profile_counts initialization, sampling;
    pcg_profile_counts *active;
} pcg_profile;
typedef struct { uint64_t state, inc; } pcg_rng;

static inline void pcg_count(uint64_t *value, pcg_profile_counts *counts) {
    if (*value == UINT64_MAX) counts->overflow=1;
    else ++*value;
}
static inline void pcg_profile_reset(pcg_profile *p) {
    p->initialization=(pcg_profile_counts){0};
    p->sampling=(pcg_profile_counts){0};
    p->active=NULL;
}
static inline void pcg_profile_initialization(pcg_profile *p) { p->active=&p->initialization; }
static inline void pcg_profile_sampling(pcg_profile *p) { p->active=&p->sampling; }

static inline uint32_t pcg_next(pcg_rng *r) {
#ifdef ZT_TEST_PRNG_STEPS
    extern uint64_t zt_test_prng_steps;
    ++zt_test_prng_steps;
#endif
    uint64_t old=r->state;
    r->state=old*6364136223846793005ULL+r->inc;
    uint32_t x=(uint32_t)(((old>>18u)^old)>>27u), rot=(uint32_t)(old>>59u);
    return (x>>rot)|(x<<((-rot)&31));
}

static inline uint32_t pcg_next_profiled(pcg_rng *r,pcg_profile *p) {
    pcg_count(&p->active->pcg32_calls,p->active);
    return pcg_next(r);
}

static inline void pcg_seed(pcg_rng *r,uint64_t seed) {
    r->state=0; r->inc=(seed<<1u)|1u; (void)pcg_next(r);
    r->state+=seed ^ 0x9e3779b97f4a7c15ULL; (void)pcg_next(r);
}
static inline void pcg_seed_profiled(pcg_rng *r,pcg_profile *p,uint64_t seed) {
    r->state=0; r->inc=(seed<<1u)|1u; (void)pcg_next_profiled(r,p);
    r->state+=seed ^ 0x9e3779b97f4a7c15ULL; (void)pcg_next_profiled(r,p);
}

static inline double pcg_uniform(pcg_rng *r) {
    uint32_t a=pcg_next(r)>>5, b=pcg_next(r)>>6;
    return ((double)a*67108864.0+(double)b)/9007199254740992.0;
}
static inline double pcg_uniform_profiled(pcg_rng *r,pcg_profile *p) {
    pcg_count(&p->active->uniform_calls,p->active);
    uint32_t a=pcg_next_profiled(r,p)>>5, b=pcg_next_profiled(r,p)>>6;
    return ((double)a*67108864.0+(double)b)/9007199254740992.0;
}
#endif
