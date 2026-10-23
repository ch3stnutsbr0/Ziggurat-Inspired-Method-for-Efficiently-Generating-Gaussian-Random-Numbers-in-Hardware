#define _POSIX_C_SOURCE 200809L
#include "ziggurat_trapezoid.h"
#include "ziggurat_basic.h"
#include "gaussian_prng.h"
#include "uniform_buffer.h"
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
static const char *cpu_architecture(void) {
#if defined(__aarch64__) || defined(__arm64__)
    return "arm64";
#elif defined(__x86_64__)
    return "x86_64";
#elif defined(__i386__)
    return "x86";
#else
    return "unknown";
#endif
}
static const char *compiler_name(void) {
#if defined(__clang__)
    return "Clang " __clang_version__;
#elif defined(__GNUC__)
    return "GCC " __VERSION__;
#else
    return "unknown";
#endif
}
#ifndef BENCHMARK_OPTIMIZATION
#define BENCHMARK_OPTIMIZATION "unknown"
#endif
#ifndef BENCHMARK_CFLAGS
#define BENCHMARK_CFLAGS "unknown (built outside supplied Makefile)"
#endif
static int compare_double(const void *a,const void *b) {
    double x=*(const double *)a,y=*(const double *)b;
    return (x>y)-(x<y);
}
/* The same pcg_uniform() used by the Gaussian generators. Timing excludes seeding,
 * warm-up, clock reads inside the loop, and the final checksum transfer. */
static double benchmark_uniform(uint64_t iterations, volatile double *sink) {
    double times[5];
    for(unsigned rep=0;rep<5;rep++) {
        pcg_rng r={0};
        pcg_seed(&r,0x853c49e6748fea9bULL+rep);
        for(unsigned i=0;i<100000;i++)(void)pcg_uniform(&r);
        double accum[8]={0};
        double start=now_seconds();
        for(uint64_t i=0;i<iterations;i++)accum[i&7u]+=pcg_uniform(&r);
        double elapsed=now_seconds()-start;
        for(unsigned j=0;j<8;j++)*sink+=accum[j];
        times[rep]=elapsed*1e9/(double)iterations;
    }
    qsort(times,5,sizeof times[0],compare_double);
    return times[2];
}
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
/* One exhaustion checkpoint per output batch, never per uniform/sample.
 * Progress lives outside this frame so longjmp preserves completed statistics. */
