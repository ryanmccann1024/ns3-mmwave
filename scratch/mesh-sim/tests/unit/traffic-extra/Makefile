CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..
COMMON   := ../../common

# config-validator (ns-3-free) is linked only to show that configurations
# exposing suspected traffic bugs pass validation.
SRCS := traffic-extra-test.cc \
        $(ROOT)/src/traffic/traffic-matrix.cc \
        $(ROOT)/src/config/config-validator.cc \
        $(ROOT)/src/config/rl-control.cc \
        $(ROOT)/src/util/string-utils.cc

OUT := traffic-extra-test

# ns3/ stub directory lets #include "ns3/..." resolve without real ns-3.
NS3_STUBS := ns3/log.h ns3/random-variable-stream.h ns3/double.h

.PHONY: all test clean

all: $(OUT)

$(OUT): $(NS3_STUBS) $(SRCS) ns3-traffic-extra-stub.h
	$(CXX) $(CXXFLAGS) -I. -I$(ROOT) -o $@ $(SRCS)

ns3/log.h: $(COMMON)/ns3-log-stub.h
	@mkdir -p ns3
	@ln -sf ../../../common/ns3-log-stub.h ns3/log.h

ns3/random-variable-stream.h: ns3-traffic-extra-stub.h
	@mkdir -p ns3
	@ln -sf ../ns3-traffic-extra-stub.h ns3/random-variable-stream.h

ns3/double.h: ns3-traffic-extra-stub.h
	@mkdir -p ns3
	@ln -sf ../ns3-traffic-extra-stub.h ns3/double.h

test: $(OUT)
	@./$(OUT)

clean:
	rm -f $(OUT)
	rm -rf ns3
