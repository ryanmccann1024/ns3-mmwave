CXX ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT := ../../..
OUT := joint-motion-test
.PHONY: all test clean
all: $(OUT)
$(OUT): joint-motion-test.cc $(ROOT)/src/rl/joint-motion.h $(ROOT)/src/domain/sim-config.h
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $<
test: $(OUT)
	./$(OUT)
clean:
	rm -f $(OUT)
