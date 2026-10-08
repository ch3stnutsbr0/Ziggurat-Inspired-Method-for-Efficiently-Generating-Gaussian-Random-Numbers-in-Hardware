#define _POSIX_C_SOURCE 200809L
#include "ziggurat_trapezoid.h"
#include "ziggurat_basic.h"
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <float.h>
#include <limits.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>
#include <unistd.h>

static double now_seconds(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (double)t.tv_sec+1e-9*t.tv_nsec;}
/* Reject malformed/overflowing values rather than silently wrapping N. */
static uint64_t parse_unsigned(const char *text, uint64_t limit, int base) {
    char *end;
    errno=0;
    unsigned long long value=strtoull(text,&end,base);
    if(text[0]<'0' || text[0]>'9' || *end || errno || value>limit) {
        fprintf(stderr,"Invalid unsigned integer: %s\n",text); exit(2);
    }
    return (uint64_t)value;
}
/* Create all components of a relative or absolute directory path. */
static int make_directory(const char *path){
    if(!*path){fprintf(stderr,"Output directory must not be empty\n");return 0;}
    char *copy=malloc(strlen(path)+1);
    if(!copy){perror("allocate directory path");return 0;}
    strcpy(copy,path);
    for(char *p=copy+1;;p++){
        if(*p!='/' && *p!='\0')continue;
        char saved=*p;
        *p='\0';
        if(*copy && mkdir(copy,0777)!=0){
            struct stat st;
            if(errno!=EEXIST || stat(copy,&st)!=0 || !S_ISDIR(st.st_mode)){
                perror(copy);free(copy);return 0;
            }
        }
        *p=saved;
        if(!saved)break;
    }
    free(copy);
    return 1;
}
static char *join_path(const char *dir,const char *name){
    size_t a=strlen(dir),b=strlen(name);
    if(a>SIZE_MAX-b-2)return NULL;
    char *path=malloc(a+b+2);
    if(path)snprintf(path,a+b+2,"%s/%s",dir,name);
    return path;
}
static int exists(const char *path){
    struct stat st;
    if(lstat(path,&st)==0)return 1;
    if(errno==ENOENT)return 0;
    perror(path);return -1;
}
static FILE *open_experiment_file(const char *path,int overwrite){
    int fd=open(path,O_WRONLY|O_CREAT|(overwrite?O_TRUNC:O_EXCL),0666);
    if(fd<0){perror(path);return NULL;}
    FILE *f=fdopen(fd,"wb");
    if(!f){perror(path);close(fd);return NULL;}
    return f;
}
int main(int argc,char **argv){
    uint64_t samples=10000000,seed=1;unsigned n=128,h=2,tail=4;const char *output=NULL,*output_dir=NULL;int overwrite=0;int layers_set=0; int show=0; const char *algorithm="trapezoid";
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"--algorithm")&&i+1<argc)algorithm=argv[++i];
        else if(!strcmp(argv[i],"--samples")&&i+1<argc)samples=parse_unsigned(argv[++i],UINT64_MAX,10);
        else if(!strcmp(argv[i],"--seed")&&i+1<argc)seed=parse_unsigned(argv[++i],UINT64_MAX,0);
        else if(!strcmp(argv[i],"--layers")&&i+1<argc){n=(unsigned)parse_unsigned(argv[++i],UINT_MAX,10);layers_set=1;}
        else if(!strcmp(argv[i],"--head")&&i+1<argc)h=(unsigned)parse_unsigned(argv[++i],UINT_MAX,10);
        else if(!strcmp(argv[i],"--tail")&&i+1<argc)tail=(unsigned)parse_unsigned(argv[++i],UINT_MAX,10);
        else if(!strcmp(argv[i],"--output")&&i+1<argc&&strncmp(argv[i+1],"--",2))output=argv[++i];
        else if(!strcmp(argv[i],"--output-dir")&&i+1<argc&&strncmp(argv[i+1],"--",2))output_dir=argv[++i];
        else if(!strcmp(argv[i],"--overwrite"))overwrite=1;
        else if(!strcmp(argv[i],"--counters"))show=1;
        else {fprintf(stderr,"Usage: %s [--algorithm trapezoid|basic] [--samples N] [--seed N] [--layers N] [--head H] [--tail T] [--output FILE | --output-dir DIR [--overwrite]] [--counters]\n",argv[0]);return 2;}
    }
    if(output && output_dir){fprintf(stderr,"--output and --output-dir cannot be used together\n");return 2;}
    if(overwrite && !output_dir){fprintf(stderr,"--overwrite requires --output-dir\n");return 2;}
    int basic=!strcmp(algorithm,"basic");
    if(!basic && strcmp(algorithm,"trapezoid")) { fprintf(stderr,"Unknown algorithm\n"); return 2; }
    if(samples<2) { fprintf(stderr,"Require at least two samples\n"); return 2; }
    if(!layers_set) n=basic?128:8;
    if(basic && !zb_init(seed,n)) { fprintf(stderr,"Unsupported or invalid classical layer count %u; supported: 8 16 32 64 128 256\n",n); return 2; }
    if(!basic && !zt_init(seed,n,h,tail)){fprintf(stderr,"Invalid table configuration\n");return 2;}
    /* Output uses at most 512 KiB, regardless of the requested sample count. */
    const size_t chunk_size=65536;
    size_t capacity=samples<chunk_size?(size_t)samples:chunk_size;
    double *buffer=NULL;
    FILE *f=NULL,*summary_file=NULL,*config_file=NULL;
    char *sample_path=NULL,*summary_path=NULL,*config_path=NULL;
    int created_sample=0,created_summary=0,created_config=0;
    if(output_dir){
        if(!make_directory(output_dir))return 1;
        sample_path=join_path(output_dir,"samples.bin");
        summary_path=join_path(output_dir,"summary.json");
        config_path=join_path(output_dir,"config.json");
        if(!sample_path || !summary_path || !config_path){
            fprintf(stderr,"Cannot allocate experiment paths\n");goto output_failure;
        }
        if(!overwrite){
            int a=exists(sample_path),b=exists(summary_path),c=exists(config_path);
            if(a<0 || b<0 || c<0)goto output_failure;
            if(a || b || c){
                fprintf(stderr,"Experiment files already exist in %s; use --overwrite to replace them\n",output_dir);
                goto output_failure;
            }
        }
        output=sample_path;
    }
    if(output){
        if(!*output){fprintf(stderr,"Output filename must not be empty\n");goto output_failure;}
        if(CHAR_BIT!=8 || sizeof(double)!=8 || FLT_RADIX!=2 || DBL_MANT_DIG!=53 || DBL_MAX_EXP!=1024){
            fprintf(stderr,"Binary output requires IEEE 754 binary64 doubles and 8-bit bytes\n");goto output_failure;
        }
        buffer=malloc(capacity*sizeof(*buffer));
        if(!buffer){perror("allocate sample buffer");goto output_failure;}
        if(output_dir){
            f=open_experiment_file(sample_path,overwrite);
            if(!f)goto output_failure;
            created_sample=1;
            summary_file=open_experiment_file(summary_path,overwrite);
            if(!summary_file)goto output_failure;
            created_summary=1;
            config_file=open_experiment_file(config_path,overwrite);
            if(!config_file)goto output_failure;
            created_config=1;
        }else{
            f=fopen(output,"wb");
            if(!f){perror(output);goto output_failure;}
        }
    }
    double (*generate)(void)=basic?zb_gaussian:zt_gaussian;
    printf("Algorithm:        %s\n",algorithm);
    if(basic) printf("Configuration:    N=%u (H/T not applicable)\n",n);
    else printf("Configuration:    N=%u H=%u T=%u\n",n,h,tail);
    printf("Seed:             %" PRIu64 "\n",seed);
    if(output) printf("Binary output mode: I/O excluded from timing; memory writes affect throughput.\n");
    volatile double checksum=0.0;double sum=0.0,sumsq=0.0;double elapsed;
    if(!output){
        double start=now_seconds();
        for(uint64_t i=0;i<samples;i++){double x=generate();checksum+=x;sum+=x;sumsq+=x*x;}
        elapsed=now_seconds()-start;
    } else {
        elapsed=0.0;
        const uint16_t one=1;
        const int little_endian=*(const unsigned char *)&one==1;
        for(uint64_t done=0;done<samples;){
            size_t count=samples-done<capacity?(size_t)(samples-done):capacity;
            double start=now_seconds();
            for(size_t i=0;i<count;i++){
                double x=generate();checksum+=x;sum+=x;sumsq+=x*x;buffer[i]=x;
            }
            elapsed+=now_seconds()-start;
            if(!little_endian){
                unsigned char *bytes=(unsigned char *)buffer;
                for(size_t i=0;i<count;i++)for(size_t j=0;j<4;j++){
                    unsigned char tmp=bytes[8*i+j];bytes[8*i+j]=bytes[8*i+7-j];bytes[8*i+7-j]=tmp;
                }
            }
            if(fwrite(buffer,sizeof(*buffer),count,f)!=count){perror("write output");goto output_failure;}
            done+=count;
        }
        int close_result=fclose(f);f=NULL;
        if(close_result!=0){perror("close output");goto output_failure;}
        free(buffer);buffer=NULL;
    }
    if(output_dir){
        double mean=sum/(double)samples;
        double variance=(sumsq-sum*sum/(double)samples)/(double)(samples-1);
        double throughput=(double)samples/elapsed;
        double ns_per_sample=elapsed*1e9/(double)samples;
        if(!isfinite(elapsed) || elapsed<=0 || !isfinite(throughput) ||
           !isfinite(ns_per_sample) || !isfinite(mean) || !isfinite(variance) ||
           !isfinite((double)checksum)){
            fprintf(stderr,"Non-finite summary value cannot be written as JSON\n");
            goto output_failure;
        }
        if(fprintf(summary_file,
            "{\n  \"sampling_time_seconds\": %.17g,\n  \"throughput_samples_per_second\": %.17g,\n"
            "  \"time_per_sample_ns\": %.17g,\n  \"mean\": %.17g,\n"
            "  \"variance\": %.17g,\n  \"checksum\": %.17g,\n"
            "  \"num_samples\": %" PRIu64 "\n}\n",
            elapsed,throughput,ns_per_sample,mean,variance,(double)checksum,samples)<0){
            perror(summary_path);goto output_failure;
        }
        int summary_close=fclose(summary_file);summary_file=NULL;
        if(summary_close!=0){perror(summary_path);goto output_failure;}
        if(fprintf(config_file,"{\n  \"algorithm\": \"%s\",\n  \"N\": %u,\n",algorithm,n)<0){
            perror(config_path);goto output_failure;
        }
        if(!basic && fprintf(config_file,"  \"H\": %u,\n  \"T\": %u,\n",h,tail)<0){
            perror(config_path);goto output_failure;
        }
        if(fprintf(config_file,"  \"seed\": %" PRIu64 ",\n  \"num_samples\": %" PRIu64,seed,samples)<0){
            perror(config_path);goto output_failure;
        }
#ifdef BENCHMARK_OPTIMIZATION
        if(fprintf(config_file,",\n  \"compiler_optimization\": \"%s\"",BENCHMARK_OPTIMIZATION)<0){
            perror(config_path);goto output_failure;
        }
#endif
        if(fprintf(config_file,"\n}\n")<0){perror(config_path);goto output_failure;}
        int config_close=fclose(config_file);config_file=NULL;
        if(config_close!=0){perror(config_path);goto output_failure;}
    }
    printf("Samples:          %" PRIu64 "\nTime:             %.6f s\nThroughput:       %.3f M samples/s\nTime per sample:  %.2f ns\nChecksum:         %.17g\n",samples,elapsed,(double)samples/elapsed/1e6,elapsed*1e9/(double)samples,(double)checksum);
    printf("Samples/second:   %.3f\n",(double)samples/elapsed);
    if(output_dir)printf("Output directory: %s\n",output_dir);
    else if(output)printf("Output:           %s\n",output);
    if(samples>1)printf("Mean:             %.8f\nVariance:         %.8f\n",sum/(double)samples,(sumsq-sum*sum/(double)samples)/(double)(samples-1));
    if(show && !ZT_ENABLE_COUNTERS) printf("Counters disabled; build with make debug.\n");
    if(show && ZT_ENABLE_COUNTERS){zt_counters c;if(basic)zb_get_counters(&c);else zt_get_counters(&c);printf("Counters: total=%" PRIu64 " rect=%" PRIu64 " triangle=%" PRIu64 " head=%" PRIu64 " tail=%" PRIu64 " head-refined=%" PRIu64 " tail-refined=%" PRIu64 "\n",c.total_samples,c.rectangle_acceptances,c.triangle_acceptances,c.head_region_hits,c.tail_region_hits,c.head_refined_paths,c.tail_refined_paths);printf("Rejection tests=%" PRIu64 " rejected=%" PRIu64 " retries=%" PRIu64 "\n",c.rejection_region_tests,c.rejected_candidates,c.retries);}
    free(sample_path);free(summary_path);free(config_path);
    return 0;
output_failure:
    if(f)fclose(f);
    if(summary_file)fclose(summary_file);
    if(config_file)fclose(config_file);
    free(buffer);
    if(output_dir && !overwrite){
        if(created_sample)unlink(sample_path);
        if(created_summary)unlink(summary_path);
        if(created_config)unlink(config_path);
    }
    free(sample_path);free(summary_path);free(config_path);
    return 1;
}
