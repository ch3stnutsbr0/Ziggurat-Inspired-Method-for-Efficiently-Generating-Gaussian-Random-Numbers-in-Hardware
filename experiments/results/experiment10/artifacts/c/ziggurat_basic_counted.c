#define ZT_COUNTED_BUILD 1
#define zb_init zb_init_counted
#define zb_gaussian zb_gaussian_counted
#define zb_get_counters zb_get_counters_counted
#define zb_get_prng_profile zb_get_prng_profile_counted
#include "ziggurat_basic.c"
uint64_t zb_uniform_calls_counted(void){uint64_t result=uniform_calls;uniform_calls=0;return result;}
