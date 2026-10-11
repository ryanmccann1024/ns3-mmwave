#include "src/query/layout-evaluation.h"

#include "src/config/layout-override.h"
#include "src/eval/link-evaluator.h"
#include "src/eval/probe-diagnostics.h"
#include "src/eval/sinr-capacity.h"
#include "src/query/child-process.h"
#include "src/setup/topology-builder.h"

#include "ns3/rng-seed-manager.h"

#include <chrono>
#include <cmath>

namespace mesh_sim::query
{
using Clock = std::chrono::steady_clock;

double
SecondsSince(Clock::time_point t0)
{
    return std::chrono::duration<double>(Clock::now() - t0).count();
}

// Runs only in a forked child; mirrors sim.cc's per-seed setup and tick-0 evaluation.
ojson
EvaluateInChild(SimConfig cfg, uint32_t planningSeed, const ProbeGrid* probes)
{
    // As in sim.cc, the resolved run seed also reaches JammerModel through cfg.seed.
    cfg.seed = planningSeed;
    ns3::RngSeedManager::SetSeed(planningSeed);
    ns3::RngSeedManager::SetRun(cfg.run_id);

    TopologyBuilder topo(cfg);
    if (probes != nullptr)
    {
        topo.SetProbes(*probes);
    }
    topo.Build();
    const auto mobs = topo.GetMobilityModels();
    const auto jammerMobs = topo.GetJammerMobilityModels();

    LinkEvaluator linkEval;
    linkEval.Configure(cfg,
                       topo.GetPropagationModel(),
                       topo.GetConditionModel(),
                       cfg.band,
                       jammerMobs);

    // Draw order is part of the realization: all mesh pairs first, exactly as tick 0 of a run.
    const auto links = linkEval.EvaluateAll(mobs, 0.0);
    ojson rows = ojson::array();
    for (const auto& r : links)
    {
        if (!std::isfinite(r.sinr_db) || !std::isfinite(r.capacity_mbps))
        {
            return LayoutError("non-finite channel result for link " + std::to_string(r.tx_id) +
                               "-" + std::to_string(r.rx_id));
        }
        rows.push_back(ojson::array(
            {r.tx_id, r.rx_id, r.sinr_db, r.capacity_mbps, r.is_los, r.sinr_db >= SINR_MIN_DB}));
    }

    ojson coverage = nullptr;
    if (probes != nullptr)
    {
        const auto probeMobs = topo.GetProbeMobilityModels();
        coverage = ojson::array();
        for (uint32_t i = 0; i < mobs.size(); ++i)
        {
            ojson covered = ojson::array();
            for (std::size_t k = 0; k < probeMobs.size(); ++k)
            {
                const LinkResult r =
                    linkEval.EvaluateProbe(mobs[i], probeMobs[k], i, probes->rx_gain_dbi, 0.0);
                if (!std::isfinite(r.sinr_db))
                {
                    return LayoutError("non-finite channel result for node " + std::to_string(i) +
                                       " probe " + std::to_string(k));
                }
                if (r.sinr_db >= probes->sinr_db)
                {
                    covered.push_back(k);
                }
            }
            coverage.push_back(std::move(covered));
        }
    }

    ojson result;
    result["diagnostics"] = ProbeDiagnostics(cfg, probes);
    result["links"] = std::move(rows);
    result["coverage"] = std::move(coverage);
    return result;
}

ojson
EvaluateLayout(const SimConfig& cfg,
               uint32_t planningSeed,
               const std::vector<Position>& layout,
               const ProbeGrid* probes,
               std::ostream& out)
{
    const auto t0 = Clock::now();
    SimConfig layoutCfg = cfg;
    const auto errors = ApplyLayout(layoutCfg, layout);
    if (!errors.empty())
    {
        std::string msg = "invalid layout:";
        for (const auto& e : errors)
        {
            msg += " " + e + ";";
        }
        msg.pop_back();
        return LayoutError(msg);
    }

    std::string body;
    std::string failure;
    if (!RunChild(
            [&]() {
                try
                {
                    return EvaluateInChild(layoutCfg, planningSeed, probes).dump();
                }
                catch (const std::exception& e)
                {
                    return LayoutError(std::string("child evaluation failed: ") + e.what()).dump();
                }
            },
            cfg.query,
            out,
            body,
            failure))
    {
        return LayoutError(failure);
    }
    ojson result = ojson::parse(body, nullptr, false);
    if (result.is_discarded() || !result.is_object())
    {
        return LayoutError("unparsable child output");
    }
    if (result.contains("error"))
    {
        return LayoutError(result["error"].is_string() ? result["error"].get<std::string>()
                                                       : "child reported an error");
    }
    if (!result.contains("links") || !result["links"].is_array() || !result.contains("coverage"))
    {
        return LayoutError("unparsable child output");
    }
    result["wall_s"] = SecondsSince(t0);
    return result;
}

} // namespace mesh_sim::query
