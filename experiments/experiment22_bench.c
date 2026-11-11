/* Experiment 22 harness: distribution of the time per sample (core cycles), Trapezoid one-block
 * sampler against Classical Philox fast path.
 *
 *   experiment22_bench --variant V --layers N [--head H --tail T] --samples S --seed X
 *                      --window W [--warmup K]
 *
 * VARIANT: trapezoid_1call | classical_philox_fast
 * W = 1: every sample is timed on its own, fenced (lfence) on both sides, so the value is the
 *        latency of that one sample; samples do not overlap.
 * W > 1: W consecutive samples run unfenced (as in a normal loop) and the window is timed; the
 *        value is the window's cycles / W, i.e. the throughput over that window.
 * Time is read with rdpmc from the core-cycle counter (user mode only): it counts real core
 * cycles whatever the clock frequency, and cycles spent in interrupt handlers are not counted.
 * The fixed cost of a fenced counter read pair is calibrated in-process and subtracted.
 *
 * Build modes (same source), as in Experiment 21:
 *   default                     PRNG inline
 *   -DPHILOX_PRECOMPUTED        PRNG outputs generated into a buffer outside the timed region:
 *       the buffer (16384 blocks, 256 KiB) stays in L2; it is refilled with the next blocks of
 *       the stream (untimed) before every chunk of 8192 samples. A buffer streamed from DRAM was
 *       tried first and gave occasional ~1000-cycle memory stalls unrelated to the sampler.
 *
 * Output: one line "BENCHMARK_JSON: {...}" with summary values and the histogram of
 * cycles per sample (window mode: per-window cycles, divide by W) as [value, count] pairs. */
#define _GNU_SOURCE
#include "gaussian_prng.h"
#include "philox2x64.h"
#include "ziggurat_philox.h"
#include <inttypes.h>
#include <linux/perf_event.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#include <x86intrin.h>

#ifdef PHILOX_PRECOMPUTED
const philox2x64_block *philox_buf;
size_t philox_pos;
#define PRECOMPUTED 1
#else
#define PRECOMPUTED 0
#endif

enum { TRAP_1CALL, CLASSICAL_PHILOX_FAST };
static const char *names[] = {"trapezoid_1call", "classical_philox_fast"};
#define CHUNK 8192u                           /* samples per refill (precomputed mode) */
#define BINS (1u << 20)                     /* histogram range in cycles (per sample or per window) */

static struct perf_event_mmap_page *pc;
static unsigned pmc_index;
static uint64_t pmc_mask;

static void counter_open(void) {
    struct perf_event_attr a;
    memset(&a, 0, sizeof a);
    a.size = sizeof a;
    a.type = PERF_TYPE_HARDWARE;
    a.config = PERF_COUNT_HW_CPU_CYCLES;
    a.exclude_kernel = 1;
    a.exclude_hv = 1;
    int fd = (int)syscall(SYS_perf_event_open, &a, 0, -1, -1, 0);
    if (fd < 0) { perror("perf_event_open"); exit(1); }
    pc = mmap(NULL, (size_t)sysconf(_SC_PAGESIZE), PROT_READ, MAP_SHARED, fd, 0);
    if (pc == MAP_FAILED) { perror("mmap"); exit(1); }
    if (!pc->cap_user_rdpmc || !pc->index) { fprintf(stderr, "rdpmc not available\n"); exit(1); }
    pmc_index = pc->index - 1;
    pmc_mask = pc->pmc_width >= 64 ? ~0ull : (1ull << pc->pmc_width) - 1;
}
static inline uint64_t cyc(void) { return __rdpmc((int)pmc_index); }

static inline double sample(int v) {
    return v == TRAP_1CALL ? zt_gaussian_philox_1call() : zb_gaussian_philox_fast();
}

int main(int argc, char **argv) {
    int v = -1;
    unsigned n = 0, h = 0, t = 0, W = 1;
    uint64_t samples = 0, warmup = 100000, seed = 0;
    for (int i = 1; i + 1 < argc; i += 2) {
        const char *k = argv[i], *val = argv[i + 1];
        if (!strcmp(k, "--variant")) { for (int j = 0; j < 2; j++) if (!strcmp(val, names[j])) v = j; }
        else if (!strcmp(k, "--layers")) n = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--head")) h = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--tail")) t = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--samples")) samples = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--warmup")) warmup = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--seed")) seed = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--window")) W = (unsigned)strtoul(val, NULL, 10);
        else { fprintf(stderr, "unknown option %s\n", k); return 2; }
    }
    if (v < 0 || !n || !W || samples < W) { fprintf(stderr, "bad arguments\n"); return 2; }
    if (v != TRAP_1CALL) h = t = 0;
    const int ok = v == TRAP_1CALL ? zt_init_philox_1call(seed, n, h, t) : zb_init_philox(seed, n);
    if (!ok) { fprintf(stderr, "init failed\n"); return 2; }

