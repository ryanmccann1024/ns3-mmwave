CXX ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT := ../../..
OUT := reward-window-test

.PHONY: all test clean
all: $(OUT)
$(OUT): reward-window-test.cc $(ROOT)/src/rl/reward-window.h
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $<
test: $(OUT)
	@./$(OUT)
clean:
	rm -f $(OUT)
