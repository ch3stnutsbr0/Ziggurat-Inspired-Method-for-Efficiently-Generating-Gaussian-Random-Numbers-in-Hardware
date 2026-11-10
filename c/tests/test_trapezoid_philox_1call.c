/* zt_philox_1call_map() (the optimised one-block sampler) against zt_philox_1call_reference()
 * (the bit layout written out field by field), bit for bit, on random blocks and on blocks whose
 * index fields are forced onto refined strips so that every descent depth is exercised. */
#include "philox2x64.h"
#include "ziggurat_philox.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    static const unsigned HT[][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 2}, {2, 1}, {2, 2}, {3, 1}, {1, 3}, {4, 4}};
    philox2x64_rng r;
    philox2x64_seed(&r, 12345);
    int bad = 0;
    for (unsigned n = 8; n <= 256; n *= 2)
        for (unsigned c = 0; c < sizeof HT / sizeof HT[0]; c++) {
            const unsigned h = HT[c][0], t = HT[c][1];
            if (!zt_init_philox_1call(1, n, h, t)) { printf("N=%u H%u/T%u: layout does not fit (skipped)\n", n, h, t); continue; }
            unsigned k = 0;
            while ((1u << k) < n) k++;
            const unsigned L = 1 + (h > t ? h : t);
            unsigned long mism = 0, total = 0;
            for (unsigned long s = 0; s < 400000; s++) {
                philox2x64_block b = philox2x64_next(&r);
                uint64_t A = b.v[0];
                const unsigned mode = s % 4;                 /* 0: as drawn; 1: head; 2: tail; 3: mixed */
                for (unsigned j = 0; mode && j + 1 < L && j < 8; j++) {
                    const uint64_t f = (mode == 1 || (mode == 3 && (s >> 3) % 2)) ? 0 : (uint64_t)(n - 1);
                    if ((s >> (4 + j)) & 1) break;            /* stop the run at a random depth */
                    const unsigned sh = 64 - k * (j + 1);
                    A = (A & ~((uint64_t)(n - 1) << sh)) | (f << sh);
                }
                const double x = zt_philox_1call_map(A, b.v[1]), y = zt_philox_1call_reference(A, b.v[1]);
                mism += memcmp(&x, &y, sizeof x) != 0;
                total++;
            }
            printf("N=%u H%u/T%u: decision bits %u, %lu blocks, %lu mismatches\n", n, h, t,
                   zt_philox_1call_decision_bits(n, h, t), total, mism);
            bad += mism != 0;
        }
    printf(bad ? "FAIL\n" : "all ok\n");
    return bad != 0;
}
