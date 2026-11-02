/* Experiment 14 timing harness: per-sample cost of the unmodified C samplers.
 *
 * Links the existing builds (every c/ source except benchmark.c); the sampler sources are not modified.
 *   precomputed: zb_/zt_gaussian_buffered on a 2 GiB xoshiro256+ buffer (sampler only)
 *   inline:      zb_/zt_gaussian_xoshiro256plus (sampler + PRNG)
 *
 * Passes, each from a fresh seed so every pass sees the same stream:
 *   --perf        whole loop, hardware counters enabled around the loop only (two counter groups,
 *                 two passes, so nothing is multiplexed)
 *   --blocks L    rdtscp around blocks of B samples for each B in the comma list L
 *   --counts      precomputed only: uniforms used per sample (buffer position difference), and at
 *                 B = 1 the joint (uniforms, ticks) histogram
 * Output: one JSON object per line on stdout. Raw samples are never stored.
 *
 * Build: see experiments/experiment14.py (gcc -O2, same flags as c/benchmark).
 */
#define _GNU_SOURCE
#include "../c/uniform_buffer.h"
#include "../c/gaussian_prng.h"
#include "../c/ziggurat_trapezoid.h"
#include <errno.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <math.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#include <x86intrin.h>

#define TICK_BINS 65536u          /* exact histogram below this many ticks per block */
#define MAX_OVERFLOW 1000000u     /* raw tick values kept above it */
#define MAX_UNIFORMS 64u          /* uniforms-per-sample histogram size (last bin = 63 or more) */
#define JOINT_TICKS 4096u         /* joint (uniforms, ticks) histogram at B = 1; last bin = 4095 or more */

static double (*generate)(void);
static int basic, precomputed;
static unsigned n, h, t;
static uint64_t seed;
static uniform_buffer buf;
/* Globals, not locals: they survive longjmp, and like benchmark.c's volatile checksum they are
 * stored on every sample. */
static double sum;
static uint64_t n_over;

static void die(const char *msg) { fprintf(stderr, "experiment14_timing: %s\n", msg); exit(2); }

static void reset(void) {
    int ok;
    if (precomputed) {
        uniform_buffer_reset(&buf);
        ok = basic ? zb_init_buffered(seed, n) : zt_init_buffered(seed, n, h, t);
        if (basic) zb_set_buffer(&buf); else zt_set_buffer(&buf);
    } else {
        ok = basic ? zb_init_xoshiro256plus(seed, n) : zt_init_xoshiro256plus(seed, n, h, t);
    }
    if (!ok) die("sampler initialization failed");
}

static inline uint64_t tick_start(void) { _mm_lfence(); uint64_t v = __rdtsc(); _mm_lfence(); return v; }
static inline uint64_t tick_end(void) { unsigned aux; uint64_t v = __rdtscp(&aux); _mm_lfence(); return v; }

static double now_s(void) { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec + 1e-9 * ts.tv_nsec; }

static double tsc_hz(void) {
    double best = 0;
    for (int k = 0; k < 3; k++) {   /* median-free: keep the last of three 0.2 s calibrations */
        double s0 = now_s(); uint64_t c0 = tick_start();
        while (now_s() - s0 < 0.2) {}
        double s1 = now_s(); uint64_t c1 = tick_end();
        best = (double)(c1 - c0) / (s1 - s0);
    }
    return best;
}

/* ---------------------------------------------------------------- perf counters */

typedef struct { const char *name; uint32_t type; uint64_t config; } event_t;
#define CACHE(id, op, res) ((id) | ((op) << 8) | ((res) << 16))
static const event_t group_a[] = {
    {"cycles", PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES},
    {"instructions", PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS},
    {"branches", PERF_TYPE_HARDWARE, PERF_COUNT_HW_BRANCH_INSTRUCTIONS},
    {"branch_misses", PERF_TYPE_HARDWARE, PERF_COUNT_HW_BRANCH_MISSES}};
static const event_t group_b[] = {
    {"cycles_b", PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES},
    {"l1d_loads", PERF_TYPE_HW_CACHE, CACHE(PERF_COUNT_HW_CACHE_L1D, PERF_COUNT_HW_CACHE_OP_READ, PERF_COUNT_HW_CACHE_RESULT_ACCESS)},
    {"l1d_misses", PERF_TYPE_HW_CACHE, CACHE(PERF_COUNT_HW_CACHE_L1D, PERF_COUNT_HW_CACHE_OP_READ, PERF_COUNT_HW_CACHE_RESULT_MISS)}};

static int open_group(const event_t *ev, unsigned k, int *fds) {
    for (unsigned i = 0; i < k; i++) {
        struct perf_event_attr a;
        memset(&a, 0, sizeof a);
        a.size = sizeof a; a.type = ev[i].type; a.config = ev[i].config;
        a.disabled = i == 0; a.exclude_kernel = 1; a.exclude_hv = 1;
        a.read_format = PERF_FORMAT_GROUP | PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
        fds[i] = (int)syscall(SYS_perf_event_open, &a, 0, -1, i ? fds[0] : -1, 0);
        if (fds[i] < 0) return 0;
    }
    return 1;
}

