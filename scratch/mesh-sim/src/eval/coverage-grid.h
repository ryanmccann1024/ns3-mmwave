#pragma once

#include "link-table.h"
#include "src/domain/probe-spec.h"
#include "src/domain/sim-config.h"

namespace mesh_sim
{
/// Receiver centers and their clipped cell areas in the same order.
struct CoverageGrid
{
    ProbeGrid probes;
    std::vector<double> areas; ///< Cell areas in square meters.
    double area_m2 = 0.0;      ///< Total area represented by the retained cells.
};

/// Tile the RL bounds and omit centers inside the supplied buildings at probe height.
/// Throws if no cells remain or a required investigation goal contains no retained center.
CoverageGrid BuildCoverageGrid(const RlConfig& cfg,
                               const std::vector<BuildingSpec>& buildings = {});

/// Largest component of available peers with usable links. Ties favor the first roster index.
/// An empty availability vector includes the entire roster.
std::vector<uint32_t> ConnectedCore(const LinkTable& links,
                                    const std::vector<bool>& available = {});

/// Fraction of grid area served by the connected core. Index coverage as [node][probe].
double ConnectedCoverage(const LinkTable& links,
                         const CoverageGrid& grid,
                         const std::vector<std::vector<bool>>& covered,
                         const std::vector<bool>& available = {});

/// Coverage within the goal radius, measured by retained cell centers.
/// An empty goal region yields zero when the investigation coverage gate is disabled.
double GoalCoverage(const LinkTable& links,
                    const CoverageGrid& grid,
                    const std::vector<std::vector<bool>>& covered,
                    const MissionConfig& mission,
                    const std::vector<bool>& available);
} // namespace mesh_sim
