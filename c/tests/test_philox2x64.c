/* Known-answer tests for Philox2x64-10 (Random123 kat_vectors).
 * gcc -std=c11 -O2 -I c c/tests/test_philox2x64.c -o test_philox2x64 && ./test_philox2x64 */
#include "philox2x64.h"
#include <inttypes.h>
#include <stdio.h>

int main(void) {
    const uint64_t kat[3][5] = {
        {0, 0, 0, UINT64_C(0xca00a0459843d731), UINT64_C(0x66c24222c9a845b5)},
        {UINT64_MAX, UINT64_MAX, UINT64_MAX, UINT64_C(0x65b021d60cd8310f), UINT64_C(0x4d02f3222f86df20)},
        {UINT64_C(0x243f6a8885a308d3), UINT64_C(0x13198a2e03707344), UINT64_C(0xa4093822299f31d0),
         UINT64_C(0x0a5e742c2997341c), UINT64_C(0xb0f883d38000de5d)},
    };
    int bad = 0;
    for (int i = 0; i < 3; i++) {
        philox2x64_block b = philox2x64_bijection(kat[i][0], kat[i][1], kat[i][2]);
        int ok = b.v[0] == kat[i][3] && b.v[1] == kat[i][4];
        printf("KAT %d: %016" PRIx64 " %016" PRIx64 " %s\n", i, b.v[0], b.v[1], ok ? "ok" : "MISMATCH");
        bad += !ok;
    }
    /* stream == bijection on consecutive counters */
    philox2x64_rng r; philox2x64_seed(&r, 12345);
    for (uint64_t i = 0; i < 1000; i++) {
        philox2x64_block a = philox2x64_next(&r), b = philox2x64_bijection(i, 0, r.key);
        if (a.v[0] != b.v[0] || a.v[1] != b.v[1]) { printf("stream MISMATCH at %llu\n", (unsigned long long)i); return 1; }
    }
    printf("stream: ok (1000 blocks)\n");
    return bad != 0;
}
