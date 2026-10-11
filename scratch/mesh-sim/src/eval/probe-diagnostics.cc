#include "src/eval/probe-diagnostics.h"

#include "src/config/rl-control.h"

#include <algorithm>

namespace mesh_sim
{
std::vector<std::string>
ProbeDiagnostics(const SimConfig& cfg, const ProbeGrid* probes)
{
    std::vector<std::string> warnings;
    if (!probes || probes->points.empty() || cfg.channel.channel_model != "3gpp")
        return warnings;
    const auto& scenario = cfg.channel.scenario;
    for (const auto& node : cfg.nodes)
    {
        const double z = ControlledStartPosition(node).z;
        const double lower = std::min(z, probes->height_m);
        const double upper = std::max(z, probes->height_m);
        bool valid = true;
        std::string expected;
        if (scenario == "RMa")
        {
            valid = lower >= 1 && lower <= 10 && upper >= 10 && upper <= 150;
            expected = "lower endpoint 1..10 m and higher endpoint 10..150 m";
        }
        else if (scenario == "UMa")
        {
            valid = lower >= 1.5 && lower <= 22.5 && upper == 25;
            expected = "lower endpoint 1.5..22.5 m and higher endpoint 25 m";
        }
        else if (scenario == "UMi")
        {
            valid = lower >= 1.5 && lower < 10 && upper == 10;
            expected = "lower endpoint [1.5,10) m and higher endpoint 10 m";
        }
        if (!valid)
            warnings.push_back("3GPP " + scenario + " probe link to node '" + node.id +
                               "' is outside height assumptions (" + expected +
                               "); coverage is extrapolated");
    }
    return warnings;
}
} // namespace mesh_sim
