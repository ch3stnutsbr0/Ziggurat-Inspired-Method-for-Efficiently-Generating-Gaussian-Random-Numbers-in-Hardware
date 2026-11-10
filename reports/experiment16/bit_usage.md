# Experiment 16: random-bit usage per step

Every sampler draws **Philox2x64-10 blocks**: one call = 128 bits = word A (64) + word B (64). The
tables below give, for each step, the bits it reads, with the general formula for N = 2^k and the
value at the recommended **N = 128 (k = 7), H1/T2**. Bit positions: A[63] is the top bit.
Sources: `c/ziggurat_basic_philox.c`, `c/ziggurat_trapezoid_philox.c`.

## 1. Classical (`zb_gaussian_philox`, `zb_gaussian_philox_fast`: same bits)

One block per **attempt**. A rejected attempt is discarded and the next attempt draws a new block.

| Step | Bits | Field | N=128 | When |
|---|---|---|---|---|
| 1. layer l | A[63 .. 64−k] | k | 7 | every attempt |
| 2. sign | A[63−k] | 1 | 1 | every attempt (used if accepted) |
| 3. position u, candidate x = u·X[l−1] | A[52..0] | 53 | 53 | every attempt |
| 4a. inner rectangle (x ≤ X[l]): accept | — | 0 | 0 | most attempts |
| 4b. boundary height test against exp(−x²/2) | B[63..11] | 53 | 53 | outer part of strip l ≥ 1 |
| 4c. base strip: rectangle or tail | B[63..11] | 53 | 53 | l = 0 |
| 5. tail candidate (xt, yt) via log() | new block: A[63..11], B[63..11] | 2 × 53 | 106 | each tail candidate (repeats until accepted) |
| unused per block | A: 10−k bits; B: 11 bits (all 64 if 4a) | | 3 + 11 (or 3 + 64) | |

Common case (inner-rectangle accept): k + 1 + 53 = **61 bits read**, 67 of the 128 bits wasted
(word B unused). Each rejection costs a whole new block. The rejected bits cannot be reused: given
that the attempt was rejected, they are no longer uniform.

## 2. Trapezoid base case (`zt_gaussian_philox_base`; H = T = 0)

Always exactly one block per sample. No rejection.

| Step | Bits | Field | N=128 | When |
|---|---|---|---|---|
| 1. layer i | A[63 .. 64−k] | k | 7 | always |
| 2. sign | A[63−k] | 1 | 1 | always |
| 3. rectangle or wedge (m < ⌈a·2^53⌉) | A[52..0] | 53 | 53 | always |
| 4a. rectangle position x = w·u | B[63..11] | 53 | 53 | probability a_i |
| 4b. wedge x = w + d·\|u1 − u2\| | B[63..32], B[31..0] | 2 × 32 | 64 | probability 1 − a_i |
| unused | A: 10−k bits; B: 11 (rectangle) or 0 (wedge) | | 3 + 11 or 3 + 0 | |

Rectangle path: 7 + 1 + 53 + 53 = **114 bits**. Wedge path: 7 + 1 + 53 + 64 = **125 bits** (N=128).

## 3. Trapezoid with refinement

### 3a. New block per descent level (`zt_gaussian_philox`, `zt_gaussian_philox_fast`: same bits)

| Step | Bits | Field | N=128 | When |
|---|---|---|---|---|
| 1. root layer i0 | block 1: A[63 .. 64−k] | k | 7 | always |
| 2. descend? (i0 = 0 and H > 0, or i0 = N−1 and T > 0) | — | 0 | 0 | probability 2/N |
| 2'. if descending: **discard block 1** (128 − k bits unread) | | | 121 wasted | per level |
| 3. level-j index i_j | block j+1: A[63 .. 64−k] | k | 7 | per level; another level with probability 1/N, up to H or T |
| 4. sign, decision, position | final block: as in section 2, steps 2–4 | 1 + 53 + (53 or 64) | 107 or 118 | always, on the last block |

Blocks per sample: 1 + P(head) + P(tail, ≥ 1 level) + P(tail, 2 levels) = 1 + 1/N + 1/N + 1/N²
for H1/T2: **1.016** at N=128 and **1.266** at N=8 (measured 1.015681 and 1.265878).

### 3b. One block per sample (`zt_gaussian_philox_1call`)

All indices in word A, L = 1 + max(H, T) of them. The decision field shrinks to D = min(53, 63 − k·L).

| Step | Bits | Field | N=128, H1/T2 (L = 3) | When |
|---|---|---|---|---|
| 1. root layer i0 = idx0 | A[63 .. 64−k] | k | 7 | always |
| 2. level-1 index idx1 | A[63−k .. 64−2k] | k | 7 | reserved; read with probability 2/N |
| 3. level-2 index idx2 | A[63−2k .. 64−3k] | k | 7 | reserved; read with probability 1/N² (tail) |
| 4. sign | A[63−kL] | 1 | 1 | always |
| 5. rectangle or wedge (m < ⌈a·2^D⌉) | A[D−1 .. 0] | D | **42** (was 53) | always |
| 6a. rectangle position | B[63..11] | 53 | 53 | probability a |
| 6b. wedge \|u1 − u2\| | B[63..32], B[31..0] | 2 × 32 | 64 | probability 1 − a |
| unused | A: 63 − kL − D (nonzero only when D is capped at 53); B: 11 (rectangle) or 0 (wedge) | | 0 + 11 or 0 + 0 | |

Every sample: exactly **1 block**. Wedge path at N=128, H1/T2: 21 + 1 + 42 + 64 = **128 of 128 bits**.
Exact cost of the shorter decision field: CDF shift ≤ 2.6·10⁻¹⁴ at N=128 H1/T2 (Exp 15 exact KS 1.5·10⁻⁶);
see report section 8.

## 4. Summary: Philox blocks per sample (measured, count mode, 4.2·10⁶ samples; H1/T2)

| N | Classical | Trapezoid base (H0/T0) | Trapezoid, new block per level | Trapezoid 1call |
|---|---|---|---|---|
| 8 | 1.147 | 1 | 1.266 | **1** |
| 16 | 1.081 | 1 | 1.129 | **1** |
| 32 | 1.044 | 1 | 1.064 | **1** |
| 64 | 1.024 | 1 | 1.032 | **1** |
| 128 | 1.013 | 1 | 1.016 | **1** |
| 256 | 1.007 | 1 | 1.008 | **1** |

Classical's extra blocks are rejections and exponential-tail candidates. Their count varies from
sample to sample with no fixed upper bound. Trapezoid's extra blocks (3a) are descents: at most
max(H, T) per sample. The one-block layout (3b) removes them.

Bits read per sample at N=128, by path (mean over paths):

| Sampler | Common path | Rare path | Mean bits drawn (128 × blocks) |
|---|---|---|---|
| Classical | 61 (inner rectangle) | +53 boundary test; +128 per retry or tail candidate | 129.7 |
| Trapezoid base | 114 (rectangle) / 125 (wedge) | — | 128 |
| Trapezoid, new block per level | 114 / 125 | +128 per level | 130.0 |
| Trapezoid 1call | 114 / 125 (+14 reserved) | +0 | 128 |
