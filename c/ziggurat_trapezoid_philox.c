/* Trapezoid Ziggurat with bit-packed Philox2x64-10 uniforms.
 *
 * Tables are built by the unchanged c/ziggurat_trapezoid.c (included below under private
 * names). Per sample on the common path:
 *   one block (128 bits): word A = [index: top log2 N bits][sign: 1 bit] ... [decision: low 53 bits]
 *                         word B = rectangle position (top 53 bits), or, on the wedge path,
 *                                  u1 = high 32 bits and u2 = low 32 bits
 * so every non-descending sample costs exactly one block. A refinement descent (index 0 into a
 * head table, index N-1 into a tail table) takes a fresh block. Each field is a disjoint set of
 * bits, so the fields are independent uniforms. The rectangle path is bit-identical to
 * zt_gaussian(); the wedge position lies on a d*2^-32 grid instead of d*2^-53 (exact effect:
 * reports/experiment16/analysis/wedge_precision.py). |u1-u2| is computed exactly in integers.
 *
 * Build with -DZT_PHILOX_WEDGE_SECOND_CALL for the earlier variant: the wedge draws a second
 * block and uses two 53-bit uniforms (output law exactly that of zt_gaussian()).
 *
 * Other changes against zt_gaussian(): one 32-byte entry {w, w*2^-53, d*2^-32 (wedge grid), threshold}
 * per strip (one cache line), the rectangle test as an integer compare
 * (u < a  <=>  m < ceil(a*2^53)), and the sign set by OR-ing the sign bit. */
#define zt_init zt_init_tables_philox_
#define zt_gaussian zt_gaussian_reference_philox_
#define zt_get_counters zt_get_counters_philox_
#define zt_reset_counters zt_reset_counters_philox_
#define zt_get_prng_profile zt_get_prng_profile_philox_
#define zt_layers zt_layers_philox_
#define zt_table_x zt_table_x_philox_
#define zt_table_y zt_table_y_philox_
#include "ziggurat_trapezoid.c"
#include "philox2x64.h"
#include "ziggurat_philox.h"
#include "ziggurat_opcount.h"

#define MASK53 ((UINT64_C(1) << 53) - 1)
#ifdef ZT_PHILOX_WEDGE_SECOND_CALL
#define WEDGE_SCALE 0x1p-53
#else
#define WEDGE_SCALE 0x1p-32
#endif

typedef struct { double w, ws, ds; uint64_t thr; } zp_entry;   /* 32 bytes */
static _Alignas(64) zp_entry ztp[1 + 2 * ZT_MAX_REFINEMENT][ZT_MAX_LAYERS];
static philox2x64_rng prng;
static unsigned p_shift, p_sign, p_last, p_nh, p_nt, p_ready;

static void fill(unsigned table, unsigned n) {
    for (unsigned i = 0; i < n; i++) {
        const table_t *t = &tabs[table];
        ztp[table][i] = (zp_entry){t->w[i], t->w[i] * 0x1p-53, t->d[i] * WEDGE_SCALE,
                                   (uint64_t)ceil(t->a[i] * 0x1p53)};
    }
}

int zt_init_philox(uint64_t seed, unsigned n, unsigned h, unsigned t) {
    p_ready = 0;
    if (n < 2 || n > ZT_MAX_LAYERS || (n & (n - 1))) return 0;
    if (!zt_init_tables_philox_(seed, n, h, t)) return 0;
    unsigned k = 0;
    while ((1u << k) < n) k++;
    p_shift = 64 - k; p_sign = 63 - k; p_last = n - 1; p_nh = h; p_nt = t;
    fill(0, n);
    for (unsigned j = 1; j <= h; j++) fill(j, n);
    for (unsigned j = 1; j <= t; j++) fill(ZT_MAX_REFINEMENT + j, n);
    philox2x64_seed(&prng, seed);
    p_ready = 1;
    return 1;
}

