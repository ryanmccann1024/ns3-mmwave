#include "coverage-grid.h"
#include "sinr-capacity.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace mesh_sim
{
CoverageGrid BuildCoverageGrid(const RlConfig& cfg, const std::vector<BuildingSpec>& buildings)
{
    CoverageGrid grid;
    const double width = cfg.x_max - cfg.x_min, height = cfg.y_max - cfg.y_min;
    grid.area_m2 = width * height;
    const double cell = std::max(cfg.coverage_min_resolution_m,
                                std::sqrt(grid.area_m2 / cfg.coverage_grid_cells));
    const auto nx = static_cast<size_t>(std::ceil(width / cell - 1e-9));
    const auto ny = static_cast<size_t>(std::ceil(height / cell - 1e-9));
    if (nx * ny > 10000) throw std::runtime_error("RL coverage grid exceeds 10000 probes");
    grid.probes.height_m = cfg.coverage_probe_height_m;
    grid.probes.rx_gain_dbi = cfg.coverage_probe_rx_gain_dbi;
    grid.probes.sinr_db = cfg.coverage_sinr_db;
    for (size_t y = 0; y < ny; ++y)
        for (size_t x = 0; x < nx; ++x)
        {
            const double x0 = cfg.x_min + x * cell, y0 = cfg.y_min + y * cell;
            const double x1 = std::min(cfg.x_max, x0 + cell);
            const double y1 = std::min(cfg.y_max, y0 + cell);
            const double px = (x0+x1)/2, py = (y0+y1)/2;
            if (std::any_of(buildings.begin(), buildings.end(), [&](const BuildingSpec& b) {
                return px >= b.x_min && px <= b.x_max && py >= b.y_min && py <= b.y_max &&
                    cfg.coverage_probe_height_m >= b.z_min && cfg.coverage_probe_height_m <= b.z_max;
            })) continue;
            grid.probes.points.push_back({(x0 + x1) / 2, (y0 + y1) / 2,
                                          cfg.coverage_probe_height_m});
            grid.areas.push_back((x1 - x0) * (y1 - y0));
        }
    if (!buildings.empty())
    {
        grid.area_m2 = 0.0;
        for (const auto area : grid.areas) grid.area_m2 += area;
    }
    if (grid.areas.empty()) throw std::runtime_error("coverage grid has no outdoor probes");
    return grid;
}

std::vector<uint32_t> ConnectedCore(const LinkTable& links, const std::vector<bool>& available)
{
    const auto n = links.NumNodes();
    std::vector<bool> seen(n, false);
    std::vector<uint32_t> core;
    for (uint32_t root = 0; root < n; ++root)
    {
        if (seen[root] || (!available.empty() && !available[root])) continue;
        std::vector<uint32_t> part{root};
        seen[root] = true;
        for (size_t k = 0; k < part.size(); ++k)
            for (uint32_t j = 0; j < n; ++j)
                if (!seen[j] && (available.empty() || available[j]) && links.Get(part[k], j).sinr_db >= SINR_MIN_DB)
                {
                    seen[j] = true;
                    part.push_back(j);
                }
        if (part.size() > core.size()) core = part;
    }
    return core;
}

double ConnectedCoverage(const LinkTable& links, const CoverageGrid& grid,
                         const std::vector<std::vector<bool>>& covered, const std::vector<bool>& available)
{
    const auto core = ConnectedCore(links, available);
    double area = 0.0;
    for (size_t p = 0; p < grid.areas.size(); ++p)
        for (const auto node : core)
            if (covered.at(node).at(p))
            {
                area += grid.areas[p];
                break;
            }
    return std::clamp(area / grid.area_m2, 0.0, 1.0);
}

double GoalCoverage(const LinkTable& links, const CoverageGrid& grid,
                    const std::vector<std::vector<bool>>& covered, const MissionConfig& mission,
                    const std::vector<bool>& available)
{
    const auto core = ConnectedCore(links, available);
    double total = 0.0, served = 0.0;
    for (size_t p = 0; p < grid.areas.size(); ++p)
    {
        const auto& point = grid.probes.points[p];
        if (std::hypot(point.x-mission.goal_x, point.y-mission.goal_y) > mission.coverage_radius_m) continue;
        total += grid.areas[p];
        for (const auto node : core) if (covered.at(node).at(p)) { served += grid.areas[p]; break; }
    }
    if (total == 0.0) throw std::runtime_error("mission goal region contains no outdoor coverage probes");
    return served / total;
}
}
