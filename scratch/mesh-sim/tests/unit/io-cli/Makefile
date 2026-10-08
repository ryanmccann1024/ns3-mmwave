CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..
COMMON   := ../../common

SRCS := io-cli-test.cc \
        $(ROOT)/src/io/metrics-writer.cc \
        $(ROOT)/src/io/viz-writer.cc \
        $(ROOT)/src/cli/cli-parser.cc \
        $(ROOT)/src/eval/link-table.cc \
        $(ROOT)/src/util/string-utils.cc

HDRS := $(ROOT)/src/io/run-logger.h \
        $(ROOT)/src/io/progress-logger.h \
        $(ROOT)/src/io/metrics-writer.h \
        $(ROOT)/src/io/viz-writer.h \
        $(ROOT)/src/cli/cli-parser.h

OUT := io-cli-test

# ns3/ stub directory (gitignored) lets #include "ns3/..." resolve without real
# ns-3. log/random come from common/; mobility and command-line from stubs/.
NS3_STUBS := ns3/log.h ns3/random-variable-stream.h \
             ns3/mobility-model.h ns3/command-line.h

.PHONY: all test clean

all: $(OUT)

$(OUT): $(NS3_STUBS) $(SRCS) $(HDRS) stubs/ns3-mobility-stub.h stubs/ns3-command-line-stub.h
	$(CXX) $(CXXFLAGS) -I. -I$(ROOT) -o $@ $(SRCS)

ns3/log.h: $(COMMON)/ns3-log-stub.h
	@mkdir -p ns3
	@ln -sf ../../../common/ns3-log-stub.h ns3/log.h

ns3/random-variable-stream.h: $(COMMON)/ns3-random-stub.h
	@mkdir -p ns3
	@ln -sf ../../../common/ns3-random-stub.h ns3/random-variable-stream.h

ns3/mobility-model.h: stubs/ns3-mobility-stub.h
	@mkdir -p ns3
	@ln -sf ../stubs/ns3-mobility-stub.h ns3/mobility-model.h

ns3/command-line.h: stubs/ns3-command-line-stub.h
	@mkdir -p ns3
	@ln -sf ../stubs/ns3-command-line-stub.h ns3/command-line.h

test: $(OUT)
	@./$(OUT)

clean:
	rm -f $(OUT)
	rm -rf ns3
