/* Specialize the same sampling code; only the uniform source changes. */
#define ZT_XOSHIRO_BUILD 1
#define zt_init zt_init_xoshiro256plus
#define zt_gaussian zt_gaussian_xoshiro256plus
#define zt_get_counters zt_get_counters_xoshiro256plus
#define zt_reset_counters zt_reset_counters_xoshiro256plus
#define zt_get_prng_profile zt_get_prng_profile_xoshiro256plus
#define zt_layers zt_layers_xoshiro256plus
#define zt_table_x zt_table_x_xoshiro256plus
#define zt_table_y zt_table_y_xoshiro256plus
#include "ziggurat_trapezoid.c"
