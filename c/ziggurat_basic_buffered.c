#define ZT_BUFFERED_BUILD 1
#define zb_init zb_init_buffered
#define zb_gaussian zb_gaussian_buffered
#define zb_get_counters zb_get_counters_buffered
#define zb_get_prng_profile zb_get_prng_profile_buffered
#include "ziggurat_basic.c"
void zb_set_buffer(uniform_buffer *b){active_buffer=b;}
