/* Operation counters for the Philox samplers (Experiment 23). Compiled in only with
 * -DZIGGURAT_COUNT_OPS; otherwise every macro expands to nothing and the object code is unchanged.
 *
 * Counted per algorithmic step, not per machine instruction: an operation the CPU code repeats
 * only because of its code layout (the Classical fast path's test, redone at the start of the
 * out-of-line slow path) is counted once. Philox blocks are counted by PHILOX_COUNT_BLOCKS. */
#ifndef ZIGGURAT_OPCOUNT_H
#define ZIGGURAT_OPCOUNT_H

#ifdef ZIGGURAT_COUNT_OPS
#include <stdint.h>

typedef struct {
    uint32_t attempts;   /* sampling attempts (Trapezoid: always 1) */
    uint32_t reads;      /* table values read (one field of one table entry) */
    uint32_t conv;       /* integer -> floating-point conversions */
    uint32_t fmul;       /* floating-point multiplies */
    uint32_t fscale;     /* multiplies by a power of two (exponent adjustment) */
    uint32_t fadd;       /* floating-point additions and subtractions */
    uint32_t fcmp;       /* floating-point comparisons */
    uint32_t fdiv;       /* floating-point divisions */
    uint32_t iadd;       /* integer additions, subtractions, absolute values */
    uint32_t icmp;       /* integer comparisons */
    uint32_t exp;        /* exp() evaluations */
    uint32_t log;        /* log() evaluations */
    uint32_t rejections; /* Classical: attempts rejected by the boundary-strip exp() test */
    uint32_t tail_iter;  /* Classical: exponential-tail candidates (each draws a block) */
    uint32_t outcome;    /* Classical: 1 fast accept, 2 base rectangle, 3 tail, 4 wedge accept
                            Trapezoid: 1 rectangle, 2 wedge */
    uint32_t depth;      /* Trapezoid: refinement levels descended */
    uint32_t side;       /* Trapezoid: 0 main table, 1 head, 2 tail */
} zop_counts;

extern zop_counts zop;
#define ZOP(f) (zop.f++)
#define ZOP_N(f, n) (zop.f += (n))
#define ZOP_SET(f, v) (zop.f = (v))
#define ZOP_ONLY(...) __VA_ARGS__
#else
#define ZOP(f) ((void)0)
#define ZOP_N(f, n) ((void)0)
#define ZOP_SET(f, v) ((void)0)
#define ZOP_ONLY(...)
#endif

#endif
