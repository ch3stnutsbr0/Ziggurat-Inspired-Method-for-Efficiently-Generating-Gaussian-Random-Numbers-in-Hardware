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