double zt_gaussian_philox(void) {
    if (!p_ready) return NAN;
    unsigned tab = 0, lev = 0, side = 0;
    for (;;) {
        philox2x64_block b = philox2x64_next(&prng);
        const uint64_t A = b.v[0], B = b.v[1];
        const unsigned i = (unsigned)(A >> p_shift);
        if (i == 0 && side != 2 && lev < p_nh) { tab = ++lev; side = 1; continue; }
        if (i == p_last && side != 1 && lev < p_nt) { tab = ZT_MAX_REFINEMENT + ++lev; side = 2; continue; }
        const zp_entry *e = &ztp[tab][i];
        double mag;
        if ((A & MASK53) < e->thr) {
            mag = (double)(B >> 11) * e->ws;                                   /* rectangle */
        } else {
#ifdef ZT_PHILOX_WEDGE_SECOND_CALL
            philox2x64_block c = philox2x64_next(&prng);                        /* wedge: 2nd block, 2 x 53 bits */
            int64_t df = (int64_t)(c.v[0] >> 11) - (int64_t)(c.v[1] >> 11);
#else
            int64_t df = (int64_t)(B >> 32) - (int64_t)(B & UINT64_C(0xffffffff));   /* wedge: reuse B, 2 x 32 bits */
#endif
            mag = e->w + (double)(df < 0 ? -df : df) * e->ds;
        }
        uint64_t bits;
        memcpy(&bits, &mag, sizeof bits);
        bits |= ((A >> p_sign) & 1) << 63;
        memcpy(&mag, &bits, sizeof mag);
        return mag;
    }
}

#ifndef ZT_PHILOX_WEDGE_SECOND_CALL
/* Base case only (H = T = 0): exactly one Philox2x64-10 call per sample, no loop.
 *   word A: [layer: top log2 N bits][sign: next bit] ... [rectangle/triangle choice: low 53 bits]
 *   word B: rectangle -> x = w * (top 53 bits); triangle -> x = w + d*|u1 - u2|, u1/u2 = 32-bit halves
 * Same tables, packing and output law as zt_gaussian_philox() at H = T = 0. */
int zt_init_philox_base(uint64_t seed, unsigned n) { return zt_init_philox(seed, n, 0, 0); }

double zt_gaussian_philox_base(void) {
    const philox2x64_block b = philox2x64_next(&prng);
    const uint64_t A = b.v[0], B = b.v[1];
    const zp_entry *e = &ztp[0][A >> p_shift];
    double mag;
    if ((A & MASK53) < e->thr) {
        mag = (double)(B >> 11) * e->ws;
    } else {
        int64_t df = (int64_t)(B >> 32) - (int64_t)(B & UINT64_C(0xffffffff));
        mag = e->w + (double)(df < 0 ? -df : df) * e->ds;
    }
    uint64_t bits;
    memcpy(&bits, &mag, sizeof bits);
    bits |= ((A >> p_sign) & 1) << 63;
    memcpy(&mag, &bits, sizeof mag);
    return mag;
}

/* Fast path + out-of-line refinement, any H and T. The inline path is the base case; only a
 * sample whose root index is a refined strip (0 with H > 0, N-1 with T > 0; probability about
 * 2/N) calls refine(), which descends exactly like zt_gaussian_philox(). Blocks are consumed in
 * the same order, so the output is bit-identical to zt_gaussian_philox() for every H and T. */
static inline double finish(const zp_entry *e, uint64_t A, uint64_t B) {
    double mag;
    if ((A & MASK53) < e->thr) {
        mag = (double)(B >> 11) * e->ws;
    } else {
        int64_t df = (int64_t)(B >> 32) - (int64_t)(B & UINT64_C(0xffffffff));
        mag = e->w + (double)(df < 0 ? -df : df) * e->ds;
    }
    uint64_t bits;
    memcpy(&bits, &mag, sizeof bits);
    bits |= ((A >> p_sign) & 1) << 63;
    memcpy(&mag, &bits, sizeof mag);
    return mag;
}

