CC ?= clang
CFLAGS_COMMON = -std=c11 -Wall -Wextra -pedantic
SOURCES = benchmark.c ziggurat_trapezoid.c ziggurat_basic.c

.PHONY: all debug O0 O2 O3 clean
all: O2
debug:
	$(CC) $(CFLAGS_COMMON) -O0 -g -DZT_ENABLE_COUNTERS=1 $(SOURCES) -o benchmark -lm
O0:
	$(CC) $(CFLAGS_COMMON) -O0 $(SOURCES) -o benchmark -lm
O2:
	$(CC) $(CFLAGS_COMMON) -O2 $(SOURCES) -o benchmark -lm
O3:
	$(CC) $(CFLAGS_COMMON) -O3 $(SOURCES) -o benchmark -lm
clean:
	rm -f benchmark
