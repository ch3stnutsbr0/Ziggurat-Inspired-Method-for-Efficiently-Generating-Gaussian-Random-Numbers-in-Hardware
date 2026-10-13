#include "pcg_rng.h"
#include "ziggurat_basic.h"
#include "ziggurat_trapezoid.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static void test_raw_pcg(void) {
    pcg_rng r={0};
    pcg_profile p={0};
    pcg_profile_reset(&p);
    pcg_profile_initialization(&p);
    pcg_seed_profiled(&r,&p,1);
    assert(p.initialization.uniform_calls==0);
    assert(p.initialization.pcg32_calls==2);
    pcg_profile_sampling(&p);
    (void)pcg_uniform_profiled(&r,&p);
    assert(p.sampling.uniform_calls==1);
    assert(p.sampling.pcg32_calls==2);
    (void)pcg_next_profiled(&r,&p);
    assert(p.sampling.uniform_calls==1);
    assert(p.sampling.pcg32_calls==3);
    p.sampling.uniform_calls=UINT64_MAX;
    (void)pcg_uniform_profiled(&r,&p);
    assert(p.sampling.overflow && p.sampling.uniform_calls==UINT64_MAX);
    pcg_profile_reset(&p);
    assert(!p.sampling.overflow && !p.sampling.uniform_calls && !p.sampling.pcg32_calls);
}

static int initialize(int basic,int refined,int profile) {
    if(basic)return profile?zb_init_profiled(123,128):zb_init(123,128);
    return profile?zt_init_profiled(123,8,refined?2:0,refined?4:0):
        zt_init(123,8,refined?2:0,refined?4:0);
}
static double generate(int basic,int profile) {
    if(basic)return profile?zb_gaussian_profiled():zb_gaussian();
    return profile?zt_gaussian_profiled():zt_gaussian();
}
static void get_profile(int basic,int profile,pcg_profile_counts *init,pcg_profile_counts *sample) {
    if(basic){
        if(profile)zb_get_prng_profile_profiled(init,sample);
        else zb_get_prng_profile(init,sample);
    }else{
        if(profile)zt_get_prng_profile_profiled(init,sample);
        else zt_get_prng_profile(init,sample);
    }
}
static void test_algorithm(int basic,int refined) {
    enum { count=10000 };
    double baseline[count];
    pcg_profile_counts init,sample;
    assert(initialize(basic,refined,0));
    for(int i=0;i<count;i++)baseline[i]=generate(basic,0);
    get_profile(basic,0,&init,&sample);
    assert(init.pcg32_calls==0 && sample.pcg32_calls==0);

    assert(initialize(basic,refined,1));
    get_profile(basic,1,&init,&sample);
    assert(init.uniform_calls==0 && init.pcg32_calls==2);
    assert(sample.uniform_calls==0 && sample.pcg32_calls==0);
    for(int i=0;i<count;i++) {
        double value=generate(basic,1);
        assert(memcmp(&value,&baseline[i],sizeof value)==0);
    }
    get_profile(basic,1,&init,&sample);
    assert(!sample.overflow && sample.uniform_calls>=3*count);
    assert(sample.pcg32_calls==2*sample.uniform_calls);
    pcg_profile_counts first=sample;

    assert(initialize(basic,refined,1));
    get_profile(basic,1,&init,&sample);
    assert(init.pcg32_calls==2 && sample.uniform_calls==0 && sample.pcg32_calls==0);
    for(int i=0;i<count;i++)assert(generate(basic,1)==baseline[i]);
    get_profile(basic,1,&init,&sample);
    assert(sample.uniform_calls==first.uniform_calls && sample.pcg32_calls==first.pcg32_calls);

    assert(initialize(basic,refined,0));
    get_profile(basic,0,&init,&sample);
    assert(init.pcg32_calls==0 && sample.pcg32_calls==0);
}
int main(void) {
    test_raw_pcg();
    test_algorithm(1,0);
    test_algorithm(0,0);
    test_algorithm(0,1);
    puts("PRNG profile counters, reset, and sequence equality PASS");
    return 0;
}
