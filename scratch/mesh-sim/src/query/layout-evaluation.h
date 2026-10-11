#pragma once
#include "src/query/query-protocol.h"

namespace mesh_sim::query
{
ojson EvaluateLayout(const SimConfig&,
                     uint32_t,
                     const std::vector<Position>&,
                     const ProbeGrid*,
                     std::ostream&);
}
