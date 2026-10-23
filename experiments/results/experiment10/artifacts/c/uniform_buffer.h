#ifndef UNIFORM_BUFFER_H
#define UNIFORM_BUFFER_H
#include "prng.h"
#include <setjmp.h>
#define UNIFORM_BUFFER_SIZE_BYTES ((size_t)2 * 1024 * 1024 * 1024)
typedef struct {
    double *values;
    size_t capacity, position;
    int exhausted;
    jmp_buf exhaustion;
} uniform_buffer;
/* cache is optional, private to a benchmark session, and never read in timing. */
int uniform_buffer_init(uniform_buffer *b, size_t bytes, prng_type type,
                        uint64_t seed, const char *cache);
void uniform_buffer_reset(uniform_buffer *b);
void uniform_buffer_free(uniform_buffer *b);
/* Caller must establish b->exhaustion with setjmp before sampling. */
static inline double uniform_buffer_next(uniform_buffer *b) {
    if(b->position == b->capacity) {
        b->exhausted=1;
        longjmp(b->exhaustion,1);
    }
    return b->values[b->position++];
}
int zb_init_buffered(uint64_t seed,unsigned n);
int zt_init_buffered(uint64_t seed,unsigned n,unsigned h,unsigned t);
double zb_gaussian_buffered(void);
double zt_gaussian_buffered(void);
void zb_set_buffer(uniform_buffer *b);
void zt_set_buffer(uniform_buffer *b);
uint64_t uniform_count_inline(int basic, prng_type type, uint64_t seed,
                              unsigned n,unsigned h,unsigned t,uint64_t samples);
#endif
