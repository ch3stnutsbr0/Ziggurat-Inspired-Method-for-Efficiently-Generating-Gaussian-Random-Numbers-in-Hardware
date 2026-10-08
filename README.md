# Ziggurat Trapezoid GRNG

MATLAB and C implementations and experiments for Gaussian random number generation.

- `matlab/`: MATLAB samplers, table construction, demos, and statistical tests.
- `c/`: C implementation, benchmark, detailed usage notes, and recorded performance results.

To build and run the C benchmark:

```sh
cd c
make O2
./benchmark --samples 1000000 --seed 1
```

See [the C README](c/README.md) for algorithm details and more benchmark options.
