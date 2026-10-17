#include "uniform_buffer.h"
#include "gaussian_prng.h"
#include <assert.h>
#include <stdio.h>
uint64_t zt_test_prng_steps;
static uniform_buffer b;
int main(void){
    assert(UNIFORM_BUFFER_SIZE_BYTES==(size_t)2147483648ULL);
    assert(!uniform_buffer_init(&b,7,PRNG_PCG32,1,NULL));
    assert(!uniform_buffer_init(&b,0,PRNG_PCG32,1,NULL));
    for(int type=0;type<2;type++)for(unsigned seed=1;seed<=2;seed++){
        assert(uniform_buffer_init(&b,65536,(prng_type)type,seed,NULL));
        pcg_rng pcg;pcg_seed(&pcg,seed);
        xoshiro256plus_rng xo;xoshiro256plus_seed(&xo,seed);
        if(setjmp(b.exhaustion))assert(0);
        for(unsigned i=0;i<1024;i++){
            double expected=type?xoshiro256plus_uniform(&xo):pcg_uniform(&pcg);
            assert(uniform_buffer_next(&b)==expected);
            assert(b.position==i+1);
        }
        for(int basic=0;basic<2;basic++){
            unsigned layers[]={8,128,256};
            for(unsigned k=0;k<3;k++){
                unsigned n=layers[k];double expected[256];
                assert(basic?zb_init_prng(seed,n,(prng_type)type):zt_init_prng(seed,n,2,4,(prng_type)type));
                double (*inline_gen)(void)=basic?zb_generator((prng_type)type):zt_generator((prng_type)type);
                for(unsigned i=0;i<256;i++)expected[i]=inline_gen();
                uniform_buffer_reset(&b);
                assert(basic?zb_init_buffered(seed,n):zt_init_buffered(seed,n,2,4));
                if(basic)zb_set_buffer(&b);else zt_set_buffer(&b);
                double (*buffered)(void)=basic?zb_gaussian_buffered:zt_gaussian_buffered;
                zt_test_prng_steps=0;
                if(setjmp(b.exhaustion))assert(0);
                for(unsigned i=0;i<256;i++)assert(buffered()==expected[i]);
                assert(zt_test_prng_steps==0); /* Both raw PRNG step functions instrumented. */
                assert(b.position==uniform_count_inline(basic,(prng_type)type,seed,n,2,4,256));
            }
        }
        b.position=b.capacity;
        zt_test_prng_steps=0;
        if(!setjmp(b.exhaustion)){(void)uniform_buffer_next(&b);assert(0);}
        assert(b.exhausted && b.position==b.capacity && zt_test_prng_steps==0);
        uniform_buffer_reset(&b);assert(!b.exhausted && !b.position);
        uniform_buffer_free(&b);
    }
    puts("Uniform sequence, seed, position, exhaustion, exact Gaussian streams and zero PRNG steps PASS");
}
