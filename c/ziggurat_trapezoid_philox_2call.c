/* Earlier Philox variant for comparison: the wedge draws a second block (two 53-bit uniforms).
 * Same source as ziggurat_trapezoid_philox.c; every external name gets a _2call / philox2_ suffix. */
#define ZT_PHILOX_WEDGE_SECOND_CALL 1
#define zt_init_philox zt_init_philox_2call
#define zt_gaussian_philox zt_gaussian_philox_2call
#define zt_init_tables_philox_ zt_init_tables_philox2_
#define zt_gaussian_reference_philox_ zt_gaussian_reference_philox2_
#define zt_get_counters_philox_ zt_get_counters_philox2_
#define zt_reset_counters_philox_ zt_reset_counters_philox2_
#define zt_get_prng_profile_philox_ zt_get_prng_profile_philox2_
#define zt_layers_philox_ zt_layers_philox2_
#define zt_table_x_philox_ zt_table_x_philox2_
#define zt_table_y_philox_ zt_table_y_philox2_
#include "ziggurat_trapezoid_philox.c"
