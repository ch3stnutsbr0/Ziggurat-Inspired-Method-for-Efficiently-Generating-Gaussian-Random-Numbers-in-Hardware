/* Experiment 21 timing harness: Trapezoid one-block sampler against Classical.
 *
 *   experiment21_bench --variant V --layers N [--head H --tail T] --samples S --warmup W
 *                      --seed X [--repeats R]
 *
 * VARIANT: trapezoid_1call | classical_philox_fast | classical_xoshiro
 *
 * Build modes (same source):
 *   default                                   21a: the PRNG runs inline, inside the timed loop
 *   -DPHILOX_PRECOMPUTED -DXOSHIRO_PRECOMPUTED 21b: the PRNG outputs are generated into a buffer
 *       before timing (same stream); the timed loop only reads them. The buffer ends in an
 *       inaccessible guard page, so an overrun crashes instead of reading garbage.
 *
 * Per repeat: W warm-up samples, then the stream is reset to the seed and S samples are timed,
 * so every repeat times the identical stream (checksum = sum of the samples in order, equal to
 * the Experiment 20 stream-mode checksum). One line "BENCHMARK_JSON: {...}" per repeat.
 * uniforms_per_sample: Philox blocks or xoshiro outputs per timed sample (exact in the
 * precomputed build; -1 inline). */
#define _DEFAULT_SOURCE
#include "gaussian_prng.h"
#include "philox2x64.h"
#include "xoshiro256plus.h"
#include "ziggurat_philox.h"
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#ifdef PHILOX_PRECOMPUTED
const philox2x64_block *philox_buf;
size_t philox_pos;
#endif
#ifdef XOSHIRO_PRECOMPUTED
const uint64_t *xoshiro_buf;
size_t xoshiro_pos;
#endif
#if defined(PHILOX_PRECOMPUTED) && defined(XOSHIRO_PRECOMPUTED)
#define PRECOMPUTED 1
#elif defined(PHILOX_PRECOMPUTED) || defined(XOSHIRO_PRECOMPUTED)
#error "define both PHILOX_PRECOMPUTED and XOSHIRO_PRECOMPUTED"
#else
#define PRECOMPUTED 0
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

#define RUN(fn) for (uint64_t k = 0; k < n; k++) { double x = fn(); c += x; s += x; q += x * x; }
static double run(int v, uint64_t n, double *sum, double *sumsq) {
    double c = 0, s = 0, q = 0;
    switch (v) {
    case TRAP_1CALL: RUN(zt_gaussian_philox_1call); break;
    case CLASSICAL_PHILOX_FAST: RUN(zb_gaussian_philox_fast); break;
    default: RUN(zb_gaussian_xoshiro256plus); break;
    }
    *sum = s; *sumsq = q;
    return c;
}

#if PRECOMPUTED
/* bytes rounded up to pages, followed by one PROT_NONE guard page */
static void *guarded_alloc(size_t bytes) {
    const size_t page = (size_t)sysconf(_SC_PAGESIZE), len = (bytes + page - 1) / page * page;
    unsigned char *p = mmap(NULL, len + page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) return NULL;
    if (mprotect(p + len, page, PROT_NONE)) return NULL;
    return p + len - bytes;                         /* the guard page starts right after the last element */
}
static size_t buffered;                           /* elements generated */
static void reset_stream(int v) { if (v == CLASSICAL_XOSHIRO) xoshiro_pos = 0; else philox_pos = 0; }
static size_t consumed(int v) { return v == CLASSICAL_XOSHIRO ? xoshiro_pos : philox_pos; }
#endif

