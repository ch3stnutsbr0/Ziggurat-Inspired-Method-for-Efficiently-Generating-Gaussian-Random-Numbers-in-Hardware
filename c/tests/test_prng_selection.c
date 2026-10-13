#include "gaussian_prng.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void reference_vectors(void) {
    xoshiro256plus_rng r = {{1,2,3,4}};
    const uint64_t outputs[] = {
        UINT64_C(0x5), UINT64_C(0xc00000000007), UINT64_C(0xc00018000007),
        UINT64_C(0x8001600018040302), UINT64_C(0x8061900024040305),
        UINT64_C(0xc0617014120f0583), UINT64_C(0x2090780422068642), UINT64_C(0x1038a418171102c6)};
    const uint64_t final_state[] = {UINT64_C(0xd058d4081b070347), UINT64_C(0x60785010040e8140),
        UINT64_C(0xe03808160b0380c3), UINT64_C(0x30204e0f198301a1)};
    const uint64_t seed1[] = {UINT64_C(0x910a2dec89025cc1), UINT64_C(0xbeeb8da1658eec67),
        UINT64_C(0xf893a2eefb32555e), UINT64_C(0x71c18690ee42c90b)};
    for(unsigned i=0;i<8;i++) assert(xoshiro256plus_next(&r)==outputs[i]);
    assert(!memcmp(r.s,final_state,sizeof final_state));
    xoshiro256plus_seed(&r,1); assert(!memcmp(r.s,seed1,sizeof seed1));
    uint64_t seeds[] = {0,1,2,UINT64_MAX};
    for(unsigned i=0;i<4;i++) {
        xoshiro256plus_rng a,b,c;
        xoshiro256plus_seed(&a,seeds[i]); xoshiro256plus_seed(&b,seeds[i]);
        xoshiro256plus_seed(&c,seeds[i]+1);
        assert(a.s[0]|a.s[1]|a.s[2]|a.s[3]);
        assert(memcmp(&a,&c,sizeof a));
        for(unsigned j=0;j<1024;j++) assert(xoshiro256plus_next(&a)==xoshiro256plus_next(&b));
        for(unsigned j=0;j<1024;j++) {
            xoshiro256plus_rng copy=a;
            double expected=(double)(xoshiro256plus_next(&copy)>>11)*0x1.0p-53;
            double u=xoshiro256plus_uniform(&a);
            assert(u==expected && u>=0 && u<1 && floor(u*0x1.0p53)==u*0x1.0p53);
            assert(isfinite(-log(1.0-u)));
        }
    }
    r=(xoshiro256plus_rng){{0,1,0,0}}; assert(xoshiro256plus_uniform(&r)==0);
    r=(xoshiro256plus_rng){{UINT64_MAX,1,0,0}};
    assert(xoshiro256plus_uniform(&r)==1.0-0x1.0p-53);
}
static void samplers(void) {
    unsigned layers[]={8,16,32,64,128,256};
    for(unsigned n=0;n<6;n++) for(int kind=0;kind<2;kind++) for(int type=0;type<2;type++) {
        double saved[256]; prng_type prng=(prng_type)type;
        double (*generate)(void)=kind?zt_generator(prng):zb_generator(prng);
        assert(kind?zt_init_prng(1,layers[n],2,4,prng):zb_init_prng(1,layers[n],prng));
        for(unsigned j=0;j<256;j++){saved[j]=generate();assert(isfinite(saved[j]));}
        assert(kind?zt_init_prng(1,layers[n],2,4,prng):zb_init_prng(1,layers[n],prng));
        for(unsigned j=0;j<256;j++){double x=generate();assert(!memcmp(&x,&saved[j],sizeof x));}
        assert(kind?zt_init_prng(2,layers[n],2,4,prng):zb_init_prng(2,layers[n],prng));
        int differs=0;
        for(unsigned j=0;j<256;j++) differs |= generate()!=saved[j];
        assert(differs);
        if(prng==PRNG_PCG32) {
            assert(kind?zt_init(1,layers[n],2,4):zb_init(1,layers[n]));
            for(unsigned j=0;j<256;j++) assert((kind?zt_gaussian():zb_gaussian())==saved[j]);
        }
    }
    /* Independent PCG/xoshiro singleton state: initializing one preserves the other. */
    assert(zb_init_prng(1,128,PRNG_PCG32)); double first=zb_gaussian();
    assert(zb_init_prng(1,128,PRNG_PCG32));
    assert(zb_init_prng(99,128,PRNG_XOSHIRO256PLUS)); assert(zb_gaussian()==first);
    assert(!zb_init_prng(1,128,(prng_type)99)); assert(zb_generator((prng_type)99)==NULL);
    assert(!zt_init_prng(1,128,2,4,(prng_type)99)); assert(zt_generator((prng_type)99)==NULL);
}
int main(void) {
    prng_type type; assert(prng_parse("pcg32",&type)&&type==PRNG_PCG32);
    assert(prng_parse("xoshiro256plus",&type)&&type==PRNG_XOSHIRO256PLUS);
    assert(!prng_parse("xoshiro256++",&type)); assert(!prng_parse("",&type));
    reference_vectors(); samplers();
    puts("Reference output/state, SplitMix64 vectors, endpoints, determinism, seed changes, both samplers and PCG adapter PASS");
    return 0;
}
