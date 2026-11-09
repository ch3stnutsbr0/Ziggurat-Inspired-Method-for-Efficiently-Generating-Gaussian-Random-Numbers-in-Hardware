#ifndef ZIGGURAT_PHILOX_H
#define ZIGGURAT_PHILOX_H
#include <stdint.h>
/* Bit-packed samplers on Philox2x64-10 (one call = 128 bits). Same output laws as
 * zt_gaussian()/zb_gaussian(); only the way uniform bits are drawn changes.
 * N must be a power of two (index = top log2 N bits). Return 0 on bad configuration. */
int zt_init_philox(uint64_t seed, unsigned layers, unsigned head, unsigned tail);
double zt_gaussian_philox(void);
/* Earlier variant (wedge takes a second block, 2 x 53-bit uniforms), for comparison. */
int zt_init_philox_2call(uint64_t seed, unsigned layers, unsigned head, unsigned tail);
double zt_gaussian_philox_2call(void);
int zb_init_philox(uint64_t seed, unsigned layers);
double zb_gaussian_philox(void);
#endif
