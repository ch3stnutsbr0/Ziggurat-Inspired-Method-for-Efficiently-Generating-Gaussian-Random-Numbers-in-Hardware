/* Experiment 16 harness: inline-PRNG throughput of Classical and Trapezoid with
 * xoshiro256+ (one 64-bit call per uniform, as in Experiments 10-14) and with
 * bit-packed Philox2x64-10 (one call = 128 bits).
 *
 *   bench time  VARIANT N H T SAMPLES REPEATS SEED  -> one CSV line per repeat
 *   bench count VARIANT N H T SAMPLES SEED          -> PRNG calls per sample + moments
 * VARIANT: classical_xoshiro | trapezoid_xoshiro | classical_philox | trapezoid_philox | trapezoid_philox_2call
 * The count mode needs a build with -DZT_TEST_PRNG_STEPS -DPHILOX_COUNT_BLOCKS. */
#define _POSIX_C_SOURCE 199309L
#include "gaussian_prng.h"
#include "ziggurat_philox.h"
#include "ziggurat_trapezoid.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef PHILOX_COUNT_BLOCKS
uint64_t philox_blocks;
#endif
#ifdef ZT_TEST_PRNG_STEPS
uint64_t zt_test_prng_steps;
#endif

int zb_init_xoshiro256plus(uint64_t seed, unsigned layers);
double zb_gaussian_xoshiro256plus(void);

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + 1e-9 * ts.tv_nsec;
}

/* Direct calls in a separate loop per variant: no pointer dispatch in the timed loop. */
#define LOOP(fn) for (uint64_t k = 0; k < n; k++) s += fn()
static double run(int v, uint64_t n) {
    double s = 0;
    switch (v) {
    case 0: LOOP(zb_gaussian_xoshiro256plus); break;
    case 1: LOOP(zt_gaussian_xoshiro256plus); break;
    case 2: LOOP(zb_gaussian_philox); break;
    case 3: LOOP(zt_gaussian_philox); break;
    case 4: LOOP(zt_gaussian_philox_2call); break;
    }
    return s;
}

int main(int argc, char **argv) {
    static const char *names[] = {"classical_xoshiro", "trapezoid_xoshiro", "classical_philox", "trapezoid_philox",
                                  "trapezoid_philox_2call"};
    if (argc < 8) { fprintf(stderr, "usage: see source header\n"); return 2; }
    int timing = !strcmp(argv[1], "time"), v = -1;
    for (int i = 0; i < 5; i++) if (!strcmp(argv[2], names[i])) v = i;
    unsigned N = (unsigned)atoi(argv[3]), H = (unsigned)atoi(argv[4]), T = (unsigned)atoi(argv[5]);
    uint64_t n = strtoull(argv[6], NULL, 10);
    unsigned reps = timing ? (unsigned)atoi(argv[7]) : 1;
    uint64_t seed = strtoull(argv[timing ? 8 : 7], NULL, 10);
    if (v < 0 || (timing && argc < 9)) { fprintf(stderr, "bad arguments\n"); return 2; }
    int ok = v == 0 ? zb_init_xoshiro256plus(seed, N) : v == 1 ? zt_init_xoshiro256plus(seed, N, H, T)
           : v == 2 ? zb_init_philox(seed, N) : v == 3 ? zt_init_philox(seed, N, H, T)
           : zt_init_philox_2call(seed, N, H, T);
    if (!ok) { fprintf(stderr, "init failed\n"); return 2; }

    if (timing) {
        volatile double sink = run(v, n / 8);                 /* warm-up: tables, caches, frequency */
        for (unsigned r = 0; r < reps; r++) {
            double t0 = now(); double s = run(v, n); double t1 = now();
            sink += s;
            printf("%s,%u,%u,%u,%u,%llu,%.6f,%.3f\n", names[v], N, H, T, r, (unsigned long long)n, t1 - t0,
                   n / (t1 - t0) / 1e6);
        }
        (void)sink;
        return 0;
    }
#if defined(PHILOX_COUNT_BLOCKS) && defined(ZT_TEST_PRNG_STEPS)
    double s1 = 0, s2 = 0, s4 = 0;
    uint64_t c0 = philox_blocks, x0 = zt_test_prng_steps;
    double (*fn)(void) = v == 0 ? zb_gaussian_xoshiro256plus : v == 1 ? zt_gaussian_xoshiro256plus
                       : v == 2 ? zb_gaussian_philox : v == 3 ? zt_gaussian_philox : zt_gaussian_philox_2call;
    for (uint64_t k = 0; k < n; k++) { double g = fn(); s1 += g; s2 += g * g; s4 += g * g * g * g; }
    double calls = v < 2 ? (double)(zt_test_prng_steps - x0) : (double)(philox_blocks - c0);
    printf("%s,%u,%u,%u,%llu,%.6f,%.6f,%.6f,%.6f,%.6f\n", names[v], N, H, T, (unsigned long long)n,
           calls / n, calls * (v < 2 ? 64 : 128) / n, s1 / n, s2 / n, s4 / n);
    return 0;
#else
    fprintf(stderr, "count mode needs -DZT_TEST_PRNG_STEPS -DPHILOX_COUNT_BLOCKS\n");
    return 2;
#endif
}
