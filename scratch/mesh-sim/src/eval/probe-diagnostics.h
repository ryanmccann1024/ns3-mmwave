#pragma once
#include "src/domain/probe-spec.h"
#include "src/domain/sim-config.h"

#include <string>
#include <vector>

namespace mesh_sim
{
std::vector<std::string> ProbeDiagnostics(const SimConfig&, const ProbeGrid*);
}
