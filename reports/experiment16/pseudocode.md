# Experiment 16: pseudocode of the general sampler and the fast-path sampler

Source: `c/ziggurat_trapezoid_philox.c`. The general sampler is `zt_gaussian_philox()`; the
fast-path sampler is `zt_gaussian_philox_fast()` with its out-of-line `refine()`. The two produce
**bit-identical output** for every N, H and T: they draw the same blocks in the same order and make
the same decisions (checked for N = 8…256, H/T = 0/0…4/4, 10^6 samples each, 0 mismatches).

## Common definitions

```text
N            number of layers (power of two), k = log2(N)
H, T         head / tail refinement depth
TABLE[0]     root table: N strips of the base ziggurat
HEAD[j]      j = 1..H: strip 0 of the level j-1 table re-split into N sub-strips
TAIL[j]      j = 1..T: strip N-1 of the level j-1 table re-split into N sub-strips
entry e      per strip: w (rectangle width), d (wedge width),
             thr = ceil(a * 2^53), where a = 2w / (2w + d) = P(rectangle | strip)

PHILOX()     one Philox2x64-10 call -> 128 bits = two 64-bit words (A, B)

Bit fields of one call:
  A[63 .. 64-k]   layer index i          (k bits)
  A[63-k]         sign bit               (1 bit)
  A[52 .. 0]      rectangle/wedge choice (53 bits)
  B[63 .. 11]     rectangle position     (53 bits)
  B[63 .. 32]     wedge u1               (32 bits)
  B[31 .. 0]      wedge u2               (32 bits)
```

The finishing step is shared by both samplers:

```text
FINISH(e, A, B):
    if A[52..0] < e.thr:                       # rectangle, probability a
        x = e.w * B[63..11] / 2^53
    else:                                      # wedge, probability 1 - a
        x = e.w + e.d * |B[63..32] - B[31..0]| / 2^32
                                               # |u1 - u2| has density 2(1 - v):
                                               # the linear wedge, no rejection
    if A[63-k] = 1: x = -x                     # sign (OR-ed into the float's sign bit)
    return x
```

Every sample that does not descend uses exactly **one** PHILOX call. Each descent level costs one
more call.

## General sampler (`zt_gaussian_philox`)

The refinement loop is part of the only code path, so every sample runs through it.

```text
GAUSSIAN_GENERAL():
    tab  = TABLE[0]
    lev  = 0
    side = NONE                                # NONE / HEAD / TAIL once descending
    loop:
        (A, B) = PHILOX()
        i = A[63 .. 64-k]

        if i = 0 and side != TAIL and lev < H:          # head strip: go one level deeper
            lev  = lev + 1
            tab  = HEAD[lev]
            side = HEAD
            continue

        if i = N-1 and side != HEAD and lev < T:        # tail strip: go one level deeper
            lev  = lev + 1
            tab  = TAIL[lev]
            side = TAIL
            continue

        return FINISH(tab[i], A, B)
```

## Fast-path sampler (`zt_gaussian_philox_fast`)

The common case is the base case written as straight-line code. Only a root index on a refined
strip, with probability about 2/N, leaves it.

```text
GAUSSIAN_FAST():                               # inline, no loop, no state
    (A, B) = PHILOX()
    i = A[63 .. 64-k]
    if (i = 0 and H > 0) or (i = N-1 and T > 0):        # rare, marked unlikely
        return REFINE(head = (i = 0 and H > 0))
    return FINISH(TABLE[0][i], A, B)


REFINE(head):                                  # out of line ("cold"), stored away from the fast path
    lev = 1
    tab = HEAD[1] if head else TAIL[1]
    loop:
        (A, B) = PHILOX()
        i = A[63 .. 64-k]
        if head     and i = 0   and lev < H:   lev = lev + 1;  tab = HEAD[lev];  continue
        if not head and i = N-1 and lev < T:   lev = lev + 1;  tab = TAIL[lev];  continue
        return FINISH(tab[i], A, B)
```

For reference, the no-refinement ceiling `zt_gaussian_philox_base()` is the fast path without the
`if`: `(A, B) = PHILOX(); return FINISH(TABLE[0][A[63..64-k]], A, B)`.

## What differs

| | General | Fast path |
|---|---|---|
| Algorithm, bits used, output | same | same (bit-identical) |
| Code every sample runs | descent loop with `tab`, `lev`, `side` | one call, one index check, FINISH |
| Descent logic | inline, in the loop | separate `REFINE`, entered with probability ≈ 2/N |
| Side tracking | `side` variable | not needed: `head` is fixed on entry, so the head and tail paths never mix |
| PRNG calls per sample (N = 128, H1/T2) | 1.016 | 1.016 |
| Throughput, N = 128, H1/T2 (Msamples/s) | 60.5 | 79.5 (base-case ceiling 83.9) |

Why the fast path is faster on a CPU: the samplers are limited by the about 50-cycle Philox
dependency chain. The general sampler's loop state (`tab`, `lev`, `side`) and loop structure
lengthen every sample's code and add stack traffic. This reduces how much the next sample's Philox
call can overlap the current one. The fast path gives the 98% common case the base-case code shape.

## Hardware reading

The fast path corresponds to a full-rate main pipeline that runs the base case on every block. A
block whose index is 0 or N−1 is sent to a separate refinement unit, at a rate of about 2/N, and a
small output FIFO absorbs the extra latency of a descent.

## One-block sampler (`zt_gaussian_philox_1call`)

The same descent as the fast path, but each level reads its index from word A instead of drawing a
new block. Not bit-identical to the samplers above: it uses different bits. Its law differs only by
the decision quantisation 2^-D (report section 8).

```text
L = 1 + max(H, T);   D = min(53, 63 - k*L)
word A:  [idx0: k][idx1: k] ... [idx_L-1: k][sign: 1] ... [decision: low D bits]

GAUSSIAN_1CALL():
    (A, B) = PHILOX()                          # the only call, for every sample
    i = idx0(A);  tab = TABLE[0]
    if i = 0 and H > 0:                        # rare: out of line, no PRNG call
        lev = 0
        while i = 0 and lev < H:   lev = lev + 1;  i = idx_lev(A)
        tab = HEAD[lev]
    else if i = N-1 and T > 0:
        lev = 0
        while i = N-1 and lev < T: lev = lev + 1;  i = idx_lev(A)
        tab = TAIL[lev]
    return FINISH_D(tab[i], A, B)              # FINISH with thr = ceil(a * 2^D) and the sign at bit 63 - k*L
```

## Classical fast path (`zb_gaussian_philox_fast`), for comparison

```text
GAUSSIAN_CLASSICAL_FAST():
    (A, B) = PHILOX()
    l = A[63 .. 64-k];  u = A[52..0] / 2^53
    if l != 0:
        x = u * X[l-1]
        if x <= X[l]:  return sign(A) * x      # inner rectangle: the common case
    return CLASSICAL_SLOW(A, B)                # out of line: base strip and exp. tail (log),
                                               # boundary test (exp), retries with new blocks
```
