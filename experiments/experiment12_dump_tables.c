/* Experiment 12: export the exact Trapezoid tables built by c/ziggurat_trapezoid.c.
 * The sampler source is included directly, so its static tables are readable here
 * without modifying it. Usage: dump_tables N H T  ->  CSV on stdout:
 *   side,level,index,w,d,a,x_lo,x_hi
 * side: root (level 0), head (level 1..H) or tail (level 1..T). x_lo/x_hi are the
 * table's boundaries x[i], x[i+1]. Descent rules and weights are applied by the caller. */
#include "../c/ziggurat_trapezoid.c"
#include <stdio.h>
#include <stdlib.h>

static void dump(const char *side, unsigned level, const table_t *t, unsigned n) {
    for (unsigned i = 0; i < n; i++)
        printf("%s,%u,%u,%.17g,%.17g,%.17g,%.17g,%.17g\n", side, level, i,
               t->w[i], t->d[i], t->a[i], t->x[i], t->x[i + 1]);
}

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: %s N H T\n", argv[0]); return 2; }
    unsigned n = (unsigned)strtoul(argv[1], NULL, 10), h = (unsigned)strtoul(argv[2], NULL, 10),
             t = (unsigned)strtoul(argv[3], NULL, 10);
    if (!zt_init(1, n, h, t)) { fprintf(stderr, "invalid configuration\n"); return 2; }
    printf("side,level,index,w,d,a,x_lo,x_hi\n");
    dump("root", 0, &tabs[0], n);
    for (unsigned j = 1; j <= h; j++) dump("head", j, &tabs[j], n);
    for (unsigned j = 1; j <= t; j++) dump("tail", j, &tabs[ZT_MAX_REFINEMENT + j], n);
    return 0;
}
