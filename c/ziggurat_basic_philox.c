/* Classical Ziggurat with bit-packed Philox2x64-10 uniforms (the same packing as
 * ziggurat_trapezoid_philox.c, so the comparison isolates the algorithm, not the PRNG).
 *
 * Tables come from the unchanged c/ziggurat_basic.c. Per attempt, one block:
 *   word A = [layer: top log2 N bits][sign: 1 bit] ... [position u: low 53 bits]
 *   word B = boundary-strip height test, or the base-strip rectangle/tail choice (top 53 bits)
 * The exponential tail draws one block per candidate (xt and yt from the two words).
 * The sign comes from the accepted attempt; it is independent of acceptance, so the output
 * law is exactly that of zb_gaussian(). x[l-1]*2^-53 is an exact scaling, so candidates
 * are bit-identical to x[l-1]*u. */
#define zb_init zb_init_tables_philox_
#define zb_gaussian zb_gaussian_reference_philox_
#define zb_get_counters zb_get_counters_philox_
#define zb_get_prng_profile zb_get_prng_profile_philox_
#include "ziggurat_basic.c"
#include "philox2x64.h"
#include "ziggurat_philox.h"
#include "ziggurat_opcount.h"

#define MASK53 ((UINT64_C(1) << 53) - 1)

static double xs[ZB_MAX_LAYERS], cutoff_s;
static uint64_t rect_thr;
static philox2x64_rng prng;
static unsigned p_shift, p_sign, p_ready;

int zb_init_philox(uint64_t seed, unsigned n) {
    p_ready = 0;
    if (n & (n - 1)) return 0;
    if (!zb_init_tables_philox_(seed, n)) return 0;
    unsigned k = 0;
    while ((1u << k) < n) k++;
    p_shift = 64 - k; p_sign = 63 - k;
    for (unsigned i = 0; i < n; i++) xs[i] = x[i] * 0x1p-53;
    cutoff_s = cutoff * 0x1p-53;
    rect_thr = (uint64_t)ceil(rectangle_probability * 0x1p53);
    philox2x64_seed(&prng, seed);
    p_ready = 1;
    return 1;
}

double zb_gaussian_philox(void) {
    if (!p_ready) return NAN;
    double mag;
    uint64_t A;
    for (;;) {
        philox2x64_block b = philox2x64_next(&prng);
        A = b.v[0];
        const uint64_t B = b.v[1], m = A & MASK53;
        const unsigned layer = (unsigned)(A >> p_shift);
        if (layer == 0) {
            if ((B >> 11) < rect_thr) {
                mag = (double)m * cutoff_s;
            } else {
                for (;;) {
                    philox2x64_block c = philox2x64_next(&prng);
                    double xt = -log(1.0 - (double)(c.v[0] >> 11) * 0x1p-53) / cutoff;
                    double yt = -log(1.0 - (double)(c.v[1] >> 11) * 0x1p-53);
                    if (2 * yt > xt * xt) { mag = cutoff + xt; break; }
                }
            }
            break;
        }
        const double cand = (double)m * xs[layer - 1];
        if (cand <= x[layer]) { mag = cand; break; }
        const double height = y[layer - 1] + (y[layer] - y[layer - 1]) * ((double)(B >> 11) * 0x1p-53);
        if (height <= exp(-cand * cand / 2.0)) { mag = cand; break; }
    }
    uint64_t bits;
    memcpy(&bits, &mag, sizeof bits);
    bits |= ((A >> p_sign) & 1) << 63;
    memcpy(&mag, &bits, sizeof mag);
    return mag;
}

/* Fast path + out-of-line slow path (the Marsaglia-Tsang code layout). Inline: one block, an
 * upper layer (layer >= 1) and a candidate inside the strip's inner rectangle
 * (cand <= x[layer]), the common case. Everything else (the base strip, i.e. the base rectangle
 * and the exponential tail, and the boundary-strip exp() test with its retries) is in an
 * out-of-line cold function that continues the attempt it is given and then loops exactly like
 * zb_gaussian_philox(). Blocks are consumed in the same order, so the output is bit-identical
 * to zb_gaussian_philox(). */
static inline double zb_sign(double mag, uint64_t A) {
    uint64_t bits;
    memcpy(&bits, &mag, sizeof bits);
    bits |= ((A >> p_sign) & 1) << 63;
    memcpy(&mag, &bits, sizeof mag);
    return mag;
}

__attribute__((noinline, cold)) static double zb_slow(uint64_t A, uint64_t B) {
    ZOP_ONLY(int first = 1;)              /* the first attempt's layer and fast tests are counted by the caller */
    for (;;) {
        const uint64_t m = A & MASK53;
        const unsigned layer = (unsigned)(A >> p_shift);
        ZOP_ONLY(if (!first) { ZOP(attempts); ZOP(icmp); })
        if (layer == 0) {
            double mag;
            ZOP(icmp);
            if ((B >> 11) < rect_thr) {
                ZOP(conv); ZOP(fmul); ZOP_SET(outcome, 2);
                mag = (double)m * cutoff_s;
            } else {
                for (;;) {
                    philox2x64_block c = philox2x64_next(&prng);
                    ZOP(tail_iter);
                    ZOP_N(conv, 2); ZOP_N(fscale, 2); ZOP_N(fadd, 2); ZOP_N(log, 2); ZOP(fdiv);
                    ZOP(fscale); ZOP(fmul); ZOP(fcmp);
                    double xt = -log(1.0 - (double)(c.v[0] >> 11) * 0x1p-53) / cutoff;
                    double yt = -log(1.0 - (double)(c.v[1] >> 11) * 0x1p-53);
                    if (2 * yt > xt * xt) { ZOP(fadd); ZOP_SET(outcome, 3); mag = cutoff + xt; break; }
                }
            }
            return zb_sign(mag, A);
        }
        ZOP_ONLY(if (!first) { ZOP(conv); ZOP(fmul); ZOP_N(reads, 2); ZOP(fcmp); })
        const double cand = (double)m * xs[layer - 1];
        if (cand <= x[layer]) { ZOP_SET(outcome, 1); return zb_sign(cand, A); }
        ZOP_N(reads, 2); ZOP_N(fadd, 2); ZOP(conv); ZOP(fscale); ZOP(fmul);  /* height */
        ZOP(fmul); ZOP(fscale); ZOP(exp); ZOP(fcmp);                         /* exp(-cand^2/2) test */
        const double height = y[layer - 1] + (y[layer] - y[layer - 1]) * ((double)(B >> 11) * 0x1p-53);
        if (height <= exp(-cand * cand / 2.0)) { ZOP_SET(outcome, 4); return zb_sign(cand, A); }
        ZOP(rejections);
        ZOP_ONLY(first = 0;)
        philox2x64_block b = philox2x64_next(&prng);            /* rejected: next attempt */
        A = b.v[0]; B = b.v[1];
    }
}

double zb_gaussian_philox_fast(void) {
    const philox2x64_block b = philox2x64_next(&prng);
    const uint64_t A = b.v[0];
    const unsigned layer = (unsigned)(A >> p_shift);
    ZOP(attempts); ZOP(icmp);
    if (__builtin_expect(layer != 0, 1)) {
        ZOP(conv); ZOP(fmul); ZOP_N(reads, 2); ZOP(fcmp);
        const double cand = (double)(A & MASK53) * xs[layer - 1];
        if (__builtin_expect(cand <= x[layer], 1)) { ZOP_SET(outcome, 1); return zb_sign(cand, A); }
    }
    return zb_slow(A, b.v[1]);
}
