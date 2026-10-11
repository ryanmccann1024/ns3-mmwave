CXX ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Wpedantic
ROOT := ../../..
SRCS := query-test.cc $(ROOT)/src/query/query-protocol.cc $(ROOT)/src/query/child-process.cc \
        $(ROOT)/src/query/channel-query.cc $(ROOT)/src/eval/probe-diagnostics.cc \
        $(ROOT)/src/config/rl-control.cc $(ROOT)/src/config/query-config.cc \
        $(ROOT)/src/util/string-utils.cc
OUT := query-test
.PHONY: all test clean
all: $(OUT)
$(OUT): $(SRCS)
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $^
test: $(OUT)
	./$(OUT)
clean:
	rm -f $(OUT)
