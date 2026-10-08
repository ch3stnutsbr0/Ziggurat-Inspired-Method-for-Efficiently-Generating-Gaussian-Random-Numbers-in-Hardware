/* Frozen pre-configurability implementation for N=128 regression. */
#include "ziggurat_trapezoid.h"
#include "pcg_rng.h"
#include "gaussian_constants.h"
#include <math.h>
#include <string.h>
#define N 128
#define R 3.442619855899
static double x[N], y[N], rectangle_probability;
static pcg_rng rng;
static zt_counters counts;
#if ZT_ENABLE_COUNTERS
#define COUNT(field) (++counts.field)
#else
#define COUNT(field) ((void)0)
#endif
static double uniform(void) { return pcg_uniform(&rng); }
void legacy_init(uint64_t seed) {
    /* build_ziggurat in ziggurat_gaussian_demo.m; analytic Gaussian tail area. */
    const double pi=ZT_PI; /* Identical double to the original literal. */
    double tail=sqrt(pi/2.0)*erfc(R/sqrt(2.0));
    double rect=R*exp(-R*R/2.0), area=rect+tail;
    x[0]=R; y[0]=exp(-R*R/2.0);
    for(unsigned i=1;i<N;i++) {
        y[i]=fmin(1.0,y[i-1]+area/x[i-1]);
        x[i]=sqrt(-2.0*log(y[i]));
    }
    rectangle_probability=rect/area;
    pcg_seed(&rng,seed); memset(&counts,0,sizeof counts);
}
double legacy_gaussian(void) {
    double magnitude;
    COUNT(total_samples);
    for(;;) {
        unsigned layer=(unsigned)(N*uniform());
        if(layer==0) {
            if(uniform()<rectangle_probability) {
                magnitude=R*uniform(); COUNT(rectangle_acceptances);
            } else {
                COUNT(tail_region_hits);
                for(;;) {
                    /* Open-at-zero uniforms avoid log(0); same distribution. */
                    double xt=-log(1.0-uniform())/R;
                    double yt=-log(1.0-uniform());
                    COUNT(rejection_region_tests);
                    if(2*yt>xt*xt) { magnitude=R+xt; break; }
                    COUNT(rejected_candidates); COUNT(retries);
                }
            }
            break;
        }
        if(layer==N-1) { COUNT(head_region_hits); }
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
void legacy_get_counters(zt_counters *out) { if(out)*out=counts; }
