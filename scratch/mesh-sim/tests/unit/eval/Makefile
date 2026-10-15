CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wpedantic
ROOT     := ../../..
COMMON   := ../../common

SRCS := eval-test.cc \
        $(ROOT)/src/eval/link-table.cc \
        $(ROOT)/src/eval/coverage-grid.cc

OUT := eval-test

# The ns3/ stub directory lets #include "ns3/log.h" resolve without real ns-3.
NS3_STUB := ns3/log.h

.PHONY: all test clean

all: $(OUT) reconfigure-test

$(OUT): $(NS3_STUB) $(SRCS)
	$(CXX) $(CXXFLAGS) -I. -I$(ROOT) -o $@ $(SRCS)

$(NS3_STUB): $(COMMON)/ns3-log-stub.h
	@mkdir -p ns3
	@ln -sf ../../../common/ns3-log-stub.h ns3/log.h

MODEL_HEADERS := ns3/mobility-model.h ns3/propagation-loss-model.h ns3/channel-condition-model.h
$(MODEL_HEADERS): stubs/ns3-eval-stub.h
	@mkdir -p ns3
	@ln -sf ../stubs/ns3-eval-stub.h $@

reconfigure-test: reconfigure-test.cc $(NS3_STUB) $(MODEL_HEADERS) stubs/ns3-eval-stub.h $(ROOT)/src/eval/link-evaluator.cc $(ROOT)/src/jammer/jammer-model.cc
	$(CXX) $(CXXFLAGS) -I. -I$(ROOT) -o $@ reconfigure-test.cc $(ROOT)/src/eval/link-evaluator.cc $(ROOT)/src/jammer/jammer-model.cc

test: $(OUT) reconfigure-test
	@./$(OUT)
	@./reconfigure-test

clean:
	rm -f $(OUT) reconfigure-test
	rm -rf ns3
