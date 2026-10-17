/* Compile the same Gaussian implementation with counted PRNG operations. */
#define ZT_PROFILE_BUILD 1
#define zt_init zt_init_profiled
#define zt_gaussian zt_gaussian_profiled
#define zt_get_counters zt_get_counters_profiled
#define zt_reset_counters zt_reset_counters_profiled
#define zt_get_prng_profile zt_get_prng_profile_profiled
#define zt_layers zt_layers_profiled
#define zt_table_x zt_table_x_profiled
#define zt_table_y zt_table_y_profiled
#include "ziggurat_trapezoid.c"
