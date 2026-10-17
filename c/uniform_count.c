#include "uniform_buffer.h"
int zb_init_counted(uint64_t,unsigned);
int zt_init_counted(uint64_t,unsigned,unsigned,unsigned);
double zb_gaussian_counted(void);
uint64_t zb_uniform_calls_counted(void);
double zt_gaussian_counted(void);
uint64_t zt_uniform_calls_counted(void);
int zb_init_counted_xoshiro(uint64_t,unsigned);
int zt_init_counted_xoshiro(uint64_t,unsigned,unsigned,unsigned);
double zb_gaussian_counted_xoshiro(void);
uint64_t zb_uniform_calls_counted_xoshiro(void);
double zt_gaussian_counted_xoshiro(void);
uint64_t zt_uniform_calls_counted_xoshiro(void);
uint64_t uniform_count_inline(int basic,prng_type type,uint64_t seed,
 unsigned n,unsigned h,unsigned t,uint64_t samples){
 double (*generate)(void);uint64_t (*count)(void);
 if(type==PRNG_PCG32){
  if(basic){zb_init_counted(seed,n);generate=zb_gaussian_counted;count=zb_uniform_calls_counted;}
  else{zt_init_counted(seed,n,h,t);generate=zt_gaussian_counted;count=zt_uniform_calls_counted;}
 }else{
  if(basic){zb_init_counted_xoshiro(seed,n);generate=zb_gaussian_counted_xoshiro;count=zb_uniform_calls_counted_xoshiro;}
  else{zt_init_counted_xoshiro(seed,n,h,t);generate=zt_gaussian_counted_xoshiro;count=zt_uniform_calls_counted_xoshiro;}
 }
 (void)count();
 for(uint64_t i=0;i<samples;i++)(void)generate();
 return count();
}
