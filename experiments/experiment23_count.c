/* Experiment 23 harness: exact operation counts per sample (no timing).
 * Build: -DZIGGURAT_COUNT_OPS -DPHILOX_COUNT_BLOCKS
 *
 *   experiment23_count count --variant V --layers N [--head H --tail T] --samples S --seed X
 *       Draws S samples and prints the histogram of per-sample operation vectors.
 *   experiment23_count enumerate --layers N --head H --tail T
 *       Trapezoid only: feeds crafted blocks to zt_philox_1call_map() so that every path
 *       (main / head / tail side, every depth, rectangle and wedge) is taken once, and prints
 *       each path's operation vector. This is the structural support of the Trapezoid's
 *       operation counts, including paths too rare to appear in a sampled run.
 *
 * VARIANT: trapezoid_1call | classical_philox_fast
 * Output: lines "BENCHMARK_JSON: {...}"; a vector is the list of FIELDS below, in that order. */
#include "gaussian_prng.h"
#include "philox2x64.h"
#include "ziggurat_opcount.h"
#include "ziggurat_philox.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uint64_t philox_blocks;
zop_counts zop;

#define NF 18
static const char *FIELDS[NF] = {"blocks", "attempts", "reads", "conv", "fmul", "fscale", "fadd", "fcmp", "fdiv",
                                 "iadd", "icmp", "exp", "log", "rejections", "tail_iter", "outcome", "depth", "side"};

static void vec(uint32_t v[NF], uint64_t blocks) {
    const uint32_t f[NF] = {(uint32_t)blocks, zop.attempts, zop.reads, zop.conv, zop.fmul, zop.fscale, zop.fadd,
                            zop.fcmp, zop.fdiv, zop.iadd, zop.icmp, zop.exp, zop.log, zop.rejections, zop.tail_iter,
                            zop.outcome, zop.depth, zop.side};
    memcpy(v, f, sizeof f);
}

/* open-addressing map: operation vector -> count */
#define CAP (1u << 16)
static uint32_t keys[CAP][NF];
static uint64_t counts[CAP];
static unsigned used;

static void add(const uint32_t v[NF]) {
    uint64_t h = 1469598103934665603ull;
    for (int i = 0; i < NF; i++) { h ^= v[i]; h *= 1099511628211ull; }
    for (uint32_t j = (uint32_t)h & (CAP - 1);; j = (j + 1) & (CAP - 1)) {
        if (!counts[j]) {
            if (++used > CAP / 2) { fprintf(stderr, "too many distinct vectors\n"); exit(1); }
            memcpy(keys[j], v, sizeof keys[j]);
            counts[j] = 1;
            return;
        }
        if (!memcmp(keys[j], v, sizeof keys[j])) { counts[j]++; return; }
    }
}

static void print_vec(const uint32_t v[NF]) {
    printf("[");
    for (int i = 0; i < NF; i++) printf("%s%" PRIu32, i ? "," : "", v[i]);
    printf("]");
}

static void print_fields(void) {
    printf("\"fields\":[");
    for (int i = 0; i < NF; i++) printf("%s\"%s\"", i ? "," : "", FIELDS[i]);
    printf("]");
}

