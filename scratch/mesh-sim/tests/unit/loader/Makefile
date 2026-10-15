CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..

SRCS := $(ROOT)/src/config/query-config.cc \
        loader-test.cc \
        $(ROOT)/src/config/config-loader.cc \
        $(ROOT)/src/util/string-utils.cc \
        $(ROOT)/src/util/ini-parser.cc

OUT := loader-test

.PHONY: all test clean

all: $(OUT)

$(OUT): $(SRCS)
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $^

test: $(OUT)
	@./$(OUT)

clean:
	rm -f $(OUT)