int main(int argc, char **argv) {
    int v = -1;
    unsigned n = 0, h = 0, t = 0, repeats = 1;
    uint64_t samples = 0, warmup = 0, seed = 0;
    for (int i = 1; i + 1 < argc; i += 2) {
        const char *k = argv[i], *val = argv[i + 1];
        if (!strcmp(k, "--variant")) { for (int j = 0; j < 3; j++) if (!strcmp(val, names[j])) v = j; }
        else if (!strcmp(k, "--layers")) n = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--head")) h = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--tail")) t = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--samples")) samples = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--warmup")) warmup = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--seed")) seed = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--repeats")) repeats = (unsigned)strtoul(val, NULL, 10);
        else { fprintf(stderr, "unknown option %s\n", k); return 2; }
    }
    if (v < 0 || !n || samples < 2 || warmup > samples || !repeats) { fprintf(stderr, "bad arguments\n"); return 2; }
    if (v != TRAP_1CALL) h = t = 0;
    if (!init(v, seed, n, h, t)) { fprintf(stderr, "init failed (N=%u H=%u T=%u)\n", n, h, t); return 2; }
    const unsigned dbits = v == TRAP_1CALL ? zt_philox_1call_decision_bits(n, h, t) : 0;

    double fill_s = 0;
#if PRECOMPUTED
    /* Room for the timed stream (warm-up reads a prefix of it). Expected use per sample:
     * Trapezoid 1 block, Classical Philox <= 1.15 blocks, Classical xoshiro <= 3.4 outputs. */
    double t0 = now();
    if (v == CLASSICAL_XOSHIRO) {
        buffered = (size_t)(6.0 * (double)samples) + 4096;
        uint64_t *buf = guarded_alloc(buffered * sizeof *buf);
        if (!buf) { perror("mmap"); return 1; }
        xoshiro256plus_rng r;
        xoshiro256plus_seed(&r, seed);
        for (size_t i = 0; i < buffered; i++) buf[i] = xoshiro256plus_step(&r);
        xoshiro_buf = buf;
    } else {
        buffered = (size_t)(2.0 * (double)samples) + 4096;
        philox2x64_block *buf = guarded_alloc(buffered * sizeof *buf);
        if (!buf) { perror("mmap"); return 1; }
        philox2x64_rng r;
        philox2x64_seed(&r, seed);
        for (size_t i = 0; i < buffered; i++) buf[i] = philox2x64_step(&r);
        philox_buf = buf;
    }
    fill_s = now() - t0;
#endif

    for (unsigned rep = 0; rep < repeats; rep++) {
        double s, q;
        /* warm-up (tables, caches, frequency), then back to the start of the seed's stream */
#if PRECOMPUTED
        reset_stream(v);
        volatile double w = run(v, warmup, &s, &q);
        reset_stream(v);
#else
        volatile double w = run(v, warmup, &s, &q);
        init(v, seed, n, h, t);
#endif
        (void)w;
        const double t1 = now();
        const double checksum = run(v, samples, &s, &q);
        const double elapsed = now() - t1;
#if PRECOMPUTED
        const double per = (double)consumed(v) / (double)samples;
        const double util = (double)consumed(v) / (double)buffered;
#else
        const double per = -1, util = 0;
#endif
        const double mean = s / (double)samples;
        const double variance = (q - s * s / (double)samples) / (double)(samples - 1);
        printf("BENCHMARK_JSON: {\"variant\":\"%s\",\"uniform_mode\":\"%s\",\"N\":%u,\"H\":%u,\"T\":%u,"
               "\"seed\":%" PRIu64 ",\"repeat\":%u,\"num_samples\":%" PRIu64 ",\"warmup_samples\":%" PRIu64 ","
               "\"complete\":true,\"mean\":%.17g,\"variance\":%.17g,\"checksum\":%.17g,"
               "\"uniforms_per_sample\":%.17g,\"buffer_utilization\":%.17g,\"buffer_fill_seconds\":%.17g,"
               "\"decision_bits\":%u,\"sampling_time_seconds\":%.17g,"
               "\"throughput_million_samples_per_second\":%.17g,\"time_per_sample_ns\":%.17g}\n",
               names[v], PRECOMPUTED ? "precomputed" : "inline", n, h, t, seed, rep + 1, samples, warmup,
               mean, variance, checksum, per, util, fill_s, dbits, elapsed, samples / elapsed / 1e6,
               elapsed * 1e9 / samples);
        fflush(stdout);
    }
    return 0;
}
