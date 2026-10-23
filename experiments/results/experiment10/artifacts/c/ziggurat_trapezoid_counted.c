#define ZT_COUNTED_BUILD 1
#define zt_init zt_init_counted
#define zt_gaussian zt_gaussian_counted
#define zt_get_counters zt_get_counters_counted
#define zt_get_prng_profile zt_get_prng_profile_counted
#define zt_reset_counters zt_reset_counters_counted
#define zt_layers zt_layers_counted
#define zt_table_x zt_table_x_counted
#define zt_table_y zt_table_y_counted
#include "ziggurat_trapezoid.c"
uint64_t zt_uniform_calls_counted(void){uint64_t result=uniform_calls;uniform_calls=0;return result;}