#if PRECOMPUTED
    /* Classical needs at most ~1.15 blocks per sample on average; 2x room per chunk */
    static philox2x64_block buf[2 * CHUNK];
    philox2x64_rng r;
    philox2x64_seed(&r, seed);
    philox_buf = buf;
    uint64_t blocks_used = 0;
#define REFILL() do { if (philox_pos > 2 * CHUNK) { fprintf(stderr, "buffer overrun\n"); exit(1); } blocks_used += philox_pos; \
        for (size_t i_ = 0; i_ < 2 * CHUNK; i_++) { buf[i_] = philox2x64_step(&r); } philox_pos = 0; } while (0)
    philox_pos = 0;
    REFILL();
    blocks_used = 0;
#endif

    counter_open();
    uint32_t *hist = calloc(BINS, sizeof *hist);
    if (!hist) { perror("calloc"); return 1; }

    /* fixed cost of a fenced read pair (the same instruction sequence as the timed loop) */
    uint64_t *cal = malloc(65536 * sizeof *cal);
    for (int i = 0; i < 65536; i++) {
        _mm_lfence(); uint64_t a = cyc(); _mm_lfence();
        _mm_lfence(); uint64_t b = cyc(); _mm_lfence();
        cal[i] = (b - a) & pmc_mask;
    }
    uint64_t overhead = 0;                                      /* median */
    { uint32_t c[1024] = {0}; for (int i = 0; i < 65536; i++) c[cal[i] < 1023 ? cal[i] : 1023]++;
      uint32_t s = 0; for (int i = 0; i < 1024; i++) { s += c[i]; if (s >= 32768) { overhead = (uint64_t)i; break; } } }
    free(cal);

    double sink = 0;
#if PRECOMPUTED
    for (uint64_t i = 0; i < warmup; i++) { if (i % CHUNK == 0) REFILL(); sink += sample(v); }
    REFILL();
    blocks_used = 0;
#else
    for (uint64_t i = 0; i < warmup; i++) sink += sample(v);
    if (v == TRAP_1CALL) zt_init_philox_1call(seed, n, h, t); else zb_init_philox(seed, n);
#endif

    const uint32_t seq0 = pc->lock;
    const uint64_t windows = samples / W;
    uint64_t overflow = 0, maxv = 0, under = 0;
    double total = 0;
#if PRECOMPUTED
    if (CHUNK % W) { fprintf(stderr, "window must divide %u\n", CHUNK); return 2; }
#endif
    for (uint64_t w = 0; w < windows; w++) {
#if PRECOMPUTED
        if (w && (w * W) % CHUNK == 0) REFILL();               /* untimed */
#endif
        _mm_lfence();
        const uint64_t a = cyc();
        _mm_lfence();
        double x = 0;
        for (unsigned j = 0; j < W; j++) x += sample(v);
        sink += x;
        _mm_lfence();
        const uint64_t b = cyc();
        _mm_lfence();
        uint64_t d = (b - a) & pmc_mask;
        d = d > overhead ? d - overhead : (under++, 0);
        total += (double)d;
        if (d > maxv) maxv = d;
        if (d < BINS) hist[d]++; else overflow++;
    }
    const int counter_moved = pc->lock != seq0;                 /* counter rescheduled during the run */

    printf("BENCHMARK_JSON: {\"variant\":\"%s\",\"uniform_mode\":\"%s\",\"N\":%u,\"H\":%u,\"T\":%u,"
           "\"seed\":%" PRIu64 ",\"window\":%u,\"windows\":%" PRIu64 ",\"samples\":%" PRIu64 ","
           "\"overhead_cycles\":%" PRIu64 ",\"below_overhead\":%" PRIu64 ",\"overflow\":%" PRIu64 ","
           "\"max_cycles\":%" PRIu64 ",\"mean_cycles_per_sample\":%.6f,\"counter_moved\":%d,"
           "\"blocks_used\":%" PRIu64 ",\"sink\":%.17g,\"hist\":[",
           names[v], PRECOMPUTED ? "precomputed" : "inline", n, h, t, seed, W, windows, windows * W,
           overhead, under, overflow, maxv, total / (double)(windows * W), counter_moved,
#if PRECOMPUTED
           blocks_used + (uint64_t)philox_pos,
#else
           (uint64_t)0,
#endif
           sink);
    int first = 1;
    for (uint32_t i = 0; i < BINS; i++)
        if (hist[i]) { printf("%s[%u,%u]", first ? "" : ",", i, hist[i]); first = 0; }
    printf("]}\n");
    return 0;
}
