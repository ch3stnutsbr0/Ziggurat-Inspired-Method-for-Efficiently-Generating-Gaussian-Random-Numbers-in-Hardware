#define _POSIX_C_SOURCE 200809L
#include "gaussian_prng.h"
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* Experiment-only cumulative timings. The existing benchmark and Gaussian
 * sampling sources are unchanged. All output occurs after the timed loops. */
static double now_seconds(void) {
    struct timespec t;
    if(clock_gettime(CLOCK_MONOTONIC,&t)) { perror("clock_gettime"); exit(1); }
    return (double)t.tv_sec + 1e-9*t.tv_nsec;
}
static uint64_t number(const char *text) {
    char *end; errno=0;
    unsigned long long n=strtoull(text,&end,10);
    if(text[0]<'0'||text[0]>'9'||*end||errno) {
        fprintf(stderr,"Invalid integer: %s\n",text); exit(2);
    }
    return (uint64_t)n;
}
typedef struct {uint64_t samples; double elapsed,checksum,sum,sumsq;} checkpoint;
int main(int argc,char **argv) {
    if(argc<5 || argc>36) {
        fprintf(stderr,"Usage: %s basic|trapezoid layers seed checkpoint...\n",argv[0]);return 2;
    }
    int basic=!strcmp(argv[1],"basic");
    if(!basic && strcmp(argv[1],"trapezoid")) return 2;
    uint64_t layers=number(argv[2]),seed=number(argv[3]),previous=0;
    checkpoint records[32]; unsigned count=(unsigned)argc-4;
    if(layers>256) return 2;
    for(unsigned k=0;k<count;k++) {
        uint64_t n=number(argv[k+4]);
        if(n<=previous || n>UINT64_C(33554432)) return 2;
        records[k].samples=n;previous=n;
    }
    if(previous!=UINT64_C(33554432)) {
        fprintf(stderr,"Final checkpoint must be 2^25 samples\n");return 2;
    }
    if(!(basic?zb_init_prng(seed,(unsigned)layers,PRNG_XOSHIRO256PLUS):
                zt_init_prng(seed,(unsigned)layers,2,4,PRNG_XOSHIRO256PLUS))) return 2;
    double (*generate)(void)=basic?zb_generator(PRNG_XOSHIRO256PLUS):zt_generator(PRNG_XOSHIRO256PLUS);
    volatile double checksum=0;double sum=0,sumsq=0;uint64_t generated=0;
    double start=now_seconds();
    for(unsigned k=0;k<count;k++) {
        for(;generated<records[k].samples;generated++) {
            double x=generate();checksum+=x;sum+=x;sumsq+=x*x;
        }
        records[k].elapsed=now_seconds()-start;
        records[k].checksum=(double)checksum;records[k].sum=sum;records[k].sumsq=sumsq;
    }
    for(unsigned k=0;k<count;k++) {
        checkpoint *r=&records[k];double n=(double)r->samples;
        if(r->elapsed<=0 || !isfinite(r->checksum)) return 1;
        printf("BENCHMARK_JSON: {\"algorithm\":\"%s\",\"prng\":\"xoshiro256plus\","
               "\"N\":%u,\"H\":%u,\"T\":%u,\"seed\":%" PRIu64 ","
               "\"num_samples\":%" PRIu64 ",\"generated_samples\":33554432,\"warmup_samples\":0,"
               "\"compiler_optimization\":\"O2\",\"sampling_time_seconds\":%.17g,"
               "\"throughput_samples_per_second\":%.17g,\"time_per_sample_ns\":%.17g,"
               "\"checksum\":%.17g,\"mean\":%.17g,\"variance\":%.17g}\n",
               argv[1],(unsigned)layers,basic?0:2,basic?0:4,seed,r->samples,
               r->elapsed,n/r->elapsed,r->elapsed*1e9/n,r->checksum,r->sum/n,
               (r->sumsq-r->sum*r->sum/n)/(n-1));
    }
    return 0;
}