__attribute__((noinline, cold)) static double refine(int head) {
    unsigned lev = 1, tab = head ? 1 : ZT_MAX_REFINEMENT + 1;
    for (;;) {
        const philox2x64_block b = philox2x64_next(&prng);
        const uint64_t A = b.v[0], B = b.v[1];
        const unsigned i = (unsigned)(A >> p_shift);
        if (head && i == 0 && lev < p_nh) { tab = ++lev; continue; }
        if (!head && i == p_last && lev < p_nt) { tab = ZT_MAX_REFINEMENT + ++lev; continue; }
        return finish(&ztp[tab][i], A, B);
    }
}

double zt_gaussian_philox_fast(void) {
    const philox2x64_block b = philox2x64_next(&prng);
    const uint64_t A = b.v[0], B = b.v[1];
    const unsigned i = (unsigned)(A >> p_shift);
    if (__builtin_expect((i == 0 && p_nh) || (i == p_last && p_nt), 0))
        return refine(i == 0 && p_nh);
    return finish(&ztp[0][i], A, B);
}

/* One block per sample for every H and T ("1call"): the descent indices are taken from word A
 * instead of fresh blocks.
 *   word A: [idx0: k][idx1: k] ... [idx_L-1: k][sign: 1] ... [decision: low D bits]
 *           L = 1 + max(H, T), D = min(53, 63 - k*L)
 *   word B: unchanged (rectangle position, or wedge u1 | u2)
 * Level j of a descent reads idx_j. The fields are disjoint bits, so idx_j is uniform and
 * independent of the earlier indices: the descent weights are exactly those of
 * zt_gaussian_philox(). The only change of law is the decision threshold, ceil(a * 2^D) / 2^D
 * instead of ceil(a * 2^53) / 2^53 (exact effect: reports/experiment16/analysis/onecall_precision.py).
 * Not bit-identical to zt_gaussian_philox(): it consumes fewer blocks and different bits. */
static _Alignas(64) zp_entry ztp1[1 + 2 * ZT_MAX_REFINEMENT][ZT_MAX_LAYERS];
static unsigned q_k, q_sign, q_ready;
static uint64_t q_dmask;

static void fill1(unsigned table, unsigned n, unsigned dbits) {
    for (unsigned i = 0; i < n; i++) {
        zp_entry e = ztp[table][i];
        e.thr = (uint64_t)ceil(tabs[table].a[i] * ldexp(1.0, (int)dbits));
        ztp1[table][i] = e;
    }
}

/* Decision bits D for (N, H, T); 0 if the layout does not fit (fewer than 20 decision bits). */
unsigned zt_philox_1call_decision_bits(unsigned n, unsigned h, unsigned t) {
    unsigned k = 0;
    while ((1u << k) < n) k++;
    unsigned L = 1 + (h > t ? h : t);
    if (k * L + 1 + 20 > 64) return 0;
    unsigned d = 63 - k * L;
    return d > 53 ? 53 : d;
}

int zt_init_philox_1call(uint64_t seed, unsigned n, unsigned h, unsigned t) {
    q_ready = 0;
    const unsigned dbits = zt_philox_1call_decision_bits(n, h, t);
    if (!dbits || !zt_init_philox(seed, n, h, t)) return 0;
    q_k = 64 - p_shift;
    q_sign = 63 - q_k * (1 + (h > t ? h : t));
    q_dmask = (UINT64_C(1) << dbits) - 1;
    fill1(0, n, dbits);
    for (unsigned j = 1; j <= h; j++) fill1(j, n, dbits);
    for (unsigned j = 1; j <= t; j++) fill1(ZT_MAX_REFINEMENT + j, n, dbits);
    q_ready = 1;
    return 1;
}

