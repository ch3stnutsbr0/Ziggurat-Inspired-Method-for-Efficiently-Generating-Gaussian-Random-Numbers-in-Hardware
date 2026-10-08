/* Internal table validation without adding test-only public API. */
#include "../ziggurat_basic.c"
#include <assert.h>
#include <stdio.h>
#include <limits.h>
void legacy_init(uint64_t seed);
double legacy_gaussian(void);
void legacy_get_counters(zt_counters *out);

/* Independent recurrence in long double. Too-small R reaches the peak early.
 * On platforms where long double == double, this still checks the same root
 * independently of the static lookup and initialization implementation. */
static long double residual(unsigned n, long double r) {
    long double yy=expl(-r*r/2), xx=r;
    long double a=r*yy+sqrtl((long double)ZT_PI/2)*erfcl(r/sqrtl(2));
    for(unsigned i=1;i<n;i++) {
        yy+=a/xx;
        if(i==n-1) return yy-1;
        if(yy>=1) return 1;
        xx=sqrtl(-2*logl(yy));
    }
    return NAN;
}
static long double derive(unsigned n) {
    long double lo=1,hi=5;
    assert(residual(n,lo)>0 && residual(n,hi)<0);
    for(unsigned i=0;i<100;i++) {
        long double mid=(lo+hi)/2;
        if(mid==lo || mid==hi) break;
        if(residual(n,mid)>0) lo=mid; else hi=mid;
    }
    return (lo+hi)/2;
}
int main(void) {
    assert(isnan(zb_gaussian()));
    for(unsigned k=0;k<sizeof configurations/sizeof configurations[0];k++) {
        unsigned n=configurations[k].n;
        long double root=derive(n);
        assert(fabsl(root-configurations[k].r)<(n==128?3e-12L:1e-13L));
        assert(fabsl(residual(n,configurations[k].r))<(n==128?1e-10L:2e-12L));
        assert(zb_init(1,n)); assert(nlayer==n && cutoff==configurations[k].r);
        assert(x[0]==cutoff && fabs(y[n-1]-1)<1e-10);
        long double tail=sqrtl((long double)ZT_PI/2)*erfcl(cutoff/sqrtl(2));
        long double rect=cutoff*expl(-((long double)cutoff)*cutoff/2), a=tail+rect;
        assert(rectangle_probability>0 && rectangle_probability<1);
        assert(fabsl(rectangle_probability-rect/a)<1e-14L);
        for(unsigned i=0;i<n;i++) {
            assert(isfinite(x[i]) && isfinite(y[i]));
            assert(x[i]>=0 && y[i]>0 && y[i]<=1);
            assert(fabs(y[i]-exp(-x[i]*x[i]/2))<1e-14);
            if(i) {
                assert(x[i]<x[i-1] && y[i]>y[i-1]);
                assert(fabsl(x[i-1]*(y[i]-y[i-1])-a)<a*1e-10L);
            }
        }
        /* Reject mismatched cutoffs, even if an unconditional clamp would pass. */
        assert(!build_tables(n,cutoff+0.001)); assert(isnan(zb_gaussian()));
        assert(!build_tables(n,configurations[k].r-0.001));
        assert(zb_init(123,n)); double saved[256];
        for(unsigned i=0;i<256;i++) saved[i]=zb_gaussian();
        assert(zb_init(123,n));
        for(unsigned i=0;i<256;i++) assert(saved[i]==zb_gaussian());
        assert(zb_init(1,n));
        double sum=0,sq=0; unsigned extreme=0;
        for(unsigned i=0;i<1000000;i++) {
            double v=zb_gaussian(); assert(isfinite(v));sum+=v;sq+=v*v;
            if(fabs(v)>3) extreme++;
        }
        double mean=sum/1e6, var=sq/1e6-mean*mean;
        assert(fabs(mean)<0.006 && fabs(var-1)<0.012);
        assert(extreme>2300 && extreme<3100);
#if ZT_ENABLE_COUNTERS
        assert(counts.total_samples==1000000);
        assert(counts.rejected_candidates==counts.retries);
        assert(counts.rejection_region_tests>=counts.rejected_candidates);
#else
        assert(counts.total_samples==0);
#endif
        printf("N=%u derived R=%.17Lg stored residual=% .3Le mean=%.7f var=%.7f tails=%u PASS\n",
               n,root,residual(n,configurations[k].r),mean,var,extreme);
    }
    const unsigned invalid[]={0,1,2,7,9,127,129,255,257,UINT_MAX};
    for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];i++) {
        assert(!zb_init(1,invalid[i]));assert(isnan(zb_gaussian()));assert(nlayer==0);
    }
    /* Original N=128 stream and counters, using the frozen pre-change code. */
    const uint64_t seeds[]={1,0,UINT64_MAX};
    for(unsigned j=0;j<3;j++) {
        legacy_init(seeds[j]); assert(zb_init(seeds[j],128));
        for(unsigned i=0;i<100000;i++) assert(legacy_gaussian()==zb_gaussian());
        zt_counters before,after; legacy_get_counters(&before);zb_get_counters(&after);
        assert(memcmp(&before,&after,sizeof before)==0);
    }
    puts("Initialization, tables, roots, moments, reproducibility, legacy streams and counters PASS");
    return 0;
}
