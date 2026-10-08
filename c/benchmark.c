#define _POSIX_C_SOURCE 200809L
#include "ziggurat_trapezoid.h"
#include "ziggurat_basic.h"
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now_seconds(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (double)t.tv_sec+1e-9*t.tv_nsec;}
int main(int argc,char **argv){
    uint64_t samples=10000000,seed=1;unsigned n=8,h=2,tail=4;const char *output=NULL;int show=0; const char *algorithm="trapezoid";
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"--algorithm")&&i+1<argc)algorithm=argv[++i];
        else if(!strcmp(argv[i],"--samples")&&i+1<argc)samples=strtoull(argv[++i],NULL,10);
        else if(!strcmp(argv[i],"--seed")&&i+1<argc)seed=strtoull(argv[++i],NULL,0);
        else if(!strcmp(argv[i],"--layers")&&i+1<argc)n=(unsigned)strtoul(argv[++i],NULL,10);
        else if(!strcmp(argv[i],"--head")&&i+1<argc)h=(unsigned)strtoul(argv[++i],NULL,10);
        else if(!strcmp(argv[i],"--tail")&&i+1<argc)tail=(unsigned)strtoul(argv[++i],NULL,10);
        else if(!strcmp(argv[i],"--output")&&i+1<argc)output=argv[++i];
        else if(!strcmp(argv[i],"--counters"))show=1;
        else {fprintf(stderr,"Usage: %s [--algorithm trapezoid|basic] [--samples N] [--seed N] [--layers N] [--head H] [--tail T] [--output FILE] [--counters]\n",argv[0]);return 2;}
    }
    int basic=!strcmp(algorithm,"basic");
    if(!basic && strcmp(algorithm,"trapezoid")) { fprintf(stderr,"Unknown algorithm\n"); return 2; }
    if(samples<2) { fprintf(stderr,"Require at least two samples\n"); return 2; }
    if(basic) zb_init(seed);
    if(!basic && !zt_init(seed,n,h,tail)){fprintf(stderr,"Invalid table configuration\n");return 2;}
    FILE *f=output?fopen(output,"w"):NULL;if(output&&!f){perror(output);return 1;}
    if(f)fprintf(f,"sample\n");
    double (*generate)(void)=basic?zb_gaussian:zt_gaussian;
    printf("Algorithm:        %s\n",algorithm);
    if(basic) printf("Configuration:    N=128 R=3.442619855899\n");
    else printf("Configuration:    N=%u H=%u T=%u\n",n,h,tail);
    if(output) printf("Timing includes CSV I/O; use no --output for performance comparisons.\n");
    volatile double checksum=0.0;double sum=0.0,sumsq=0.0;double start=now_seconds();
    for(uint64_t i=0;i<samples;i++){double x=generate();checksum+=x;sum+=x;sumsq+=x*x;if(f)fprintf(f,"%.17g\n",x);}
    double elapsed=now_seconds()-start;if(f&&fclose(f)!=0){perror("close output");return 1;}
    printf("Samples:          %" PRIu64 "\nTime:             %.6f s\nThroughput:       %.3f M samples/s\nTime per sample:  %.2f ns\nChecksum:         %.17g\n",samples,elapsed,(double)samples/elapsed/1e6,elapsed*1e9/(double)samples,(double)checksum);
    if(output)printf("Output:           %s\n",output);
    if(samples>1)printf("Mean:             %.8f\nVariance:         %.8f\n",sum/(double)samples,(sumsq-sum*sum/(double)samples)/(double)(samples-1));
    if(show && !ZT_ENABLE_COUNTERS) printf("Counters disabled; build with make debug.\n");
    if(show && ZT_ENABLE_COUNTERS){zt_counters c;if(basic)zb_get_counters(&c);else zt_get_counters(&c);printf("Counters: total=%" PRIu64 " rect=%" PRIu64 " triangle=%" PRIu64 " head=%" PRIu64 " tail=%" PRIu64 " head-refined=%" PRIu64 " tail-refined=%" PRIu64 "\n",c.total_samples,c.rectangle_acceptances,c.triangle_acceptances,c.head_region_hits,c.tail_region_hits,c.head_refined_paths,c.tail_refined_paths);printf("Rejection tests=%" PRIu64 " rejected=%" PRIu64 " retries=%" PRIu64 "\n",c.rejection_region_tests,c.rejected_candidates,c.retries);}
    return 0;
}
