#!/bin/sh
set -eu
bin=$1
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
for n in 8 16 32 64 128 256; do
    "$bin" --algorithm basic --layers "$n" --samples 1000 --seed 7 > "$work/log"
    grep -q "N=$n (H/T not applicable)" "$work/log"
    grep -q 'Seed: *7' "$work/log"
    grep -q 'Samples/second:' "$work/log"
done
"$bin" --algorithm basic --samples 1000 > "$work/log"
grep -q 'N=128 ' "$work/log"
"$bin" --samples 1000 > "$work/log"
grep -q 'N=8 H=2 T=4' "$work/log"
for n in 0 7 129 257 4294967296 -8 junk 8junk; do
    if "$bin" --algorithm basic --layers "$n" > "$work/log" 2>&1; then
        echo "Invalid N accepted: $n"; exit 1
    fi
done
python3 tests/test_benchmark_output.py "$bin" "$work"
python3 tests/test_benchmark_output_dir.py "$bin" "$work"
"$bin" --algorithm trapezoid --layers 16 --head 1 --tail 1 --samples 1000 > "$work/log"
grep -q 'N=16 H=1 T=1' "$work/log"
echo 'Benchmark defaults, layer selection, seed reporting, input validation and binary output PASS'
