#include "coverage-grid.h"

#include "sinr-capacity.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace mesh_sim
{
namespace
{
bool
IsGoalProbe(const Position& point, const MissionConfig& mission)
{
    return std::hypot(point.x - mission.goal_x, point.y - mission.goal_y) <=
           mission.coverage_radius_m;
}

bool
IsIndoor(const Position& point, const std::vector<BuildingSpec>& buildings)
{
    return std::any_of(buildings.begin(), buildings.end(), [&](const BuildingSpec& building) {
        return point.x >= building.x_min && point.x <= building.x_max &&
               point.y >= building.y_min && point.y <= building.y_max &&
               point.z >= building.z_min && point.z <= building.z_max;
    });
}

bool
IsCovered(size_t probe,
          const std::vector<uint32_t>& core,
          const std::vector<std::vector<bool>>& covered)
{
    return std::any_of(core.begin(), core.end(), [&](uint32_t node) {
        return covered.at(node).at(probe);
    });
}

constexpr auto kEmptyGoalRegion = "mission goal region contains no outdoor coverage probes";
} // namespace

CoverageGrid
BuildCoverageGrid(const RlConfig& cfg, const std::vector<BuildingSpec>& buildings)
{
    CoverageGrid grid;
    const double width = cfg.x_max - cfg.x_min;
    const double height = cfg.y_max - cfg.y_min;
    const double rectangleArea = width * height;
    const double cell =
        std::max(cfg.coverage_min_resolution_m, std::sqrt(rectangleArea / cfg.coverage_grid_cells));
    const auto nx = static_cast<size_t>(std::ceil(width / cell - 1e-9));
    const auto ny = static_cast<size_t>(std::ceil(height / cell - 1e-9));
    if (nx * ny > 10000)
    {
        throw std::runtime_error("RL coverage grid exceeds 10000 probes");
    }

    grid.probes.height_m = cfg.coverage_probe_height_m;
    grid.probes.rx_gain_dbi = cfg.coverage_probe_rx_gain_dbi;
    grid.probes.sinr_db = cfg.coverage_sinr_db;
    for (size_t y = 0; y < ny; ++y)
    {
        for (size_t x = 0; x < nx; ++x)
        {
            const double x0 = cfg.x_min + x * cell;
            const double y0 = cfg.y_min + y * cell;
            const double x1 = std::min(cfg.x_max, x0 + cell);
            const double y1 = std::min(cfg.y_max, y0 + cell);
            const Position center{(x0 + x1) / 2, (y0 + y1) / 2, cfg.coverage_probe_height_m};
            if (IsIndoor(center, buildings))
            {
                continue;
            }
            const double area = (x1 - x0) * (y1 - y0);
            grid.probes.points.push_back(center);
            grid.areas.push_back(area);
            grid.area_m2 += area;
        }
    }
    if (grid.areas.empty())
    {
        throw std::runtime_error("coverage grid has no outdoor probes");
    }
    if (buildings.empty())
    {
        grid.area_m2 = rectangleArea;
    }

    if (cfg.mission.kind == "investigation" && cfg.mission.goal_coverage_target > 0.0 &&
        std::none_of(grid.probes.points.begin(), grid.probes.points.end(), [&](const auto& point) {
            return IsGoalProbe(point, cfg.mission);
        }))
    {
        throw std::runtime_error(kEmptyGoalRegion);
    }
    return grid;
}

std::vector<uint32_t>
ConnectedCore(const LinkTable& links, const std::vector<bool>& available)
{
    const auto nodeCount = links.NumNodes();
    std::vector<bool> seen(nodeCount, false);
    std::vector<uint32_t> core;
    for (uint32_t root = 0; root < nodeCount; ++root)
    {
        if (seen[root] || (!available.empty() && !available[root]))
        {
            continue;
        }
        std::vector<uint32_t> component{root};
        seen[root] = true;
        for (size_t k = 0; k < component.size(); ++k)
        {
            for (uint32_t peer = 0; peer < nodeCount; ++peer)
            {
                if (!seen[peer] && (available.empty() || available[peer]) &&
                    links.Get(component[k], peer).sinr_db >= SINR_MIN_DB)
                {
                    seen[peer] = true;
                    component.push_back(peer);
                }
            }
        }
        if (component.size() > core.size())
        {
            core = std::move(component);
        }
    }
    return core;
}

double
ConnectedCoverage(const LinkTable& links,
                  const CoverageGrid& grid,
                  const std::vector<std::vector<bool>>& covered,
                  const std::vector<bool>& available)
{
    const auto core = ConnectedCore(links, available);
    double area = 0.0;
    for (size_t probe = 0; probe < grid.areas.size(); ++probe)
    {
        if (IsCovered(probe, core, covered))
        {
            area += grid.areas[probe];
        }
    }
    return std::clamp(area / grid.area_m2, 0.0, 1.0);
}

double
GoalCoverage(const LinkTable& links,
             const CoverageGrid& grid,
             const std::vector<std::vector<bool>>& covered,
             const MissionConfig& mission,
             const std::vector<bool>& available)
{
    const auto core = ConnectedCore(links, available);
    double goalArea = 0.0;
    double coveredArea = 0.0;
    for (size_t probe = 0; probe < grid.areas.size(); ++probe)
    {
        if (!IsGoalProbe(grid.probes.points[probe], mission))
        {
            continue;
        }
        goalArea += grid.areas[probe];
        if (IsCovered(probe, core, covered))
        {
            coveredArea += grid.areas[probe];
        }
    }
    if (goalArea > 0.0)
    {
        return coveredArea / goalArea;
    }
    if (mission.goal_coverage_target > 0.0)
    {
        throw std::runtime_error(kEmptyGoalRegion);
    }
    return 0.0;
}
} // namespace mesh_sim
