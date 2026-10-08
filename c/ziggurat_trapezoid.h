#ifndef ZIGGURAT_TRAPEZOID_H
#define ZIGGURAT_TRAPEZOID_H

#include <stdint.h>

#ifndef ZT_ENABLE_COUNTERS
#define ZT_ENABLE_COUNTERS 0
#endif

typedef struct {
    uint64_t total_samples;
    uint64_t rectangle_acceptances;
    uint64_t triangle_acceptances;
    uint64_t rejection_region_tests;
    uint64_t rejected_candidates;
    uint64_t retries;
    uint64_t head_region_hits;
    uint64_t tail_region_hits;
    uint64_t head_refined_paths;
    uint64_t tail_refined_paths;
} zt_counters;

/* Set seed and parameters before sampling. Zero refinement is permitted. */
int zt_init(uint64_t seed, unsigned layers, unsigned head_levels,
            unsigned tail_levels);
double zt_gaussian(void);
void zt_get_counters(zt_counters *out);
void zt_reset_counters(void);
unsigned zt_layers(void);
double zt_table_x(unsigned table, unsigned boundary); /* main=0, head 1..H, tail H+1.. */
double zt_table_y(unsigned table, unsigned boundary);

#endif
