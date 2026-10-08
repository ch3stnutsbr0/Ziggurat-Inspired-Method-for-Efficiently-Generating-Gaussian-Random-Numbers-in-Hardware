#include "ziggurat_basic.h"
#include "pcg_rng.h"
#include "gaussian_constants.h"
#include <math.h>
#include <string.h>
#define ZB_MAX_LAYERS 256
/* Derived by solving the recurrence documented in README.md. */
typedef struct { unsigned n; double r; } ziggurat_config;
static const ziggurat_config configurations[] = {
    {8,   2.3383716982472524},
    {16,  2.6755367657376140},
    {32,  2.9613001212640190},
    {64,  3.2136576271588960},
    {128, 3.442619855899}, /* Preserve the original rounded reference value. */
    {256, 3.6541528853610088}
};
static unsigned nlayer;
static double cutoff, x[ZB_MAX_LAYERS], y[ZB_MAX_LAYERS];
static double rectangle_probability;
static pcg_rng rng;
static zt_counters counts;
#if ZT_ENABLE_COUNTERS
#define COUNT(field) (++counts.field)
#else
#define COUNT(field) ((void)0)
#endif
static double uniform(void) { return pcg_uniform(&rng); }
/* Check the actual recurrence before permitting peak-rounding correction.
 * The original 128-layer R is truncated and has a larger known residual.
 * No interior layer is clamped; invalid configurations disable sampling. */
static int build_tables(unsigned n, double r) {
    const double peak_tolerance = n==128 ? 1e-10 : 2e-12;
    nlayer=0;
    if(n<2 || n>ZB_MAX_LAYERS || !isfinite(r) || r<=0) return 0;
    double tail=sqrt(ZT_PI/2.0)*erfc(r/sqrt(2.0));
    double rect=r*exp(-r*r/2.0), area=rect+tail;
    if(!isfinite(area) || tail<=0 || rect<=0) return 0;
    rectangle_probability=rect/area;
    if(!(rectangle_probability>0 && rectangle_probability<1)) return 0;
    x[0]=r; y[0]=exp(-r*r/2.0);
    for(unsigned i=1;i<n;i++) {
        double height=y[i-1]+area/x[i-1];
        if(!isfinite(height) || height<=y[i-1]) return 0;
        if(i==n-1) {
            if(fabs(height-1.0)>peak_tolerance) return 0;
            if(height>1.0) height=1.0; /* Verified final rounding only. */
        } else if(height>=1.0) return 0;
        y[i]=height;
        x[i]=sqrt(-2.0*log(y[i]));
        if(!isfinite(x[i]) || x[i]<0 || x[i]>=x[i-1]) return 0;
        if(fabs(x[i-1]*(y[i]-y[i-1])-area)>area*1e-10) return 0;
    }
    cutoff=r; nlayer=n;
    return 1;
}
int zb_init(uint64_t seed, unsigned n) {
    nlayer=0;
    memset(&counts,0,sizeof counts);
    for(unsigned i=0;i<sizeof configurations/sizeof configurations[0];i++) {
        if(configurations[i].n==n) {
            if(!build_tables(n,configurations[i].r)) return 0;
            pcg_seed(&rng,seed);
            return 1;
        }
    }
    return 0;
}
double zb_gaussian(void) {
    if(!nlayer) return NAN;
    double magnitude;
    COUNT(total_samples);
    for(;;) {
        unsigned layer=(unsigned)(nlayer*uniform());
        if(layer==0) {
            if(uniform()<rectangle_probability) {
                magnitude=cutoff*uniform(); COUNT(rectangle_acceptances);
            } else {
                COUNT(tail_region_hits);
                for(;;) {
                    /* Open-at-zero uniforms avoid log(0); same distribution. */
                    double xt=-log(1.0-uniform())/cutoff;
                    double yt=-log(1.0-uniform());
                    COUNT(rejection_region_tests);
                    if(2*yt>xt*xt) { magnitude=cutoff+xt; break; }
                    COUNT(rejected_candidates); COUNT(retries);
                }
            }
            break;
        }
        if(layer==nlayer-1) { COUNT(head_region_hits); }
        double candidate=x[layer-1]*uniform();
        if(candidate<=x[layer]) {
            magnitude=candidate; COUNT(rectangle_acceptances); break;
        }
        /* Boundary strip: accept precisely under the Gaussian curve. */
        COUNT(rejection_region_tests);
        double height=y[layer-1]+(y[layer]-y[layer-1])*uniform();
        if(height<=exp(-candidate*candidate/2.0)) { magnitude=candidate; break; }
        /* Rejection restarts layer selection, as in the MATLAB source. */
        COUNT(rejected_candidates); COUNT(retries);
    }
    return uniform()<0.5?-magnitude:magnitude;
}
void zb_get_counters(zt_counters *out) { if(out)*out=counts; }
