#include "ziggurat_trapezoid.h"
#include <math.h>
#include "pcg_rng.h"
#include <stddef.h>
#include <string.h>

#define ZT_MAX_LAYERS 256
#define ZT_MAX_REFINEMENT 16
#define PI 3.141592653589793238462643383279502884

typedef struct { double a[ZT_MAX_LAYERS], w[ZT_MAX_LAYERS], d[ZT_MAX_LAYERS];
                 double x[ZT_MAX_LAYERS+1], y[ZT_MAX_LAYERS+1]; } table_t;
static table_t tabs[1+2*ZT_MAX_REFINEMENT];
static unsigned nlayer, nh, nt;
static pcg_rng rng;
static zt_counters counts;
static double uniform(void) { return pcg_uniform(&rng); }

/* Probability density function for standard normal distribution */
static double pdf(double x) { return exp(-0.5*x*x)/sqrt(2.0*PI); }

/* MATLAB compute_partitions uses G(x)=x*phi(x)+Q(x), G(Inf)=0. */
static double area(double x) { return x==INFINITY ? 0.0 : x*pdf(x)+0.5*erfc(x/sqrt(2.0)); }
static double inv_area(double target,double lo,double hi) {
    for(int k=0;k<100;k++){ double mid=lo+(hi-lo)*0.5; if(area(mid)>target)lo=mid;else hi=mid; }
    return lo+(hi-lo)*0.5;
}
/* Composite Simpson quadrature approximates MATLAB integral(...,1e-10,1e-12). */
static double inv_pdf(double y) { return sqrt(fmax(0.0,-2.0*log(sqrt(2.0*PI)*y))); }
static void fit(table_t *t,unsigned i) {
    double yl=t->y[i+1], yh=t->y[i], l0=0,l1=0; const int m=4096;
    for(int j=0;j<=m;j++){
        double s=(double)j/m, wt=(j==0||j==m)?1.0:(j&1?4.0:2.0);
        double tt, jac, x;
        if(yl==0.0) {
            tt=2*s*s-1; jac=4*s;
            x=(j==0)?0.0:inv_pdf(yh*s*s);
        } else {
            /* MATLAB non-tail branch: yLow + (yHigh-yLow)*(t+1)/2. */
            tt=2*s-1; jac=2;
            x=inv_pdf(yl+(yh-yl)*s);
        }
        l0+=wt*jac*x/sqrt(2.0); l1+=wt*jac*tt*x*sqrt(3.0/2.0);
    }
    l0/=3.0*m; l1/=3.0*m;
    /* First-order orthonormal Legendre fit, same orientation as fit_trapezoid.m. */
    double c=l0/sqrt(2.0), s=l1*sqrt(3.0/2.0), lower=fmax(c-s,c+s), upper=fmin(c-s,c+s);
    t->a[i]=2*upper/(upper+lower); t->w[i]=upper; t->d[i]=lower-upper;
}
static void build(table_t *t,unsigned n,double left,double right) {
    double ga=area(left), gb=area(right); t->x[0]=left;
    for(unsigned i=1;i<n;i++){
        double target=ga+(gb-ga)*(double)i/n, hi=isfinite(right)?right:fmax(1.0,t->x[i-1]+1.0);
        while(!isfinite(right)&&area(hi)>target)hi*=2;
        t->x[i]=inv_area(target,t->x[i-1],hi);
    }
    t->x[n]=right;
    for(unsigned i=0;i<=n;i++)t->y[i]=isinf(t->x[i])?0.0:pdf(t->x[i]);
    for(unsigned i=0;i<n;i++)fit(t,i);
}
int zt_init(uint64_t seed,unsigned n,unsigned h,unsigned tail) {
    if(n<2||n>ZT_MAX_LAYERS||h>ZT_MAX_REFINEMENT||tail>ZT_MAX_REFINEMENT)return 0;
    nlayer=n;nh=h;nt=tail; memset(&counts,0,sizeof counts); memset(tabs,0,sizeof tabs);
    pcg_seed(&rng,seed);
    build(&tabs[0],n,0.0,INFINITY);
    for(unsigned j=1;j<=h;j++){table_t *p=&tabs[j-1],*c=&tabs[j];build(c,n,p->x[0],p->x[1]);}
    for(unsigned j=1;j<=tail;j++){
        table_t *p=(j==1)?&tabs[0]:&tabs[ZT_MAX_REFINEMENT+j-1];
        table_t *c=&tabs[ZT_MAX_REFINEMENT+j];build(c,n,p->x[n-1],p->x[n]);
    }
    return 1;
}
static double sample_entry(table_t *t,unsigned i) {
    if(uniform()<t->a[i]){
#if ZT_ENABLE_COUNTERS
        counts.rectangle_acceptances++;
#endif
        return t->w[i]*uniform();
    }
#if ZT_ENABLE_COUNTERS
    counts.triangle_acceptances++;
#endif
    double u1=uniform(), u2=uniform();
    return t->w[i]+t->d[i]*fabs(u1-u2);
}
double zt_gaussian(void) {
    if(!nlayer)return NAN;
#if ZT_ENABLE_COUNTERS
    counts.total_samples++;
#endif
    table_t *t=&tabs[0]; unsigned idx=0, lev=0,side=0;
    for(;;){unsigned i=(unsigned)(uniform()*nlayer);if(i>=nlayer)i=nlayer-1;
        if((side==0||side==1)&&i==0&&lev<nh){
#if ZT_ENABLE_COUNTERS
            counts.head_region_hits++;counts.head_refined_paths++;
#endif
            t=&tabs[++lev];side=1;continue;
        }
        if((side==0||side==2)&&i==nlayer-1&&lev<nt){
#if ZT_ENABLE_COUNTERS
            counts.tail_region_hits++;counts.tail_refined_paths++;
#endif
            t=&tabs[ZT_MAX_REFINEMENT+ ++lev];side=2;continue;
        }
        idx=i;break;
    }
    double mag=sample_entry(t,idx);
    return uniform()<0.5?-mag:mag;
}
void zt_get_counters(zt_counters *o){if(o)*o=counts;}
void zt_reset_counters(void){memset(&counts,0,sizeof counts);}
unsigned zt_layers(void){return nlayer;}
double zt_table_x(unsigned table,unsigned boundary){if(table>=1+2*ZT_MAX_REFINEMENT||boundary>nlayer)return NAN;return tabs[table].x[boundary];}
double zt_table_y(unsigned table,unsigned boundary){if(table>=1+2*ZT_MAX_REFINEMENT||boundary>nlayer)return NAN;return tabs[table].y[boundary];}
