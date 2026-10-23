#include "gaussian_prng.h"
#include <string.h>
int prng_parse(const char *name, prng_type *type) {
    if (!strcmp(name, "pcg32")) *type = PRNG_PCG32;
    else if (!strcmp(name, "xoshiro256plus")) *type = PRNG_XOSHIRO256PLUS;
    else return 0;
    return 1;
}
const char *prng_name(prng_type type) {
    switch (type) {
        case PRNG_PCG32: return "pcg32";
        case PRNG_XOSHIRO256PLUS: return "xoshiro256plus";
        default: return NULL;
    }
}
int zb_init_prng(uint64_t seed, unsigned n, prng_type type) {
    switch (type) {
        case PRNG_PCG32: return zb_init(seed, n);
        case PRNG_XOSHIRO256PLUS: return zb_init_xoshiro256plus(seed, n);
        default: return 0;
    }
}
int zt_init_prng(uint64_t seed, unsigned n, unsigned h, unsigned t, prng_type type) {
    switch (type) {
        case PRNG_PCG32: return zt_init(seed, n, h, t);
        case PRNG_XOSHIRO256PLUS: return zt_init_xoshiro256plus(seed, n, h, t);
        default: return 0;
    }
}
double (*zb_generator(prng_type type))(void) {
    return type == PRNG_PCG32 ? zb_gaussian :
        type == PRNG_XOSHIRO256PLUS ? zb_gaussian_xoshiro256plus : NULL;
}
double (*zt_generator(prng_type type))(void) {
    return type == PRNG_PCG32 ? zt_gaussian :
        type == PRNG_XOSHIRO256PLUS ? zt_gaussian_xoshiro256plus : NULL;
}
