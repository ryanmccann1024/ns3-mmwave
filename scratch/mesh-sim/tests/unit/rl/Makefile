CXX ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT := ../../..
OUT := reward-window-test joint-motion-test
.PHONY: all test clean
all: $(OUT)
reward-window-test: reward-window-test.cc $(ROOT)/src/rl/reward-window.h
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $<
joint-motion-test: joint-motion-test.cc $(ROOT)/src/rl/joint-motion.h $(ROOT)/src/domain/sim-config.h
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $<
test: $(OUT)
	./reward-window-test
	./joint-motion-test
clean:
	rm -f $(OUT)
