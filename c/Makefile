CC ?= clang
CFLAGS_COMMON = -std=c11 -Wall -Wextra -pedantic
SOURCES = benchmark.c ziggurat_trapezoid.c ziggurat_basic.c

.PHONY: all debug O0 O2 O3 clean
all: O2
debug:
	$(CC) $(CFLAGS_COMMON) -O0 -g -DZT_ENABLE_COUNTERS=1 -DBENCHMARK_OPTIMIZATION='"O0"' $(SOURCES) -o benchmark -lm
O0:
	$(CC) $(CFLAGS_COMMON) -O0 -DBENCHMARK_OPTIMIZATION='"O0"' $(SOURCES) -o benchmark -lm
O2:
	$(CC) $(CFLAGS_COMMON) -O2 -DBENCHMARK_OPTIMIZATION='"O2"' $(SOURCES) -o benchmark -lm
O3:
	$(CC) $(CFLAGS_COMMON) -O3 -DBENCHMARK_OPTIMIZATION='"O3"' $(SOURCES) -o benchmark -lm
clean:
	rm -f benchmark test_basic test_basic_counters benchmark_test

# Test sources include basic.c to inspect internal tables without public hooks.
TEST_SOURCES = tests/test_basic.c tests/legacy_basic.c
.PHONY: test
test:
	$(CC) $(CFLAGS_COMMON) -O2 -I. $(TEST_SOURCES) -o test_basic -lm
	./test_basic
	$(CC) $(CFLAGS_COMMON) -O2 -I. -DZT_ENABLE_COUNTERS=1 $(TEST_SOURCES) -o test_basic_counters -lm
	./test_basic_counters
	$(CC) $(CFLAGS_COMMON) -O2 -DBENCHMARK_OPTIMIZATION='"O2"' $(SOURCES) -o benchmark_test -lm
	sh tests/test_benchmark.sh ./benchmark_test
