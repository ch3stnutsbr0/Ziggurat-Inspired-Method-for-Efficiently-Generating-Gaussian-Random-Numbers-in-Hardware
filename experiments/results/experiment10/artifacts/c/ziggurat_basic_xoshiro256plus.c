/* Specialize the same sampling code; only the uniform source changes. */
#define ZT_XOSHIRO_BUILD 1
#define zb_init zb_init_xoshiro256plus
#define zb_gaussian zb_gaussian_xoshiro256plus
#define zb_get_counters zb_get_counters_xoshiro256plus
#define zb_get_prng_profile zb_get_prng_profile_xoshiro256plus
#include "ziggurat_basic.c"
