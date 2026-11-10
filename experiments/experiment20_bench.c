/* Experiment 20 harness: Trapezoid one-block sampler (zt_gaussian_philox_1call) against Classical.
 *
 *   experiment20_bench stream --variant V --layers N [--head H --tail T] --samples S --seed X --output PATH
 *       writes S binary64 samples (little-endian) to PATH, for the goodness-of-fit tests
 *   experiment20_bench time   --variant V --layers N [--head H --tail T] --samples S --warmup W --seed X
 *       W warm-up samples, re-seed, then S timed samples (the timed stream equals the stream mode's)
 *
 * VARIANT: trapezoid_1call | classical_philox_fast | classical_xoshiro
 * Both modes end with one line "BENCHMARK_JSON: {...}" (num_samples, complete, mean, variance,
 * checksum = sum of the samples in order, uniforms_per_sample, decision_bits, and in time mode
 * sampling_time_seconds and throughput). uniforms_per_sample counts Philox blocks (Philox variants)
 * or 64-bit calls (xoshiro) and is only available in a build with -DPHILOX_COUNT_BLOCKS
 * -DZT_TEST_PRNG_STEPS (otherwise -1). */
#define _POSIX_C_SOURCE 199309L
#include "gaussian_prng.h"
#include "ziggurat_philox.h"
#include <inttypes.h>
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

enum { TRAP_1CALL, CLASSICAL_PHILOX_FAST, CLASSICAL_XOSHIRO };
static const char *names[] = {"trapezoid_1call", "classical_philox_fast", "classical_xoshiro"};

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + 1e-9 * ts.tv_nsec;
}

static int init(int v, uint64_t seed, unsigned n, unsigned h, unsigned t) {
    return v == TRAP_1CALL ? zt_init_philox_1call(seed, n, h, t)
         : v == CLASSICAL_PHILOX_FAST ? zb_init_philox(seed, n) : zb_init_xoshiro256plus(seed, n);
}

static uint64_t calls(int v) {
#if defined(PHILOX_COUNT_BLOCKS) && defined(ZT_TEST_PRNG_STEPS)
    return v == CLASSICAL_XOSHIRO ? zt_test_prng_steps : philox_blocks;
#else
    (void)v;
    return 0;
#endif
}

typedef struct { volatile double checksum; double sum, sumsq; } stats_t;

/* Direct calls in one loop per variant: no pointer dispatch inside the timed loop. */
#define FILL(fn) for (size_t k = 0; k < m; k++) { double x = fn(); buf[k] = x; }
#define RUN(fn) for (uint64_t k = 0; k < n; k++) { double x = fn(); c += x; s += x; q += x * x; }
static void fill(int v, double *buf, size_t m) {
    switch (v) {
    case TRAP_1CALL: FILL(zt_gaussian_philox_1call); break;
    case CLASSICAL_PHILOX_FAST: FILL(zb_gaussian_philox_fast); break;
    default: FILL(zb_gaussian_xoshiro256plus); break;
    }
}
static void run(int v, uint64_t n, stats_t *st) {
    double c = 0, s = 0, q = 0;
    switch (v) {
    case TRAP_1CALL: RUN(zt_gaussian_philox_1call); break;
    case CLASSICAL_PHILOX_FAST: RUN(zb_gaussian_philox_fast); break;
    default: RUN(zb_gaussian_xoshiro256plus); break;
    }
    st->checksum = c; st->sum = s; st->sumsq = q;
}

int main(int argc, char **argv) {
    if (argc < 2 || (strcmp(argv[1], "stream") && strcmp(argv[1], "time"))) {
        fprintf(stderr, "usage: %s stream|time --variant V --layers N [--head H --tail T] --samples S "
                        "[--warmup W] --seed X [--output PATH]\n", argv[0]);
        return 2;
    }
    const int timing = !strcmp(argv[1], "time");
    int v = -1;
    unsigned n = 0, h = 0, t = 0;
    uint64_t samples = 0, warmup = 0, seed = 0;
    const char *output = NULL;
    for (int i = 2; i + 1 < argc; i += 2) {
        const char *k = argv[i], *val = argv[i + 1];
        if (!strcmp(k, "--variant")) { for (int j = 0; j < 3; j++) if (!strcmp(val, names[j])) v = j; }
        else if (!strcmp(k, "--layers")) n = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--head")) h = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--tail")) t = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--samples")) samples = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--warmup")) warmup = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--seed")) seed = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--output")) output = val;
        else { fprintf(stderr, "unknown option %s\n", k); return 2; }
    }
    if (v < 0 || !n || samples < 2 || (!timing && !output)) { fprintf(stderr, "bad arguments\n"); return 2; }
    if (v != TRAP_1CALL) h = t = 0;
    const unsigned dbits = v == TRAP_1CALL ? zt_philox_1call_decision_bits(n, h, t) : 0;
    if (!init(v, seed, n, h, t)) { fprintf(stderr, "init failed (N=%u H=%u T=%u)\n", n, h, t); return 2; }

    stats_t st = {0, 0, 0};
    double elapsed = 0;
    uint64_t c0;
    if (timing) {
        stats_t warm;
        run(v, warmup, &warm);                          /* tables, caches, frequency */
        if (!isfinite(warm.checksum)) return 1;
        init(v, seed, n, h, t);                         /* timed stream = stream-mode stream */
        c0 = calls(v);
        double t0 = now();
        run(v, samples, &st);
        elapsed = now() - t0;
    } else {
        FILE *f = fopen(output, "wb");
        if (!f) { perror(output); return 1; }
        const size_t cap = (size_t)1 << 20;
        double *buf = malloc(cap * sizeof *buf);
        if (!buf) { fclose(f); return 1; }
        c0 = calls(v);
        double c = 0, s = 0, q = 0;
        for (uint64_t done = 0; done < samples;) {
            const size_t m = samples - done < cap ? (size_t)(samples - done) : cap;
            fill(v, buf, m);
            for (size_t k = 0; k < m; k++) { c += buf[k]; s += buf[k]; q += buf[k] * buf[k]; }
            if (fwrite(buf, sizeof *buf, m, f) != m) { perror("write"); free(buf); fclose(f); return 1; }
            done += m;
        }
        free(buf);
        if (fclose(f)) { perror("close"); return 1; }
        st.checksum = c; st.sum = s; st.sumsq = q;
    }
    const uint64_t used = calls(v) - c0;
    const double mean = st.sum / (double)samples;
    const double variance = (st.sumsq - st.sum * st.sum / (double)samples) / (double)(samples - 1);
#if defined(PHILOX_COUNT_BLOCKS) && defined(ZT_TEST_PRNG_STEPS)
    const double per = (double)used / (double)samples;
#else
    const double per = -1; (void)used;
#endif
    printf("BENCHMARK_JSON: {\"variant\":\"%s\",\"N\":%u,\"H\":%u,\"T\":%u,\"seed\":%" PRIu64 ","
           "\"num_samples\":%" PRIu64 ",\"warmup_samples\":%" PRIu64 ",\"complete\":true,"
           "\"mean\":%.17g,\"variance\":%.17g,\"checksum\":%.17g,\"uniforms_per_sample\":%.17g,"
           "\"decision_bits\":%u", names[v], n, h, t, seed, samples, timing ? warmup : 0,
           mean, variance, (double)st.checksum, per, dbits);
    if (timing)
        printf(",\"sampling_time_seconds\":%.17g,\"throughput_million_samples_per_second\":%.17g,"
               "\"time_per_sample_ns\":%.17g", elapsed, samples / elapsed / 1e6, elapsed * 1e9 / samples);
    printf("}\n");
    return 0;
}
