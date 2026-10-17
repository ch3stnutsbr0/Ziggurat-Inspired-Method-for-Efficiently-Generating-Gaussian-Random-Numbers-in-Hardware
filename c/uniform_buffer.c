#include "uniform_buffer.h"
#include <stdio.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
/* Header is local/native, never a portable interchange format. */
typedef struct { uint64_t magic, seed, count, type; } cache_header;
int uniform_buffer_init(uniform_buffer *b,size_t bytes,prng_type type,
                        uint64_t seed,const char *cache) {
    memset(b,0,sizeof *b);
    if(sizeof(double)!=8 || !bytes || bytes%sizeof(double) || !prng_name(type))return 0;
    b->capacity=bytes/sizeof(double);
    b->values=malloc(bytes);
    if(!b->values)return 0;
    cache_header expected={UINT64_C(0x5a54554e49463031),seed,b->capacity,(uint64_t)type};
    FILE *f=cache?fopen(cache,"rb"):NULL;
    if(cache && !f && errno!=ENOENT){uniform_buffer_free(b);return 0;}
    if(f) {
        cache_header actual;
        int ok=fread(&actual,sizeof actual,1,f)==1 &&
            memcmp(&actual,&expected,sizeof actual)==0 &&
            fread(b->values,sizeof(double),b->capacity,f)==b->capacity && fgetc(f)==EOF;
        if(fclose(f)!=0)ok=0;
        if(!ok){uniform_buffer_free(b);return 0;}
        return 1;
    }
    if(type==PRNG_PCG32) {
        pcg_rng r;pcg_seed(&r,seed);
        for(size_t i=0;i<b->capacity;i++)b->values[i]=pcg_uniform(&r);
    } else {
        xoshiro256plus_rng r;xoshiro256plus_seed(&r,seed);
        for(size_t i=0;i<b->capacity;i++)b->values[i]=xoshiro256plus_uniform(&r);
    }
    if(cache) {
        f=fopen(cache,"wb");
        if(!f){uniform_buffer_free(b);return 0;}
        int ok=fwrite(&expected,sizeof expected,1,f)==1 &&
            fwrite(b->values,sizeof(double),b->capacity,f)==b->capacity;
        if(fclose(f)!=0)ok=0;
        if(!ok){remove(cache);uniform_buffer_free(b);return 0;}
    }
    return 1;
}
void uniform_buffer_reset(uniform_buffer *b){b->position=0;b->exhausted=0;}
void uniform_buffer_free(uniform_buffer *b){free(b->values);b->values=NULL;b->capacity=b->position=0;}
