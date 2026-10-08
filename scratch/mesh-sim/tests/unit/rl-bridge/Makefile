CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..
COMMON   := ../../common

SRCS := rl-bridge-test.cc \
        $(ROOT)/src/rl/rl-bridge.cc \
        $(ROOT)/src/eval/link-table.cc

OUT := rl-bridge-test

# ns3/ stub directory lets #include "ns3/..." resolve without real ns-3.
NS3_STUBS := ns3/log.h ns3/random-variable-stream.h ns3/constant-velocity-mobility-model.h

.PHONY: all test clean

all: $(OUT)

$(OUT): $(NS3_STUBS) $(SRCS) ns3-mobility-stub.h
	$(CXX) $(CXXFLAGS) -I. -I$(ROOT) -o $@ $(SRCS)

ns3/log.h: $(COMMON)/ns3-log-stub.h
	@mkdir -p ns3
	@ln -sf ../../../common/ns3-log-stub.h ns3/log.h

ns3/random-variable-stream.h: ns3-mobility-stub.h
	@mkdir -p ns3
	@ln -sf ../ns3-mobility-stub.h ns3/random-variable-stream.h

ns3/constant-velocity-mobility-model.h: ns3-mobility-stub.h
	@mkdir -p ns3
	@ln -sf ../ns3-mobility-stub.h ns3/constant-velocity-mobility-model.h

test: $(OUT)
	@./$(OUT)

clean:
	rm -f $(OUT)
	rm -rf ns3
