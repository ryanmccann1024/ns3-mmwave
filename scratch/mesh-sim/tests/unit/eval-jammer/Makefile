CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..
COMMON   := ../../common

SRCS := eval-jammer-test.cc \
        $(ROOT)/src/eval/link-table.cc \
        $(ROOT)/src/eval/link-evaluator.cc \
        $(ROOT)/src/jammer/jammer-model.cc

OUT := eval-jammer-test

# link-evaluator.cc and jammer-model.cc include ns-3 headers. The local,
# gitignored ns3/ dir maps them onto deterministic stubs: log.h onto the shared
# common/ns3-log-stub.h, and the propagation / mobility / channel-condition
# headers onto stubs/ns3-eval-jammer-stub.h (tests control path loss,
# positions and LOS through subclasses).
NS3_LOG   := ns3/log.h
NS3_MODEL := ns3/mobility-model.h ns3/propagation-loss-model.h ns3/channel-condition-model.h
NS3_STUBS := $(NS3_LOG) $(NS3_MODEL)
MODEL_STUB := stubs/ns3-eval-jammer-stub.h

.PHONY: all test clean

all: $(OUT)

$(OUT): $(NS3_STUBS) $(MODEL_STUB) $(SRCS)
	$(CXX) $(CXXFLAGS) -I. -I$(ROOT) -o $@ $(SRCS)

$(NS3_LOG): $(COMMON)/ns3-log-stub.h
	@mkdir -p ns3
	@ln -sf ../../../common/ns3-log-stub.h $@

$(NS3_MODEL): $(MODEL_STUB)
	@mkdir -p ns3
	@ln -sf ../$(MODEL_STUB) $@

test: $(OUT)
	@./$(OUT)

clean:
	rm -f $(OUT)
	rm -rf ns3
