#pragma once
#include "src/domain/probe-spec.h"
#include "src/domain/sim-config.h"
#include "link-table.h"

namespace mesh_sim
{
struct CoverageGrid
{
    ProbeGrid probes;
    std::vector<double> areas;
    double area_m2 = 0.0;
};
CoverageGrid BuildCoverageGrid(const RlConfig& cfg);
double ConnectedCoverage(const LinkTable& links, const CoverageGrid& grid,
                         const std::vector<std::vector<bool>>& covered);
}