typedef struct { uint64_t generated; double sum,sumsq; volatile double checksum; } sample_progress;
static void sample_batch(double (*generate)(void),uniform_buffer *source,
                         uint64_t count,double *output,sample_progress *progress){
    if(source){if(setjmp(source->exhaustion))return;}
    for(uint64_t i=0;i<count;i++){
        double x=generate();
        progress->checksum+=x;progress->sum+=x;progress->sumsq+=x*x;
        if(output)output[i]=x;
        ++progress->generated;
    }
}
static void uniform_metrics(FILE *f,const char *algorithm,const char *mode,
                            uint64_t generated,uint64_t consumed,size_t bytes,
                            double elapsed,int exhausted){
    fprintf(f,"\"algorithm\":\"%s\",\"uniform_mode\":\"%s\","
        "\"gaussian_samples_generated\":%" PRIu64 ",\"uniform_values_consumed\":%" PRIu64 ","
        "\"uniforms_per_sample\":%.17g,\"buffer_size_bytes\":%zu,"
        "\"buffer_utilization\":%.17g,\"buffer_exhausted\":%s,\"complete\":%s,"
        "\"throughput_million_samples_per_second\":",
        algorithm,mode,generated,consumed,generated?(double)consumed/generated:0.0,
        bytes,bytes?(double)consumed/(bytes/sizeof(double)):0.0,
        exhausted?"true":"false",exhausted?"false":"true");
    if(exhausted)fprintf(f,"null");else fprintf(f,"%.17g",generated/elapsed/1e6);
}
int main(int argc,char **argv){
    uint64_t samples=10000000,seed=1,prng_iterations=10000000,warmup=0;unsigned n=128,h=2,tail=4;const char *output=NULL,*output_dir=NULL;int overwrite=0;int layers_set=0; int show=0,profile_prng=0,iterations_set=0,report_json=0; const char *algorithm="trapezoid", *prng="pcg32"; prng_type type=PRNG_PCG32;
    const char *uniform_mode="inline", *uniform_cache=NULL;
    size_t uniform_bytes=UNIFORM_BUFFER_SIZE_BYTES;
    uniform_buffer source={0};
    uint64_t uniforms_consumed=0;
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"--algorithm")&&i+1<argc)algorithm=argv[++i];
        else if(!strcmp(argv[i],"--uniform-mode")&&i+1<argc)uniform_mode=argv[++i];
        else if(!strcmp(argv[i],"--uniform-buffer-bytes")&&i+1<argc)uniform_bytes=(size_t)parse_unsigned(argv[++i],SIZE_MAX,10);
        else if(!strcmp(argv[i],"--uniform-buffer-cache")&&i+1<argc)uniform_cache=argv[++i];
        else if(!strcmp(argv[i],"--prng")&&i+1<argc)prng=argv[++i];
        else if(!strcmp(argv[i],"--samples")&&i+1<argc)samples=parse_unsigned(argv[++i],UINT64_MAX,10);
        else if(!strcmp(argv[i],"--seed")&&i+1<argc)seed=parse_unsigned(argv[++i],UINT64_MAX,0);
        else if(!strcmp(argv[i],"--warmup")&&i+1<argc)warmup=parse_unsigned(argv[++i],UINT64_MAX,10);
        else if(!strcmp(argv[i],"--report-json"))report_json=1;
        else if(!strcmp(argv[i],"--layers")&&i+1<argc){n=(unsigned)parse_unsigned(argv[++i],UINT_MAX,10);layers_set=1;}
        else if(!strcmp(argv[i],"--head")&&i+1<argc)h=(unsigned)parse_unsigned(argv[++i],UINT_MAX,10);
        else if(!strcmp(argv[i],"--tail")&&i+1<argc)tail=(unsigned)parse_unsigned(argv[++i],UINT_MAX,10);
        else if(!strcmp(argv[i],"--output")&&i+1<argc&&strncmp(argv[i+1],"--",2))output=argv[++i];
        else if(!strcmp(argv[i],"--output-dir")&&i+1<argc&&strncmp(argv[i+1],"--",2))output_dir=argv[++i];
        else if(!strcmp(argv[i],"--overwrite"))overwrite=1;
        else if(!strcmp(argv[i],"--counters"))show=1;
        else if(!strcmp(argv[i],"--profile-prng"))profile_prng=1;
        else if(!strcmp(argv[i],"--prng-iterations")&&i+1<argc){prng_iterations=parse_unsigned(argv[++i],UINT64_MAX,10);iterations_set=1;}
        else {fprintf(stderr,"Usage: %s [--algorithm trapezoid|basic] [--prng pcg32|xoshiro256plus] [--uniform-mode inline|precomputed] [--uniform-buffer-bytes N] [--uniform-buffer-cache FILE] [--samples N] [--seed N] [--layers N] [--head H] [--tail T] [--output FILE | --output-dir DIR [--overwrite]] [--counters] [--warmup N] [--report-json] [--profile-prng [--prng-iterations N]]\n",argv[0]);return 2;}
    }
    int precomputed=!strcmp(uniform_mode,"precomputed");
    if(!precomputed && strcmp(uniform_mode,"inline")){fprintf(stderr,"Unknown uniform mode\n");return 2;}
    if(!uniform_bytes || uniform_bytes%8 || (uniform_cache && !precomputed) || (precomputed && (profile_prng || show))){
        fprintf(stderr,"Require a positive multiple-of-8 buffer size; cache requires precomputed; precomputed cannot use inline PRNG profiling/counters\n");return 2;
    }
    if(!prng_parse(prng,&type)){fprintf(stderr,"Unknown PRNG: %s\n",prng);return 2;}
    /* Existing profiling fields count PCG32 words and are intentionally PCG-specific. */
    if(profile_prng && type!=PRNG_PCG32){fprintf(stderr,"--profile-prng currently supports pcg32 only\n");return 2;}
    if(output && output_dir){fprintf(stderr,"--output and --output-dir cannot be used together\n");return 2;}
    if(overwrite && !output_dir){fprintf(stderr,"--overwrite requires --output-dir\n");return 2;}
    int basic=!strcmp(algorithm,"basic");
    if(!basic && strcmp(algorithm,"trapezoid")) { fprintf(stderr,"Unknown algorithm\n"); return 2; }
    if(samples<2) { fprintf(stderr,"Require at least two samples\n"); return 2; }
    if(!prng_iterations || (!profile_prng && iterations_set)) {
        fprintf(stderr,"--prng-iterations requires --profile-prng and a positive count\n");return 2;
    }
    if(!layers_set) n=basic?128:8;
    if(basic && !zb_init_prng(seed,n,type)) { fprintf(stderr,"Unsupported or invalid classical layer count %u; supported: 8 16 32 64 128 256\n",n); return 2; }
    if(!basic && !zt_init_prng(seed,n,h,tail,type)){fprintf(stderr,"Invalid table configuration\n");return 2;}
    /* Output uses at most 512 KiB, regardless of the requested sample count. */
    const size_t chunk_size=65536;
    size_t capacity=samples<chunk_size?(size_t)samples:chunk_size;
    double *buffer=NULL;
    FILE *f=NULL,*summary_file=NULL,*config_file=NULL,*profile_file=NULL;
    char *sample_path=NULL,*summary_path=NULL,*config_path=NULL,*profile_path=NULL;
    int created_sample=0,created_summary=0,created_config=0,created_profile=0;
    if(output_dir){
        if(!make_directory(output_dir))return 1;
        sample_path=join_path(output_dir,"samples.bin");
        summary_path=join_path(output_dir,"summary.json");
        config_path=join_path(output_dir,"config.json");
        if(profile_prng)profile_path=join_path(output_dir,"prng_profile.json");
        if(!sample_path || !summary_path || !config_path || (profile_prng && !profile_path)){
            fprintf(stderr,"Cannot allocate experiment paths\n");goto output_failure;
        }
        if(!overwrite){
            int a=exists(sample_path),b=exists(summary_path),c=exists(config_path);
            int d=profile_path?exists(profile_path):0;
            if(a<0 || b<0 || c<0 || d<0)goto output_failure;
            if(a || b || c || d){
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
    double (*generate)(void)=basic?zb_generator(type):zt_generator(type);
    if(precomputed){
        if(!uniform_buffer_init(&source,uniform_bytes,type,seed,uniform_cache)){
            fprintf(stderr,"Cannot allocate/generate/load uniform buffer (%zu bytes)\n",uniform_bytes);goto output_failure;
        }
        if(!(basic?zb_init_buffered(seed,n):zt_init_buffered(seed,n,h,tail)))goto output_failure;
        if(basic)zb_set_buffer(&source);else zt_set_buffer(&source);
        generate=basic?zb_gaussian_buffered:zt_gaussian_buffered;
    }
    /* Optional Gaussian warm-up: fully outside all timed loops. Reset to the
     * requested seed afterward so measured samples retain the original stream. */
    if(warmup){
        volatile double warmup_checksum=0.0;
        sample_progress warm={0};
        sample_batch(generate,precomputed?&source:NULL,warmup,NULL,&warm);
        warmup_checksum=warm.checksum;
        if(source.exhausted){fprintf(stderr,"Uniform buffer exhausted during warm-up after %zu uniforms; benchmark incomplete\n",source.position);goto output_failure;}
        if(precomputed)uniform_buffer_reset(&source);
        if(!isfinite((double)warmup_checksum) ||
           !(basic?zb_init_prng(seed,n,type):zt_init_prng(seed,n,h,tail,type))){
            fprintf(stderr,"Gaussian warm-up or reinitialization failed\n");goto output_failure;
        }
        printf("Warm-up samples:  %" PRIu64 " (outside timing; reset to seed afterward)\n",warmup);
    }
    printf("Algorithm:        %s\n",algorithm);
    printf("Uniform mode:     %s\n",uniform_mode);
    printf("PRNG:             %s\n",prng);
    if(basic) printf("Configuration:    N=%u (H/T not applicable)\n",n);
    else printf("Configuration:    N=%u H=%u T=%u\n",n,h,tail);
    printf("Seed:             %" PRIu64 "\n",seed);
    if(output) printf("Binary output mode: I/O excluded from timing; memory writes affect throughput.\n");
    volatile double checksum=0.0;double sum=0.0,sumsq=0.0;double elapsed;
    sample_progress progress={0};
    if(!output){
        double start=now_seconds();
        if(precomputed)sample_batch(generate,&source,samples,NULL,&progress);
        else for(uint64_t i=0;i<samples;i++){double x=generate();checksum+=x;sum+=x;sumsq+=x*x;}
        elapsed=now_seconds()-start;
    } else {
        elapsed=0.0;
        const uint16_t one=1;
        const int little_endian=*(const unsigned char *)&one==1;
        for(uint64_t done=0;done<samples;){
            size_t count=samples-done<capacity?(size_t)(samples-done):capacity;
            double start=now_seconds();
            uint64_t before=progress.generated;
            if(precomputed)sample_batch(generate,&source,count,buffer,&progress);
            else for(size_t i=0;i<count;i++){
                double x=generate();checksum+=x;sum+=x;sumsq+=x*x;buffer[i]=x;
            }
            elapsed+=now_seconds()-start;
            if(precomputed)count=(size_t)(progress.generated-before);
            else progress.generated+=count;
            if(!little_endian){
                unsigned char *bytes=(unsigned char *)buffer;
                for(size_t i=0;i<count;i++)for(size_t j=0;j<4;j++){
                    unsigned char tmp=bytes[8*i+j];bytes[8*i+j]=bytes[8*i+7-j];bytes[8*i+7-j]=tmp;
                }
            }
            if(fwrite(buffer,sizeof(*buffer),count,f)!=count){perror("write output");goto output_failure;}
            done+=count;
            if(source.exhausted)break;
        }
        int close_result=fclose(f);f=NULL;
        if(close_result!=0){perror("close output");goto output_failure;}
        free(buffer);buffer=NULL;
    }
    if(precomputed){checksum=progress.checksum;sum=progress.sum;sumsq=progress.sumsq;}
    uniforms_consumed=precomputed?source.position:uniform_count_inline(basic,type,seed,n,h,tail,samples);
    if(source.exhausted){
        fprintf(stderr,"Uniform buffer exhausted: consumed %zu uniforms; generated %" PRIu64 " of %" PRIu64 " samples; benchmark incomplete\n",source.position,progress.generated,samples);
        if(summary_file){
            fprintf(summary_file,"{");uniform_metrics(summary_file,algorithm,uniform_mode,progress.generated,uniforms_consumed,uniform_bytes,elapsed,1);
            fprintf(summary_file,",\"prng\":\"%s\",\"num_samples\":%" PRIu64 ",\"sampling_time_seconds\":%.17g,\"throughput_samples_per_second\":null}\n",prng,progress.generated,elapsed);
            fclose(summary_file);summary_file=NULL;
        }
        if(report_json){
            printf("BENCHMARK_JSON: {");uniform_metrics(stdout,algorithm,uniform_mode,progress.generated,uniforms_consumed,uniform_bytes,elapsed,1);
            printf(",\"prng\":\"%s\",\"num_samples\":%" PRIu64 ",\"sampling_time_seconds\":%.17g,\"throughput_samples_per_second\":null}\n",prng,progress.generated,elapsed);
        }
        if(config_file)fclose(config_file);
        uniform_buffer_free(&source);
        free(sample_path);free(summary_path);free(config_path);free(profile_path);
        return 3;
    }
    printf("Uniform values consumed: %" PRIu64 "\n",uniforms_consumed);
    printf("Uniforms/sample:   %.9g\nBuffer size (bytes): %zu\nBuffer utilization: %.9g\nBuffer exhausted: false\nBenchmark complete: true\n",
           (double)uniforms_consumed/samples,precomputed?uniform_bytes:0,
           precomputed?(double)uniforms_consumed/source.capacity:0.0);
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
        fprintf(summary_file,"{");
        uniform_metrics(summary_file,algorithm,uniform_mode,samples,uniforms_consumed,precomputed?uniform_bytes:0,elapsed,0);
        fprintf(summary_file,",");
        if(fprintf(summary_file,
            "\n  \"prng\": \"%s\",\n  \"sampling_time_seconds\": %.17g,\n  \"throughput_samples_per_second\": %.17g,\n"
            "  \"time_per_sample_ns\": %.17g,\n  \"mean\": %.17g,\n"
            "  \"variance\": %.17g,\n  \"checksum\": %.17g,\n"
            "  \"num_samples\": %" PRIu64 "\n}\n",
            prng,elapsed,throughput,ns_per_sample,mean,variance,(double)checksum,samples)<0){
            perror(summary_path);goto output_failure;
        }
        int summary_close=fclose(summary_file);summary_file=NULL;
        if(summary_close!=0){perror(summary_path);goto output_failure;}
        fprintf(config_file,"{\n  \"uniform_mode\": \"%s\",\n  \"uniform_buffer_size_bytes\": %zu,\n",uniform_mode,precomputed?uniform_bytes:0);
        if(fprintf(config_file,"\n  \"algorithm\": \"%s\",\n  \"prng\": \"%s\",\n  \"N\": %u,\n",algorithm,prng,n)<0){
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
    if(profile_prng){
        pcg_profile_counts initialization,sampling;
        if(!(basic?zb_init_profiled(seed,n):zt_init_profiled(seed,n,h,tail))){
            fprintf(stderr,"Cannot reinitialize generator for PRNG profiling\n");goto output_failure;
        }
        volatile double profiled_checksum=0.0;
        double profile_start=now_seconds();
        double (*generate_profiled)(void)=basic?zb_gaussian_profiled:zt_gaussian_profiled;
        for(uint64_t i=0;i<samples;i++)profiled_checksum+=generate_profiled();
        double instrumented_ns=(now_seconds()-profile_start)*1e9/(double)samples;
        if(basic)zb_get_prng_profile_profiled(&initialization,&sampling);
        else zt_get_prng_profile_profiled(&initialization,&sampling);
        if(initialization.overflow || sampling.overflow ||
           sampling.uniform_calls>UINT64_MAX/2 ||
           sampling.pcg32_calls!=2*sampling.uniform_calls ||
           initialization.uniform_calls!=0 || initialization.pcg32_calls!=2){
            fprintf(stderr,"PRNG counter overflow or inconsistent counts\n");goto output_failure;
        }
        volatile double uniform_checksum=0.0;
        double median_uniform_ns=benchmark_uniform(prng_iterations,&uniform_checksum);
        double uniforms_per_sample=(double)sampling.uniform_calls/(double)samples;
        double pcg32_per_sample=(double)sampling.pcg32_calls/(double)samples;
        double estimated_prng_ns=uniforms_per_sample*median_uniform_ns;
        double baseline_ns=elapsed*1e9/(double)samples;
        double fraction=estimated_prng_ns/baseline_ns;
        if(!isfinite(instrumented_ns)||instrumented_ns<=0||
           !isfinite(median_uniform_ns)||median_uniform_ns<=0||
           !isfinite(baseline_ns)||baseline_ns<=0||!isfinite(fraction)||
           !isfinite((double)profiled_checksum)||!isfinite((double)uniform_checksum)){
            fprintf(stderr,"Non-finite PRNG profiling result\n");goto output_failure;
        }
        printf("\nPRNG Profiling\n--------------\n");
        printf("Gaussian samples: %" PRIu64 "\n",samples);
        printf("Initialization uniform calls: %" PRIu64 "\n",initialization.uniform_calls);
        printf("Initialization PCG32 calls: %" PRIu64 "\n",initialization.pcg32_calls);
        printf("Uniform calls: %" PRIu64 "\n",sampling.uniform_calls);
        printf("PCG32 calls: %" PRIu64 "\n",sampling.pcg32_calls);
        printf("Uniforms per Gaussian sample: %.9g\n",uniforms_per_sample);
        printf("PCG32 calls per Gaussian sample: %.9g\n",pcg32_per_sample);
        printf("Median uniform generation time: %.6g ns\n",median_uniform_ns);
        printf("Estimated PRNG time per Gaussian sample: %.6g ns\n",estimated_prng_ns);
        printf("Baseline Gaussian sampling time per sample: %.6g ns\n",baseline_ns);
        printf("Estimated PRNG fraction: %.6g\n",fraction);
        printf("Instrumented Gaussian time per sample: %.6g ns (separate pass)\n",instrumented_ns);
        printf("PRNG microbenchmark: %" PRIu64 " calls/repetition, 5 repetitions, 100000 warm-up calls\n",prng_iterations);
        printf("Compiler: %s; flags: %s; CPU architecture: %s\n",compiler_name(),BENCHMARK_CFLAGS,cpu_architecture());
        if(output_dir){
            profile_file=open_experiment_file(profile_path,overwrite);
            if(!profile_file)goto output_failure;
            created_profile=1;
            if(fprintf(profile_file,
                "{\n  \"gaussian_samples\": %" PRIu64 ",\n  \"initialization_uniform_calls\": %" PRIu64 ",\n"
                "  \"initialization_pcg32_calls\": %" PRIu64 ",\n  \"uniform_calls\": %" PRIu64 ",\n"
                "  \"pcg32_calls\": %" PRIu64 ",\n  \"uniforms_per_gaussian_sample\": %.17g,\n"
                "  \"pcg32_calls_per_gaussian_sample\": %.17g,\n  \"median_uniform_ns\": %.17g,\n"
                "  \"estimated_prng_ns_per_sample\": %.17g,\n  \"baseline_gaussian_ns_per_sample\": %.17g,\n"
                "  \"estimated_prng_fraction\": %.17g,\n  \"instrumented_gaussian_ns_per_sample\": %.17g,\n"
                "  \"microbenchmark_iterations\": %" PRIu64 ",\n  \"microbenchmark_repetitions\": 5,\n"
                "  \"microbenchmark_warmup_iterations\": 100000,\n  \"compiler\": \"%s\",\n"
                "  \"compiler_optimization\": \"%s\",\n  \"compiler_flags\": \"%s\",\n  \"cpu_architecture\": \"%s\"\n}\n",
                samples,initialization.uniform_calls,initialization.pcg32_calls,
                sampling.uniform_calls,sampling.pcg32_calls,uniforms_per_sample,pcg32_per_sample,
                median_uniform_ns,estimated_prng_ns,baseline_ns,fraction,instrumented_ns,
                prng_iterations,compiler_name(),BENCHMARK_OPTIMIZATION,BENCHMARK_CFLAGS,cpu_architecture())<0){
                perror(profile_path);goto output_failure;
            }
            int profile_close=fclose(profile_file);profile_file=NULL;
            if(profile_close!=0){perror(profile_path);goto output_failure;}
        }
    }
    printf("Samples:          %" PRIu64 "\nTime:             %.6f s\nThroughput:       %.3f M samples/s\nTime per sample:  %.2f ns\nChecksum:         %.17g\n",samples,elapsed,(double)samples/elapsed/1e6,elapsed*1e9/(double)samples,(double)checksum);
    printf("Samples/second:   %.3f\n",(double)samples/elapsed);
    if(output_dir)printf("Output directory: %s\n",output_dir);
    else if(output)printf("Output:           %s\n",output);
    if(samples>1)printf("Mean:             %.8f\nVariance:         %.8f\n",sum/(double)samples,(sumsq-sum*sum/(double)samples)/(double)(samples-1));
    if(show && !ZT_ENABLE_COUNTERS) printf("Counters disabled; build with make debug.\n");
    if(show && ZT_ENABLE_COUNTERS){zt_counters c;if(basic){if(type==PRNG_PCG32)zb_get_counters(&c);else zb_get_counters_xoshiro256plus(&c);}else{if(type==PRNG_PCG32)zt_get_counters(&c);else zt_get_counters_xoshiro256plus(&c);}printf("Counters: total=%" PRIu64 " rect=%" PRIu64 " triangle=%" PRIu64 " head=%" PRIu64 " tail=%" PRIu64 " head-refined=%" PRIu64 " tail-refined=%" PRIu64 "\n",c.total_samples,c.rectangle_acceptances,c.triangle_acceptances,c.head_region_hits,c.tail_region_hits,c.head_refined_paths,c.tail_refined_paths);printf("Rejection tests=%" PRIu64 " rejected=%" PRIu64 " retries=%" PRIu64 "\n",c.rejection_region_tests,c.rejected_candidates,c.retries);}
    if(report_json){
        /* Opt-in full precision for experiment collectors. PRNG metadata is
         * additive; existing metric fields and precision are unchanged. */
        printf("BENCHMARK_JSON: {");
        uniform_metrics(stdout,algorithm,uniform_mode,samples,uniforms_consumed,precomputed?uniform_bytes:0,elapsed,0);
        printf(",\"prng\":\"%s\",\"N\":%u,\"H\":%u,\"T\":%u,"
               "\"seed\":%" PRIu64 ",\"num_samples\":%" PRIu64 ",\"warmup_samples\":%" PRIu64 ","
               "\"compiler_optimization\":\"%s\",\"sampling_time_seconds\":%.17g,"
               "\"throughput_samples_per_second\":%.17g,\"time_per_sample_ns\":%.17g,"
               "\"mean\":%.17g,\"variance\":%.17g,\"checksum\":%.17g}\n",
               prng,n,basic?0:h,basic?0:tail,seed,samples,warmup,BENCHMARK_OPTIMIZATION,
               elapsed,(double)samples/elapsed,elapsed*1e9/(double)samples,
               sum/(double)samples,(sumsq-sum*sum/(double)samples)/(double)(samples-1),(double)checksum);
    }
    uniform_buffer_free(&source);
    free(sample_path);free(summary_path);free(config_path);free(profile_path);
    return 0;
output_failure:
    uniform_buffer_free(&source);
    if(f)fclose(f);
    if(summary_file)fclose(summary_file);
    if(config_file)fclose(config_file);
    if(profile_file)fclose(profile_file);
    free(buffer);
    if(output_dir && !overwrite){
        if(created_sample)unlink(sample_path);
        if(created_summary)unlink(summary_path);
        if(created_config)unlink(config_path);
        if(created_profile)unlink(profile_path);
    }
    free(sample_path);free(summary_path);free(config_path);free(profile_path);
    return 1;
}
