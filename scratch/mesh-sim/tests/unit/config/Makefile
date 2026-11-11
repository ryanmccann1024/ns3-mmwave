CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..

SRCS := config-validator-test.cc mission-config-test.cc \
        $(ROOT)/src/config/query-config.cc \
        $(ROOT)/src/config/config-validator.cc \
        $(ROOT)/src/config/config-loader.cc \
        $(ROOT)/src/config/rl-control.cc \
        $(ROOT)/src/config/layout-override.cc \
        $(ROOT)/src/util/string-utils.cc \
        $(ROOT)/src/util/ini-parser.cc

OUT := config-validator-test

.PHONY: all test clean

all: $(OUT)

$(OUT): $(SRCS) config-test-support.h
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $(SRCS)

test: $(OUT)
	@./$(OUT)

clean:
	rm -f $(OUT)