static int enumerate(unsigned n, unsigned h, unsigned t) {
    if (!zt_init_philox_1call(1, n, h, t)) { fprintf(stderr, "init failed\n"); return 2; }
    unsigned k = 0;
    while ((1u << k) < n) k++;
    const unsigned D = zt_philox_1call_decision_bits(n, h, t), L = 1 + (h > t ? h : t);
    const uint64_t dmask = (UINT64_C(1) << D) - 1, B = UINT64_C(0x0123456789abcdef);
    printf("BENCHMARK_JSON: {\"mode\":\"enumerate\",\"N\":%u,\"H\":%u,\"T\":%u,\"decision_bits\":%u,", n, h, t, D);
    print_fields();
    printf(",\"paths\":[");
    int first = 1;
    for (unsigned side = 0; side < 3; side++) {
        const unsigned levels = side == 0 ? 0 : side == 1 ? h : t;
        for (unsigned depth = 0; depth <= levels; depth++) {
            if (side && !depth) continue;                     /* depth 0 of a refined side is the main table */
            for (unsigned wedge = 0; wedge < 2; wedge++) {
                /* idx0..idx_{depth-1} = the refined index (0 head, N-1 tail), idx_depth = a middle strip */
                uint64_t A = 0;
                const unsigned refined = side == 1 ? 0 : n - 1, middle = n / 2;
                for (unsigned j = 0; j < L; j++) {
                    const unsigned idx = j < depth ? refined : middle;
                    A |= (uint64_t)idx << (64 - k * (j + 1));
                }
                A |= wedge ? dmask : 0;                      /* decision bits: 0 -> rectangle, all ones -> wedge */
                memset(&zop, 0, sizeof zop);
                (void)zt_philox_1call_map(A, B);
                uint32_t v[NF];
                vec(v, 1);
                printf("%s{\"side\":%u,\"depth\":%u,\"wedge\":%u,\"vector\":", first ? "" : ",", side, depth, wedge);
                print_vec(v);
                printf("}");
                first = 0;
            }
        }
    }
    printf("]}\n");
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: count|enumerate ...\n"); return 2; }
    const int is_enum = !strcmp(argv[1], "enumerate");
    int v = -1;
    unsigned n = 0, h = 0, t = 0;
    uint64_t samples = 0, seed = 0;
    for (int i = 2; i + 1 < argc; i += 2) {
        const char *k = argv[i], *val = argv[i + 1];
        if (!strcmp(k, "--variant")) v = !strcmp(val, "trapezoid_1call") ? 0 : !strcmp(val, "classical_philox_fast") ? 1 : -1;
        else if (!strcmp(k, "--layers")) n = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--head")) h = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--tail")) t = (unsigned)strtoul(val, NULL, 10);
        else if (!strcmp(k, "--samples")) samples = strtoull(val, NULL, 10);
        else if (!strcmp(k, "--seed")) seed = strtoull(val, NULL, 10);
        else { fprintf(stderr, "unknown option %s\n", k); return 2; }
    }
    if (is_enum) return enumerate(n, h, t);
    if (strcmp(argv[1], "count") || v < 0 || !n || !samples) { fprintf(stderr, "bad arguments\n"); return 2; }
    if (v == 1) h = t = 0;
    const int ok = v == 0 ? zt_init_philox_1call(seed, n, h, t) : zb_init_philox(seed, n);
    if (!ok) { fprintf(stderr, "init failed\n"); return 2; }
    double sum = 0;
    for (uint64_t s = 0; s < samples; s++) {
        memset(&zop, 0, sizeof zop);
        const uint64_t b0 = philox_blocks;
        sum += v == 0 ? zt_gaussian_philox_1call() : zb_gaussian_philox_fast();
        uint32_t vv[NF];
        vec(vv, philox_blocks - b0);
        add(vv);
    }
    printf("BENCHMARK_JSON: {\"mode\":\"count\",\"variant\":\"%s\",\"N\":%u,\"H\":%u,\"T\":%u,\"seed\":%" PRIu64
           ",\"samples\":%" PRIu64 ",\"sum\":%.17g,", v == 0 ? "trapezoid_1call" : "classical_philox_fast", n, h, t, seed,
           samples, sum);
    print_fields();
    printf(",\"vectors\":[");
    int first = 1;
    for (unsigned j = 0; j < CAP; j++)
        if (counts[j]) {
            printf("%s{\"count\":%" PRIu64 ",\"vector\":", first ? "" : ",", counts[j]);
            print_vec(keys[j]);
            printf("}");
            first = 0;
        }
    printf("]}\n");
    return 0;
}
