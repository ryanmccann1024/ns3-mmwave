/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */

/**
 * @file config-validator.cc
 * @brief Implements @ref mesh_sim::ValidateConfig; rules are listed in config-validator.h.
 */


#include "src/config/config-validator.h"
#include "src/config/query-config.h"

#include "src/config/rl-control.h"

#include <algorithm>
#include <cmath>
#include <initializer_list>

namespace mesh_sim
{

/** @brief Append an error to @p r if @p val is not > 0. */
static void
checkPositive(ValidationResult& r, const std::string& field, double val)
{
    if (!(val > 0.0))
    {
        r.errors.push_back(field + " must be > 0 (got " + std::to_string(val) + ")");
    }
}

/** @brief Append an error to @p r if @p val is not one of @p allowed. */
static void
checkOneOf(ValidationResult& r,
           const std::string& field,
           const std::string& val,
           std::initializer_list<std::string> allowed)
{
    if (std::find(allowed.begin(), allowed.end(), val) == allowed.end())
    {
        std::string opts;
        for (const auto& a : allowed)
        {
            if (!opts.empty())
                opts += ", ";
            opts += "'" + a + "'";
        }
        r.errors.push_back(field + ": unknown value '" + val +
                           "' (must be one of: " + opts + ")");
    }
}

/** @brief See config-validator.h; collects every error rather than stopping at the first. */
ValidationResult
ValidateConfig(const SimConfig& cfg)
{
    ValidationResult r;

    const auto queryErrors = ValidateQueryConfig(cfg.query);
    r.errors.insert(r.errors.end(), queryErrors.begin(), queryErrors.end());

    // -- timing --
    checkPositive(r, "duration_s", cfg.duration_s);
    checkPositive(r, "tick_s", cfg.tick_s);
    if (std::isinf(cfg.duration_s))
        r.errors.push_back("duration_s must be finite");

    if (cfg.tick_s > cfg.duration_s)
    {
        r.errors.push_back("tick_s (" + std::to_string(cfg.tick_s) +
                           ") must be <= duration_s (" +
                           std::to_string(cfg.duration_s) + ")");
    }
    if (!std::isfinite(cfg.warmup_s) || cfg.warmup_s < 0.0)
    {
        r.errors.push_back("warmup_s must be finite and >= 0 (got " +
                           std::to_string(cfg.warmup_s) + ")");
    }
    if (cfg.warmup_s >= cfg.duration_s && cfg.duration_s > 0.0)
    {
        r.errors.push_back("warmup_s (" + std::to_string(cfg.warmup_s) +
                           ") must be < duration_s (" +
                           std::to_string(cfg.duration_s) + ")");
    }

    // -- nodes --
    if (cfg.nodes.size() < 2)
    {
        r.errors.push_back("at least 2 nodes required (got " +
                           std::to_string(cfg.nodes.size()) + ")");
    }

    for (const auto& node : cfg.nodes)
    {
        checkOneOf(r, "node '" + node.id + "' mobility", node.mobility,
                   {"fixed", "constant_velocity", "random_walk", "waypoint"});

        if (node.mobility == "waypoint")
        {
            const std::string label = "node '" + node.id + "' waypoints";
            if (node.waypoints.size() < 2)
            {
                r.errors.push_back(label + ": need at least 2 waypoints (got " +
                                   std::to_string(node.waypoints.size()) + ")");
            }
            for (size_t i = 1; i < node.waypoints.size(); ++i)
            {
                if (!(node.waypoints[i].t > node.waypoints[i - 1].t))
                {
                    r.errors.push_back(label + ": time must be strictly monotonic " +
                                       "(index " + std::to_string(i) + " t=" +
                                       std::to_string(node.waypoints[i].t) + " <= " +
                                       std::to_string(node.waypoints[i - 1].t) + ")");
                    break;
                }
            }
            if (!node.waypoints.empty() && !(node.waypoints.front().t >= 0.0))
            {
                r.errors.push_back(label + ": first waypoint t must be >= 0 (got " +
                                   std::to_string(node.waypoints.front().t) + ")");
            }
        }

        if (node.tx_array_gain_dbi.has_value() && !(*node.tx_array_gain_dbi >= 0.0))
        {
            r.errors.push_back("node '" + node.id +
                               "' tx_array_gain_dbi must be >= 0 (got " +
                               std::to_string(*node.tx_array_gain_dbi) + ")");
        }
        if (node.rx_array_gain_dbi.has_value() && !(*node.rx_array_gain_dbi >= 0.0))
        {
            r.errors.push_back("node '" + node.id +
                               "' rx_array_gain_dbi must be >= 0 (got " +
                               std::to_string(*node.rx_array_gain_dbi) + ")");
        }
    }

    // -- channel --
    checkPositive(r, "channel.frequency_ghz", cfg.channel.frequency_ghz);
    checkPositive(r, "channel.bandwidth_mhz", cfg.channel.bandwidth_mhz);
    checkOneOf(r, "channel.channel_model", cfg.channel.channel_model,
               {"3gpp", "nyu"});
    checkOneOf(r, "channel.condition_model", cfg.channel.condition_model,
               {"auto", "static_los"});
    checkOneOf(r, "channel.scenario", cfg.channel.scenario,
               {"UMi", "UMa", "RMa", "InH", "InF"});
    checkOneOf(r, "channel.band", cfg.band, {"mmwave", "sub-6"});
    if (!(cfg.channel.tx_array_gain_dbi >= 0.0))
    {
        r.errors.push_back("channel.tx_array_gain_dbi must be >= 0 (got " +
                           std::to_string(cfg.channel.tx_array_gain_dbi) + ")");
    }
    if (!(cfg.channel.rx_array_gain_dbi >= 0.0))
    {
        r.errors.push_back("channel.rx_array_gain_dbi must be >= 0 (got " +
                           std::to_string(cfg.channel.rx_array_gain_dbi) + ")");
    }

    // -- traffic --
    const auto& tc = cfg.mesh.traffic;
    checkOneOf(r, "traffic.model", tc.model,
               {"constant", "poisson", "on_off"});
    checkOneOf(r, "traffic.flow_topology", tc.flow_topology,
               {"all_pairs", "random_pairs", "gateway", "explicit_pairs"});
    checkPositive(r, "traffic.demand_mbps", tc.demand_mbps);
    if (tc.model == "on_off")
    {
        if (!std::isfinite(tc.on_time_s) || tc.on_time_s < 0.0 ||
            !std::isfinite(tc.off_time_s) || tc.off_time_s < 0.0 ||
            (tc.on_time_s == 0.0 && tc.off_time_s == 0.0))
            r.errors.push_back("traffic on/off phases must be finite, nonnegative, and not both zero");
    }

    if (tc.flow_topology == "explicit_pairs")
    {
        if (tc.pairs.empty()) r.errors.push_back("explicit_pairs requires nonempty traffic.pairs");
        if (tc.model != "constant") r.errors.push_back("explicit_pairs requires constant traffic");
        std::vector<std::pair<std::string,std::string>> seen;
        for (const auto& pair : tc.pairs)
        {
            for (const auto& id : {pair.src,pair.dst})
                if (std::none_of(cfg.nodes.begin(),cfg.nodes.end(),[&](const NodeSpec& n){return n.id==id;}))
                    r.errors.push_back("traffic pair references unknown peer '"+id+"'");
            if (pair.src == pair.dst) r.errors.push_back("traffic pair endpoints must differ");
            if (!std::isfinite(pair.demand_mbps) || pair.demand_mbps <= 0)
                r.errors.push_back("traffic pair demand must be finite and positive");
            const auto key = std::make_pair(pair.src,pair.dst);
            if (std::find(seen.begin(),seen.end(),std::make_pair(key.first,key.second))!=seen.end())
                r.errors.push_back("duplicate directed traffic pair");
            seen.emplace_back(key.first,key.second);
        }
    }
    else if (!tc.pairs.empty()) r.errors.push_back("traffic.pairs requires explicit_pairs topology");

    if (tc.flow_topology == "gateway")
    {
        if (tc.gateway_node_id.empty())
        {
            r.errors.push_back(
                "traffic.gateway_node_id is required when flow_topology='gateway'");
        }
        else
        {
            bool found = false;
            for (const auto& n : cfg.nodes)
            {
                if (n.id == tc.gateway_node_id)
                {
                    found = true;
                    break;
                }
            }
            if (!found)
            {
                r.errors.push_back(
                    "traffic.gateway_node_id '" + tc.gateway_node_id +
                    "' does not match any node ID");
            }
        }
    }

    if (tc.flow_topology == "random_pairs" && tc.random_pair_count == 0)
    {
        r.errors.push_back(
            "traffic.random_pair_count must be > 0 when flow_topology='random_pairs'");
    }

    // -- routing --
    checkOneOf(r, "routing.algorithm", cfg.mesh.routing.algorithm,
               {"shortest_path", "max_throughput", "min_hop"});

    // -- node types --
    for (const auto& node : cfg.nodes)
    {
        checkOneOf(r, "node '" + node.id + "' node_type", node.node_type,
                   {"drone", "vehicle", "pedestrian"});
    }

    if (!std::isfinite(cfg.rl.building_clearance_m) || cfg.rl.building_clearance_m < 0)
        r.errors.push_back("rl.building_clearance_m must be finite and nonnegative");

    // Mission and dropout are opt-in; ordinary scenes retain their old contract.
    const auto& mission = cfg.rl.mission;
    checkOneOf(r, "mission.kind", mission.kind, {"none", "coverage", "investigation", "recovery"});
    if (mission.kind != "none")
    {
        if (!cfg.rl.enabled || !cfg.rl.coverage_enabled)
            r.errors.push_back("mission requires enabled RL and coverage");
        for (const auto& value : std::vector<std::pair<std::string, double>>{
                 {"arrival_radius_m", mission.arrival_radius_m},
                 {"coverage_radius_m", mission.coverage_radius_m}, {"dwell_s", mission.dwell_s},
                 {"team_radius_m", mission.team_radius_m}})
            if (!std::isfinite(value.second) || value.second <= 0.0)
                r.errors.push_back("mission." + value.first + " must be finite and positive");
        for (const auto& value : std::vector<std::pair<std::string, double>>{
                 {"team_delivery_target", mission.team_delivery_target},
                 {"goal_coverage_target", mission.goal_coverage_target},
                 {"recovery_delivery_target", mission.recovery_delivery_target},
                 {"recovery_coverage_ratio", mission.recovery_coverage_ratio},
                 {"recovery_worst_target", mission.recovery_worst_target}})
        {
            // Zero disables these secondary gates for an investigation-only task.
            const bool zeroAllowed = value.first == "recovery_coverage_ratio" ||
                (mission.kind == "investigation" &&
                 (value.first == "team_delivery_target" || value.first == "goal_coverage_target"));
            if (!std::isfinite(value.second) || value.second < 0.0 ||
                (!zeroAllowed && value.second == 0.0) || value.second > 1.0)
                r.errors.push_back("mission." + value.first +
                    (zeroAllowed ? " must be in [0,1]" : " must be in (0,1]"));
        }
        if (!std::isfinite(mission.goal_x) || !std::isfinite(mission.goal_y) ||
            mission.goal_x < cfg.rl.x_min || mission.goal_x > cfg.rl.x_max ||
            mission.goal_y < cfg.rl.y_min || mission.goal_y > cfg.rl.y_max)
            r.errors.push_back("mission goal must be finite and within RL bounds");
        if (mission.team_investigation && mission.kind != "investigation")
            r.errors.push_back("team_investigation requires mission.kind=investigation");
        if (mission.kind == "investigation")
        {
            const auto it = std::find_if(cfg.nodes.begin(), cfg.nodes.end(),
                [&](const NodeSpec& n) { return n.id == mission.investigator_id; });
            if (it == cfg.nodes.end()) r.errors.push_back("mission investigator_id must identify a peer");
            else
            {
                if (it->failure_at_s >= 0) r.errors.push_back("investigator cannot have a scheduled dropout");
                const auto control = ResolveRlControl(cfg);
                const auto index = static_cast<uint32_t>(std::distance(cfg.nodes.begin(), it));
                if (std::find(control.controlled_indices.begin(), control.controlled_indices.end(), index) == control.controlled_indices.end())
                    r.errors.push_back("mission investigator must be a controlled peer");
            }
        }
    }
    size_t failed = 0;
    for (const auto& node : cfg.nodes)
    {
        if (!std::isfinite(node.failure_at_s) ||
            (node.failure_at_s != -1.0 && (node.failure_at_s <= 0.0 || node.failure_at_s >= cfg.duration_s)))
            r.errors.push_back("node failure_at_s must be -1 or in (0,duration_s)");
        if (node.failure_at_s >= 0.0)
        {
            ++failed;
            if (mission.kind != "recovery") r.errors.push_back("node dropout requires mission.kind=recovery");
            const double ticks = node.failure_at_s / cfg.tick_s;
            if (std::abs(ticks - std::round(ticks)) > 1e-6)
                r.errors.push_back("node failure_at_s must align with a simulator tick");
        }
    }
    if (mission.kind == "recovery" && (failed == 0 || cfg.nodes.size() - failed < 2))
        r.errors.push_back("recovery requires a dropout and at least two surviving peers");

    // -- rl --
    if (!std::isfinite(cfg.rl.control_start_s) || cfg.rl.control_start_s < 0 ||
        cfg.rl.control_start_s >= cfg.duration_s)
        r.errors.push_back("rl.control_start_s must be finite in [0,duration_s)");
    if (cfg.rl.control_start_s > 0)
    {
        const double dt = cfg.rl.decision_interval_s > 0 ? cfg.rl.decision_interval_s : cfg.tick_s;
        if (!cfg.rl.enabled || !cfg.rl.controlled_nodes_set)
            r.errors.push_back("rl.control_start_s requires enabled centralized control");
        if (dt > 0 && std::abs(cfg.rl.control_start_s / dt -
                             std::round(cfg.rl.control_start_s / dt)) > 1e-8)
            r.errors.push_back("rl.control_start_s must align to a decision boundary");
    }
    if (cfg.rl.enabled)
    {
        checkOneOf(r, "rl.reward_type", cfg.rl.reward_type,
                   {"throughput", "all_links_los"});

        if (!(cfg.rl.x_min < cfg.rl.x_max))
            r.errors.push_back("rl.x_min must be < rl.x_max");
        if (!(cfg.rl.y_min < cfg.rl.y_max))
            r.errors.push_back("rl.y_min must be < rl.y_max");
        if (!(cfg.rl.z_min < cfg.rl.z_max))
            r.errors.push_back("rl.z_min must be < rl.z_max");

        checkPositive(r, "rl.unsafe_separation_m", cfg.rl.unsafe_separation_m);
        if (!std::isfinite(cfg.rl.unsafe_separation_m))
            r.errors.push_back("rl.unsafe_separation_m must be finite");
        if (cfg.rl.coverage_enabled)
        {
            if (!cfg.rl.controlled_nodes_set)
                r.errors.push_back("rl.coverage_enabled requires centralized control");
            if (cfg.rl.coverage_grid_cells < 1 || cfg.rl.coverage_grid_cells > 10000)
                r.errors.push_back("baseline.coverage_grid_cells must be in [1,10000] for RL coverage");
            checkPositive(r, "baseline.grid_min_resolution_m", cfg.rl.coverage_min_resolution_m);
            if (!std::isfinite(cfg.rl.coverage_min_resolution_m))
                r.errors.push_back("baseline.grid_min_resolution_m must be finite");
            if (!std::isfinite(cfg.rl.coverage_probe_height_m) || cfg.rl.coverage_probe_height_m < 0)
                r.errors.push_back("baseline.coverage_probe_height_m must be finite and nonnegative");
            if (!std::isfinite(cfg.rl.coverage_probe_rx_gain_dbi) || cfg.rl.coverage_probe_rx_gain_dbi < 0)
                r.errors.push_back("baseline.coverage_probe_rx_gain_dbi must be finite and nonnegative");
            if (!std::isfinite(cfg.rl.coverage_sinr_db))
                r.errors.push_back("baseline.coverage_sinr_db must be finite");
        }

        if (cfg.rl.avoid_node_collisions)
        {
            if (!cfg.rl.controlled_nodes_set)
                r.errors.push_back("rl.avoid_node_collisions requires centralized control");
            for (size_t i = 0; i < cfg.nodes.size(); ++i)
            {
                const auto a = ControlledStartPosition(cfg.nodes[i]);
                for (size_t j = i + 1; j < cfg.nodes.size(); ++j)
                {
                    const auto b = ControlledStartPosition(cfg.nodes[j]);
                    if (std::hypot(std::hypot(a.x-b.x, a.y-b.y), a.z-b.z) < cfg.rl.unsafe_separation_m)
                        r.errors.push_back("unsafe initial node separation: " + cfg.nodes[i].id + " / " + cfg.nodes[j].id);
                }
            }
        }

        // Slot/cadence/start-position rules live in the shared resolver.
        const RlControlResolution ctl = ResolveRlControl(cfg);
        r.errors.insert(r.errors.end(), ctl.errors.begin(), ctl.errors.end());
    }

    // -- baseline -- value only; the direct-run guard needs the explicit --rl-mode flag (sim.cc).
    checkOneOf(r, "baseline.algorithm", cfg.baseline.algorithm,
               {"none", "geometric", "optimization"});

    // -- jammers --
    for (const auto& j : cfg.jammers)
    {
        std::string label = "jammer '" + j.id + "'";

        // Type check
        checkOneOf(r, label + " type", j.type, {"constant", "random"});

        // Power / duty cycle
        if (!(j.duty_cycle >= 0.0 && j.duty_cycle <= 1.0))
        {
            r.errors.push_back(label + ": duty_cycle must be in [0, 1] (got " +
                               std::to_string(j.duty_cycle) + ")");
        }

        // Beamwidth in (0, 360]; azimuth in [0, 360)
        if (!(j.beamwidth_deg > 0.0 && j.beamwidth_deg <= 360.0))
        {
            r.errors.push_back(label + ": beamwidth_deg must be in (0, 360] (got " +
                               std::to_string(j.beamwidth_deg) + ")");
        }

        // Interval check: each [start, end) must be ordered and non-negative.
        for (const auto& iv : j.intervals)
        {
            if (!(iv.start >= 0.0))
            {
                r.errors.push_back(label + ": interval start must be >= 0 (got " +
                                   std::to_string(iv.start) + ")");
            }
            if (!(iv.end > iv.start))
            {
                r.errors.push_back(label + ": interval end must be > start (got start=" +
                                   std::to_string(iv.start) + ", end=" +
                                   std::to_string(iv.end) + ")");
            }
        }

        // Random-walk bounds (the only bounds a JammerSpec carries).
        if (j.type == "random")
        {
            if (!(j.random_walk.x_min < j.random_walk.x_max))
                r.errors.push_back(label + ": random_walk x_min must be < x_max");
            if (!(j.random_walk.y_min < j.random_walk.y_max))
                r.errors.push_back(label + ": random_walk y_min must be < y_max");
        }
    }
    
    if (cfg.rl.enabled && cfg.rl.avoid_buildings)
        for (const auto& node : cfg.nodes)
            for (const auto& b : cfg.buildings)
            {
                const auto& p = node.position; const double c = cfg.rl.building_clearance_m;
                if (p.x >= b.x_min-c && p.x <= b.x_max+c &&
                    p.y >= b.y_min-c && p.y <= b.y_max+c &&
                    p.z >= b.z_min-c && p.z <= b.z_max+c)
                    r.errors.push_back("node '"+node.id+"' starts inside building clearance");
            }

    // -- buildings --
    for (const auto& b : cfg.buildings)
    {
        std::string label = "building '" + b.id + "'";
        if (!(b.x_min < b.x_max))
            r.errors.push_back(label + ": x_min must be < x_max");
        if (!(b.y_min < b.y_max))
            r.errors.push_back(label + ": y_min must be < y_max");
        if (!(b.z_min < b.z_max))
            r.errors.push_back(label + ": z_min must be < z_max");
    }

    return r;
}

}  // namespace mesh_sim
