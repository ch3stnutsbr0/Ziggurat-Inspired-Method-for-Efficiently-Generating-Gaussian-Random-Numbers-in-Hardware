#define ZT_BUFFERED_BUILD 1
#define zt_init zt_init_buffered
#define zt_gaussian zt_gaussian_buffered
#define zt_get_counters zt_get_counters_buffered
#define zt_get_prng_profile zt_get_prng_profile_buffered
#define zt_reset_counters zt_reset_counters_buffered
#define zt_layers zt_layers_buffered
#define zt_table_x zt_table_x_buffered
#define zt_table_y zt_table_y_buffered
#include "ziggurat_trapezoid.c"
void zt_set_buffer(uniform_buffer *b){active_buffer=b;}
