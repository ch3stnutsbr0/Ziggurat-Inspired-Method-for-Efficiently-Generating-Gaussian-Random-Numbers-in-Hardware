/* Compile the same Gaussian implementation with counted PRNG operations. */
#define ZT_PROFILE_BUILD 1
#define zb_init zb_init_profiled
#define zb_gaussian zb_gaussian_profiled
#define zb_get_counters zb_get_counters_profiled
#define zb_get_prng_profile zb_get_prng_profile_profiled
#include "ziggurat_basic.c"