/* Descent on the bits already drawn: returns the terminal entry. Out of line (about 2/N of samples). */
__attribute__((noinline, cold)) static const zp_entry *descend1(uint64_t A, unsigned i) {
    const unsigned mask = p_last;                       /* N - 1 */
    unsigned lev = 0;
    if (i == 0) {
        while (i == 0 && lev < p_nh) { ++lev; ZOP(icmp); i = (unsigned)(A >> (64 - q_k * (lev + 1))) & mask; }
        ZOP_SET(depth, lev); ZOP_SET(side, 1);
        return &ztp1[lev][i];
    }
    while (i == p_last && lev < p_nt) { ++lev; ZOP(icmp); i = (unsigned)(A >> (64 - q_k * (lev + 1))) & mask; }
    ZOP_SET(depth, lev); ZOP_SET(side, 2);
    return &ztp1[lev ? ZT_MAX_REFINEMENT + lev : 0][i];
}

double zt_philox_1call_map(uint64_t A, uint64_t B) {
    const unsigned i = (unsigned)(A >> p_shift);
    const zp_entry *e = &ztp1[0][i];
    ZOP(attempts); ZOP_N(icmp, 2);                                 /* is it a refined strip (head or tail)? */
    if (__builtin_expect((i == 0 && p_nh) || (i == p_last && p_nt), 0)) e = descend1(A, i);
    double mag;
    ZOP(reads); ZOP(icmp);                                         /* threshold, rectangle test */
    if ((A & q_dmask) < e->thr) {
        ZOP(reads); ZOP(conv); ZOP(fmul); ZOP_SET(outcome, 1);
        mag = (double)(B >> 11) * e->ws;
    } else {
        ZOP_N(reads, 2); ZOP_N(iadd, 2); ZOP(conv); ZOP(fmul); ZOP(fadd); ZOP_SET(outcome, 2);
        int64_t df = (int64_t)(B >> 32) - (int64_t)(B & UINT64_C(0xffffffff));
        mag = e->w + (double)(df < 0 ? -df : df) * e->ds;
    }
    uint64_t bits;
    memcpy(&bits, &mag, sizeof bits);
    bits |= ((A >> q_sign) & 1) << 63;
    memcpy(&mag, &bits, sizeof mag);
    return mag;
}

double zt_gaussian_philox_1call(void) {
    const philox2x64_block b = philox2x64_next(&prng);
    return zt_philox_1call_map(b.v[0], b.v[1]);
}

/* Plain reference for the tests: the layout written out field by field, thresholds from the
 * double tables (not the packed entries). */
double zt_philox_1call_reference(uint64_t A, uint64_t B) {
    const unsigned k = q_k, n = p_last + 1, L = 1 + (p_nh > p_nt ? p_nh : p_nt);
    const unsigned dbits = 63 - k * L > 53 ? 53 : 63 - k * L;
    unsigned idx[ZT_MAX_REFINEMENT + 1];
    for (unsigned j = 0; j < L; j++) idx[j] = (unsigned)((A >> (64 - k * (j + 1))) & (n - 1));
    unsigned table = 0, lev = 0;
    if (idx[0] == 0 && p_nh) { while (lev < p_nh && idx[lev] == 0) lev++; table = lev; }
    else if (idx[0] == n - 1 && p_nt) { while (lev < p_nt && idx[lev] == n - 1) lev++; table = lev ? ZT_MAX_REFINEMENT + lev : 0; }
    const unsigned i = idx[lev];
    const table_t *t = &tabs[table];
    const uint64_t dec = A & ((UINT64_C(1) << dbits) - 1);
    const int sign = (int)((A >> (63 - k * L)) & 1);
    double mag;
    if (dec < (uint64_t)ceil(t->a[i] * ldexp(1.0, (int)dbits))) {
        mag = t->w[i] * ((double)(B >> 11) * 0x1p-53);
    } else {
        uint64_t u1 = B >> 32, u2 = B & UINT64_C(0xffffffff);
        mag = t->w[i] + t->d[i] * ((double)(u1 > u2 ? u1 - u2 : u2 - u1) * 0x1p-32);
    }
    return sign ? -mag : mag;
}
#endif
