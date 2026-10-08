CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..

SRCS := config-rules-test.cc \
        $(ROOT)/src/config/config-validator.cc \
        $(ROOT)/src/config/config-loader.cc \
        $(ROOT)/src/config/rl-control.cc \
        $(ROOT)/src/config/layout-override.cc \
        $(ROOT)/src/util/string-utils.cc \
        $(ROOT)/src/util/ini-parser.cc

OUT := config-rules-test

.PHONY: all test clean

all: $(OUT)

$(OUT): $(SRCS)
	$(CXX) $(CXXFLAGS) -I$(ROOT) -o $@ $^

test: $(OUT)
	@./$(OUT)

clean:
	rm -f $(OUT)
