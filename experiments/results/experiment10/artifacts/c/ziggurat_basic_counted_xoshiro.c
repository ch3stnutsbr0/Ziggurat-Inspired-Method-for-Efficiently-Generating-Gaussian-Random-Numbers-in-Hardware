#define ZT_COUNTED_BUILD 1
#define ZT_XOSHIRO_BUILD 1
#define zb_init zb_init_counted_xoshiro
#define zb_gaussian zb_gaussian_counted_xoshiro
#define zb_get_counters zb_get_counters_counted_xoshiro
#define zb_get_prng_profile zb_get_prng_profile_counted_xoshiro
#include "ziggurat_basic.c"
uint64_t zb_uniform_calls_counted_xoshiro(void){uint64_t result=uniform_calls;uniform_calls=0;return result;}
