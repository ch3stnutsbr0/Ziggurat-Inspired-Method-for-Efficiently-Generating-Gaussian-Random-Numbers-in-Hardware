CC ?= clang
CFLAGS_COMMON = -std=c11 -Wall -Wextra -pedantic
SOURCES = benchmark.c ziggurat_trapezoid.c ziggurat_basic.c ziggurat_trapezoid_profiled.c ziggurat_basic_profiled.c xoshiro256plus.c prng.c ziggurat_basic_xoshiro256plus.c ziggurat_trapezoid_xoshiro256plus.c

.PHONY: all debug O0 O2 O3 clean
all: O2
debug:
	$(CC) $(CFLAGS_COMMON) -O0 -g -DZT_ENABLE_COUNTERS=1 -DBENCHMARK_OPTIMIZATION='"O0"' -DBENCHMARK_CFLAGS='"-std=c11 -Wall -Wextra -pedantic -O0 -g -DZT_ENABLE_COUNTERS=1"' $(SOURCES) -o benchmark -lm
O0:
	$(CC) $(CFLAGS_COMMON) -O0 -DBENCHMARK_OPTIMIZATION='"O0"' -DBENCHMARK_CFLAGS='"-std=c11 -Wall -Wextra -pedantic -O0"' $(SOURCES) -o benchmark -lm
O2:
	$(CC) $(CFLAGS_COMMON) -O2 -DBENCHMARK_OPTIMIZATION='"O2"' -DBENCHMARK_CFLAGS='"-std=c11 -Wall -Wextra -pedantic -O2"' $(SOURCES) -o benchmark -lm
O3:
	$(CC) $(CFLAGS_COMMON) -O3 -DBENCHMARK_OPTIMIZATION='"O3"' -DBENCHMARK_CFLAGS='"-std=c11 -Wall -Wextra -pedantic -O3"' $(SOURCES) -o benchmark -lm
clean:
	rm -f benchmark test_basic test_basic_counters test_prng_profile benchmark_test test_prng_selection

# Test sources include basic.c to inspect internal tables without public hooks.
TEST_SOURCES = tests/test_basic.c tests/legacy_basic.c
.PHONY: test
test:
	$(CC) $(CFLAGS_COMMON) -O2 -I. $(TEST_SOURCES) -o test_basic -lm
	./test_basic
	$(CC) $(CFLAGS_COMMON) -O2 -I. -DZT_ENABLE_COUNTERS=1 $(TEST_SOURCES) -o test_basic_counters -lm
	./test_basic_counters
	$(CC) $(CFLAGS_COMMON) -O2 -I. tests/test_prng_profile.c ziggurat_basic.c ziggurat_trapezoid.c ziggurat_basic_profiled.c ziggurat_trapezoid_profiled.c -o test_prng_profile -lm
	./test_prng_profile
	$(CC) $(CFLAGS_COMMON) -O2 -DBENCHMARK_OPTIMIZATION='"O2"' -DBENCHMARK_CFLAGS='"-std=c11 -Wall -Wextra -pedantic -O2"' $(SOURCES) -o benchmark_test -lm
	sh tests/test_benchmark.sh ./benchmark_test

.PHONY: test-prng-selection
test-prng-selection: O2
	$(CC) $(CFLAGS_COMMON) -O2 -I. tests/test_prng_selection.c $(filter-out benchmark.c,$(SOURCES)) -o test_prng_selection -lm
	./test_prng_selection
	PYTHONDONTWRITEBYTECODE=1 python3 ../experiments/tests/test_prng_selection.py