static void perf_pass(const event_t *ev, unsigned k, const char *group) {
    int fds[8];
    if (!open_group(ev, k, fds)) {
        printf("{\"kind\":\"perf\",\"group\":\"%s\",\"error\":\"perf_event_open: %s\"}\n", group, strerror(errno));
        return;
    }
    reset();
    sum = 0;
    uint64_t samples = (uint64_t)strtoull(getenv("E14_SAMPLES"), NULL, 10);
    if (precomputed && setjmp(buf.exhaustion)) die("uniform buffer exhausted");
    double s0 = now_s(); uint64_t c0 = tick_start();
    ioctl(fds[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
    ioctl(fds[0], PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
    for (uint64_t i = 0; i < samples; i++) sum += generate();
    ioctl(fds[0], PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
    uint64_t c1 = tick_end(); double s1 = now_s();
    uint64_t values[3 + 8];
    if (read(fds[0], values, sizeof values) < (ssize_t)((3 + k) * sizeof(uint64_t))) die("perf read failed");
    printf("{\"kind\":\"perf\",\"group\":\"%s\",\"time_s\":%.9f,\"ticks\":%" PRIu64 ",\"checksum\":%.17g,"
           "\"time_enabled\":%" PRIu64 ",\"time_running\":%" PRIu64 ",\"uniforms\":%zu",
           group, s1 - s0, c1 - c0, sum, values[1], values[2], precomputed ? buf.position : (size_t)0);
    for (unsigned i = 0; i < k; i++) printf(",\"%s\":%" PRIu64, ev[i].name, values[3 + i]);
    printf("}\n");
    for (unsigned i = 0; i < k; i++) close(fds[i]);
}

/* ---------------------------------------------------------------- block timing */

static uint64_t *hist, *overflow, *joint, ucount[MAX_UNIFORMS];

static void print_hist(const char *kind, unsigned block) {
    printf("{\"kind\":\"%s\",\"block\":%u,\"checksum\":%.17g,\"bins\":[", kind, block, sum);
    int first = 1;
    for (unsigned i = 0; i < TICK_BINS; i++)
        if (hist[i]) { printf("%s[%u,%" PRIu64 "]", first ? "" : ",", i, hist[i]); first = 0; }
    printf("],\"overflow\":[");
    for (uint64_t i = 0; i < n_over && i < MAX_OVERFLOW; i++) printf("%s%" PRIu64, i ? "," : "", overflow[i]);
    printf("],\"overflow_count\":%" PRIu64 "}\n", n_over);
}

static void record(uint64_t d) {
    if (d < TICK_BINS) hist[d]++;
    else { if (n_over < MAX_OVERFLOW) overflow[n_over] = d; n_over++; }
}

/* Empty block with the same timing code: the timer overhead to subtract. */
static void overhead_pass(void) {
    memset(hist, 0, TICK_BINS * sizeof *hist);
    n_over = 0; sum = 0;
    for (unsigned i = 0; i < 1000000u; i++) { uint64_t a = tick_start(); uint64_t b = tick_end(); record(b - a); }
    print_hist("overhead", 0);
}

static void block_pass(unsigned block, uint64_t samples, int counts) {
    memset(hist, 0, TICK_BINS * sizeof *hist);
    if (counts) { memset(joint, 0, (size_t)MAX_UNIFORMS * JOINT_TICKS * sizeof *joint); memset(ucount, 0, sizeof ucount); }
    uint64_t blocks = samples / block;
    n_over = 0; sum = 0;
    reset();
    if (precomputed && setjmp(buf.exhaustion)) die("uniform buffer exhausted");
    for (uint64_t b = 0; b < blocks; b++) {
        size_t p0 = precomputed ? buf.position : 0;
        uint64_t a = tick_start();
        for (unsigned j = 0; j < block; j++) sum += generate();
        uint64_t d = tick_end() - a;
        record(d);
        if (counts) {
            size_t u = buf.position - p0;
            if (u >= MAX_UNIFORMS) u = MAX_UNIFORMS - 1;
            ucount[u]++;
            joint[u * JOINT_TICKS + (d < JOINT_TICKS ? d : JOINT_TICKS - 1)]++;
        }
    }
    print_hist("blocks", block);
    if (counts) {
        printf("{\"kind\":\"joint\",\"block\":%u,\"cells\":[", block);
        int first = 1;
        for (unsigned u = 0; u < MAX_UNIFORMS; u++)
            for (unsigned d = 0; d < JOINT_TICKS; d++)
                if (joint[u * JOINT_TICKS + d]) {
                    printf("%s[%u,%u,%" PRIu64 "]", first ? "" : ",", u, d, joint[u * JOINT_TICKS + d]); first = 0;
                }
        printf("]}\n");
    }
}

/* Uniforms per sample without timing (fast; used by the exact-count check). */
static void count_pass(uint64_t samples) {
    memset(ucount, 0, sizeof ucount);
    sum = 0;
    reset();
    if (setjmp(buf.exhaustion)) die("uniform buffer exhausted");
    for (uint64_t i = 0; i < samples; i++) {
        size_t p0 = buf.position;
        sum += generate();
        size_t u = buf.position - p0;
        ucount[u < MAX_UNIFORMS ? u : MAX_UNIFORMS - 1]++;
    }
    printf("{\"kind\":\"counts\",\"checksum\":%.17g,\"uniforms_total\":%zu,\"hist\":[", sum, buf.position);
    for (unsigned u = 0; u < MAX_UNIFORMS; u++) printf("%s%" PRIu64, u ? "," : "", ucount[u]);
    printf("]}\n");
}

int main(int argc, char **argv) {
    const char *algorithm = NULL, *mode = "precomputed", *blocks = NULL;
    uint64_t samples = 33554432, bytes = UNIFORM_BUFFER_SIZE_BYTES;
    int do_perf = 0, do_counts = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--algorithm") && i + 1 < argc) algorithm = argv[++i];
        else if (!strcmp(argv[i], "--layers") && i + 1 < argc) n = (unsigned)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--head") && i + 1 < argc) h = (unsigned)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--tail") && i + 1 < argc) t = (unsigned)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--seed") && i + 1 < argc) seed = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--samples") && i + 1 < argc) samples = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--uniform-mode") && i + 1 < argc) mode = argv[++i];
        else if (!strcmp(argv[i], "--uniform-buffer-bytes") && i + 1 < argc) bytes = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--blocks") && i + 1 < argc) blocks = argv[++i];
        else if (!strcmp(argv[i], "--perf")) do_perf = 1;
        else if (!strcmp(argv[i], "--counts")) do_counts = 1;
        else die("usage: --algorithm basic|trapezoid --layers N [--head H --tail T] --seed S [--samples n] "
                 "[--uniform-mode precomputed|inline] [--uniform-buffer-bytes B] [--perf] [--blocks 1,16,256] [--counts]");
    }
    if (!algorithm || (strcmp(algorithm, "basic") && strcmp(algorithm, "trapezoid"))) die("--algorithm basic|trapezoid");
    basic = !strcmp(algorithm, "basic");
    precomputed = !strcmp(mode, "precomputed");
    if (!precomputed && strcmp(mode, "inline")) die("--uniform-mode precomputed|inline");
    if (do_counts && !precomputed) die("--counts needs --uniform-mode precomputed");
    if (basic) h = t = 0;
    generate = precomputed ? (basic ? zb_gaussian_buffered : zt_gaussian_buffered)
                           : (basic ? zb_gaussian_xoshiro256plus : zt_gaussian_xoshiro256plus);
    char env[32]; snprintf(env, sizeof env, "%" PRIu64, samples); setenv("E14_SAMPLES", env, 1);

    if (precomputed && !uniform_buffer_init(&buf, bytes, PRNG_XOSHIRO256PLUS, seed, NULL)) die("uniform buffer allocation failed");
    hist = calloc(TICK_BINS, sizeof *hist);
    overflow = calloc(MAX_OVERFLOW, sizeof *overflow);
    joint = do_counts ? calloc((size_t)MAX_UNIFORMS * JOINT_TICKS, sizeof *joint) : NULL;
    if (!hist || !overflow || (do_counts && !joint)) die("out of memory");

    unsigned aux; (void)__rdtscp(&aux);
    printf("{\"kind\":\"meta\",\"algorithm\":\"%s\",\"N\":%u,\"H\":%u,\"T\":%u,\"seed\":%" PRIu64 ",\"samples\":%" PRIu64 ","
           "\"uniform_mode\":\"%s\",\"cpu\":%d,\"tsc_hz\":%.6f}\n",
           algorithm, n, h, t, seed, samples, mode, sched_getcpu(), tsc_hz());
    fflush(stdout);
    if (do_perf) {
        perf_pass(group_a, sizeof group_a / sizeof *group_a, "a");
        perf_pass(group_b, sizeof group_b / sizeof *group_b, "b");
    }
    if (blocks) {
        overhead_pass();
        char *list = strdup(blocks);
        for (char *tok = strtok(list, ","); tok; tok = strtok(NULL, ",")) {
            unsigned b = (unsigned)strtoul(tok, NULL, 10);
            if (!b) die("block size must be positive");
            block_pass(b, samples, do_counts && b == 1);
            fflush(stdout);
        }
        free(list);
    } else if (do_counts) {
        count_pass(samples);
    }
    if (precomputed) uniform_buffer_free(&buf);
    return 0;
}
