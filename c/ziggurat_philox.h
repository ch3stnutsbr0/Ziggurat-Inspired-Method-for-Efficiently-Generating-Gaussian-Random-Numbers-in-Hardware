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
/* Base case only (no head/tail refinement): exactly one Philox call per sample. */
int zt_init_philox_base(uint64_t seed, unsigned layers);
double zt_gaussian_philox_base(void);
/* Fast path (base case inline) + out-of-line refinement; init with zt_init_philox(). Output is
 * bit-identical to zt_gaussian_philox() for every H and T. */
double zt_gaussian_philox_fast(void);
/* One Philox block per sample for every H and T: descent indices taken from word A
 * ([idx0..idx_L-1][sign][decision: D bits], L = 1 + max(H, T), D = min(53, 63 - k*L)).
 * Same law as zt_gaussian_philox() except the decision is quantised to 2^-D. Init returns 0 if
 * fewer than 20 decision bits remain. _map and _reference evaluate one block (tests). */
int zt_init_philox_1call(uint64_t seed, unsigned layers, unsigned head, unsigned tail);
double zt_gaussian_philox_1call(void);
unsigned zt_philox_1call_decision_bits(unsigned layers, unsigned head, unsigned tail);
double zt_philox_1call_map(uint64_t A, uint64_t B);
double zt_philox_1call_reference(uint64_t A, uint64_t B);
int zb_init_philox(uint64_t seed, unsigned layers);
double zb_gaussian_philox(void);
/* Classical fast path (inner-rectangle case inline, everything else out of line); init with
 * zb_init_philox(). Output is bit-identical to zb_gaussian_philox(). */
double zb_gaussian_philox_fast(void);
#endif
