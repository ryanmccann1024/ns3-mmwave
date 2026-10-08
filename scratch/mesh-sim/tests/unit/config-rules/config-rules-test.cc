/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file config-rules-test.cc
 * @brief Boundary and contract tests for ValidateConfig, ResolveRlControl,
 *        ApplyRlControl, ComputeTickCount, ControlledStartPosition, and
 *        ApplyLayout that complement tests/unit/config.
 *
 * Standalone binary, no ns-3 dependency.
 * Build and run: `make -C tests/unit/config-rules test`.
 */

#include "src/config/config-loader.h"
#include "src/config/config-validator.h"
#include "src/config/layout-override.h"
#include "src/config/rl-control.h"
#include "src/domain/node-spec.h"

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include <unistd.h>

using namespace mesh_sim;

// ---- helpers ----

static int g_pass = 0;
static int g_fail = 0;

static void
check(bool cond, const std::string& name)
{
    if (cond)
    {
        ++g_pass;
    }
    else
    {
        ++g_fail;
        std::cerr << "FAIL: " << name << "\n";
    }
}

static const double kNaN = std::numeric_limits<double>::quiet_NaN();
static const double kInf = std::numeric_limits<double>::infinity();

static NodeSpec
makeNode(const std::string& id, double x = 0.0, double y = 0.0, double z = 0.0)
{
    NodeSpec n;
    n.id        = id;
    n.role      = "peer";
    n.mobility  = "fixed";
    n.node_type = "drone";
    n.position  = Position{x, y, z};
    return n;
}

/// Minimal valid non-RL config with two fixed drones.
static SimConfig
makeValid()
{
    SimConfig cfg;
    cfg.scenario_name = "rules";
    cfg.duration_s    = 10.0;
    cfg.warmup_s      = 0.0;
    cfg.tick_s        = 0.1;

    cfg.channel.frequency_ghz = 28.0;
    cfg.channel.bandwidth_mhz = 400.0;
    cfg.channel.channel_model = "3gpp";
    cfg.channel.scenario      = "UMi";

    cfg.mesh.traffic.model         = "constant";
    cfg.mesh.traffic.demand_mbps   = 10.0;
    cfg.mesh.traffic.flow_topology = "all_pairs";
    cfg.mesh.routing.algorithm     = "shortest_path";

    cfg.nodes.push_back(makeNode("node0", 0.0, 0.0, 10.0));
    cfg.nodes.push_back(makeNode("node1", 100.0, 0.0, 10.0));
    return cfg;
}

/// Centralized RL config ("all") with @p n fixed nodes at (10*i, 20, 10).
static SimConfig
makeRlCfg(size_t n = 3)
{
    SimConfig cfg = makeValid();
    cfg.nodes.clear();
    for (size_t i = 0; i < n; ++i)
    {
        cfg.nodes.push_back(makeNode("node-" + std::to_string(i),
                                     10.0 * static_cast<double>(i), 20.0, 10.0));
    }
    cfg.rl.enabled              = true;
    cfg.rl.controlled_nodes_set = true;
    cfg.rl.controlled_nodes     = "all";
    return cfg;
}

/// Valid jammer; JammerSpec has no default member initializers, so value-init it.
static JammerSpec
makeJammer(const std::string& id)
{
    JammerSpec j{};
    j.enabled       = true;
    j.id            = id;
    j.type          = "constant";
    j.tx_power_dbm  = 25.0;
    j.duty_cycle    = 1.0;
    j.beamwidth_deg = 360.0;
    j.random_walk   = RandomWalkParams{};
    return j;
}

static BuildingSpec
makeBuilding(const std::string& id)
{
    BuildingSpec b;
    b.id    = id;
    b.x_min = 0.0;
    b.x_max = 10.0;
    b.y_min = 0.0;
    b.y_max = 10.0;
    b.z_min = 0.0;
    b.z_max = 10.0;
    return b;
}

static bool
hasIn(const std::vector<std::string>& errors, const std::string& substr)
{
    for (const auto& e : errors)
    {
        if (e.find(substr) != std::string::npos)
        {
            return true;
        }
    }
    return false;
}

static size_t
countIn(const std::vector<std::string>& errors, const std::string& substr)
{
    size_t n = 0;
    for (const auto& e : errors)
    {
        if (e.find(substr) != std::string::npos)
        {
            ++n;
        }
    }
    return n;
}

static bool
hasError(const ValidationResult& r, const std::string& substr)
{
    return hasIn(r.errors, substr);
}

static bool
hasResErr(const RlControlResolution& r, const std::string& substr)
{
    return hasIn(r.errors, substr);
}

/// Resolve without letting an exception escape; @p threw reports one.
static RlControlResolution
resolveNoThrow(const SimConfig& cfg, bool& threw)
{
    threw = false;
    try
    {
        return ResolveRlControl(cfg);
    }
    catch (...)
    {
        threw = true;
        return RlControlResolution{};
    }
}

static ValidationResult
validateNoThrow(const SimConfig& cfg, bool& threw)
{
    threw = false;
    try
    {
        return ValidateConfig(cfg);
    }
    catch (...)
    {
        threw = true;
        return ValidationResult{};
    }
}

// =====================================================================
// ValidateConfig -- timing
// =====================================================================

static void
test_timing_boundaries()
{
    auto cfg = makeValid();
    cfg.tick_s = cfg.duration_s;
    check(ValidateConfig(cfg).ok(), "timing: tick_s == duration_s accepted (rule tick <= duration)");

    cfg = makeValid();
    cfg.tick_s = -0.1;
    auto r = ValidateConfig(cfg);
    check(hasError(r, "tick_s must be > 0"), "timing: negative tick_s rejected");

    cfg = makeValid();
    cfg.warmup_s = cfg.duration_s - 1e-9;
    check(ValidateConfig(cfg).ok(), "timing: warmup just below duration accepted");

    cfg = makeValid();
    cfg.warmup_s = 0.0;
    check(ValidateConfig(cfg).ok(), "timing: warmup_s == 0 accepted (rule warmup >= 0)");

    cfg = makeValid();
    cfg.warmup_s = cfg.duration_s + 5.0;
    r = ValidateConfig(cfg);
    check(hasError(r, "warmup_s (") && hasError(r, "must be < duration_s"),
          "timing: warmup beyond duration names warmup_s and duration_s");

    cfg = makeValid();
    cfg.duration_s = 0.0;
    cfg.tick_s     = 0.0;
    r = ValidateConfig(cfg);
    check(hasError(r, "duration_s must be > 0") && hasError(r, "tick_s must be > 0"),
          "timing: zero duration and zero tick both reported");
}

// =====================================================================
// ValidateConfig -- nodes and waypoints
// =====================================================================

static void
test_nodes_mobility_and_type_values()
{
    for (const char* mob : {"fixed", "constant_velocity", "random_walk", "waypoint"})
    {
        auto cfg = makeValid();
        cfg.nodes[1].mobility  = mob;
        cfg.nodes[1].waypoints = {{0.0, 100.0, 0.0, 10.0}, {1.0, 110.0, 0.0, 10.0}};
        check(ValidateConfig(cfg).ok(), std::string("nodes: mobility '") + mob + "' accepted");
    }
    for (const char* mob : {"Fixed", "", "static"})
    {
        auto cfg = makeValid();
        cfg.nodes[0].mobility = mob;
        auto r = ValidateConfig(cfg);
        check(hasError(r, "node 'node0' mobility: unknown value"),
              std::string("nodes: mobility '") + mob + "' rejected (case-sensitive set)");
    }

    for (const char* type : {"drone", "vehicle", "pedestrian"})
    {
        auto cfg = makeValid();
        cfg.nodes[1].node_type = type;
        check(ValidateConfig(cfg).ok(), std::string("nodes: node_type '") + type + "' accepted");
    }
    for (const char* type : {"boat", "", "Drone"})
    {
        auto cfg = makeValid();
        cfg.nodes[1].node_type = type;
        auto r = ValidateConfig(cfg);
        check(hasError(r, "node 'node1' node_type: unknown value"),
              std::string("nodes: node_type '") + type + "' rejected");
    }

    auto cfg = makeValid();
    cfg.nodes.resize(1);
    auto r = ValidateConfig(cfg);
    check(hasError(r, "at least 2 nodes required (got 1)"), "nodes: single node message names count");
}

static void
test_waypoint_rules()
{
    auto base = makeValid();
    base.nodes[1].mobility = "waypoint";

    auto cfg = base;
    cfg.nodes[1].waypoints = {{0.0, 1.0, 2.0, 3.0}, {0.5, 1.0, 2.0, 3.0}};
    check(ValidateConfig(cfg).ok(), "waypoint: two increasing waypoints from t=0 accepted");

    cfg = base;
    cfg.nodes[1].waypoints.clear();
    auto r = ValidateConfig(cfg);
    check(hasError(r, "node 'node1' waypoints: need at least 2 waypoints (got 0)"),
          "waypoint: zero waypoints rejected");

    cfg = base;
    cfg.nodes[1].waypoints = {{0.0, 1.0, 2.0, 3.0}};
    r = ValidateConfig(cfg);
    check(hasError(r, "need at least 2 waypoints (got 1)"), "waypoint: one waypoint rejected");

    cfg = base;
    cfg.nodes[1].waypoints = {{1.0, 0, 0, 0}, {1.0, 5, 0, 0}};
    r = ValidateConfig(cfg);
    check(hasError(r, "time must be strictly monotonic"),
          "waypoint: equal consecutive times rejected (strict)");

    cfg = base;
    cfg.nodes[1].waypoints = {{2.0, 0, 0, 0}, {1.0, 5, 0, 0}};
    r = ValidateConfig(cfg);
    check(hasError(r, "time must be strictly monotonic"), "waypoint: decreasing times rejected");

    cfg = base;
    cfg.nodes[1].waypoints = {{0.0, 0, 0, 0}, {1.0, 5, 0, 0}, {1.0, 6, 0, 0}};
    r = ValidateConfig(cfg);
    check(hasError(r, "(index 2 t="), "waypoint: violation at index 2 is located at index 2");

    cfg = base;
    cfg.nodes[1].waypoints = {{-0.5, 0, 0, 0}, {1.0, 5, 0, 0}};
    r = ValidateConfig(cfg);
    check(hasError(r, "first waypoint t must be >= 0"), "waypoint: negative first t rejected");

    cfg = base;
    cfg.nodes[1].waypoints = {{-1.0, 0, 0, 0}};
    r = ValidateConfig(cfg);
    check(hasError(r, "need at least 2 waypoints (got 1)") &&
              hasError(r, "first waypoint t must be >= 0"),
          "waypoint: single negative-t waypoint reports both rules");

    // Rules apply only to waypoint mobility.
    cfg = makeValid();
    cfg.nodes[0].waypoints = {{5.0, 0, 0, 0}, {-1.0, 0, 0, 0}};
    check(ValidateConfig(cfg).ok(), "waypoint: rules ignored for a fixed node with a waypoints list");

    // Every waypoint node is checked.
    cfg = makeValid();
    cfg.nodes[0].mobility = "waypoint";
    cfg.nodes[1].mobility = "waypoint";
    r = ValidateConfig(cfg);
    check(hasError(r, "node 'node0' waypoints") && hasError(r, "node 'node1' waypoints"),
          "waypoint: errors reported for each waypoint node");
}

// =====================================================================
// ValidateConfig -- channel
// =====================================================================

static void
test_channel_rules()
{
    for (const char* sc : {"UMi", "UMa", "RMa", "InH", "InF"})
    {
        auto cfg = makeValid();
        cfg.channel.scenario = sc;
        check(ValidateConfig(cfg).ok(), std::string("channel: scenario '") + sc + "' accepted");
    }
    auto cfg = makeValid();
    cfg.channel.scenario = "umi";
    check(hasError(ValidateConfig(cfg), "channel.scenario: unknown value 'umi'"),
          "channel: scenario is case-sensitive");

    cfg = makeValid();
    cfg.channel.channel_model = "nyu";
    check(ValidateConfig(cfg).ok(), "channel: channel_model 'nyu' accepted");

    for (const char* cm : {"auto", "static_los"})
    {
        cfg = makeValid();
        cfg.channel.condition_model = cm;
        check(ValidateConfig(cfg).ok(), std::string("channel: condition_model '") + cm + "' accepted");
    }
    cfg = makeValid();
    cfg.channel.condition_model = "buildings";
    check(hasError(ValidateConfig(cfg), "channel.condition_model: unknown value 'buildings'"),
          "channel: unknown condition_model rejected");

    cfg = makeValid();
    cfg.band = "sub-6";
    check(ValidateConfig(cfg).ok(), "channel: band 'sub-6' accepted");

    cfg = makeValid();
    cfg.channel.bandwidth_mhz = 0.0;
    check(hasError(ValidateConfig(cfg), "channel.bandwidth_mhz must be > 0"),
          "channel: bandwidth_mhz == 0 rejected");

    cfg = makeValid();
    cfg.channel.frequency_ghz = -28.0;
    check(hasError(ValidateConfig(cfg), "channel.frequency_ghz must be > 0"),
          "channel: negative frequency rejected");
}

static void
test_array_gain_rules()
{
    auto cfg = makeValid();
    cfg.channel.tx_array_gain_dbi = 0.0;
    cfg.channel.rx_array_gain_dbi = 0.0;
    check(ValidateConfig(cfg).ok(), "gain: channel gains of exactly 0 accepted (rule >= 0)");

    cfg = makeValid();
    cfg.channel.tx_array_gain_dbi = -0.1;
    auto r = ValidateConfig(cfg);
    check(hasError(r, "channel.tx_array_gain_dbi must be >= 0"), "gain: negative channel tx gain rejected");
    check(!hasError(r, "channel.rx_array_gain_dbi"), "gain: rx not reported when only tx is bad");

    cfg = makeValid();
    cfg.channel.rx_array_gain_dbi = -0.1;
    check(hasError(ValidateConfig(cfg), "channel.rx_array_gain_dbi must be >= 0"),
          "gain: negative channel rx gain rejected");

    cfg = makeValid();
    cfg.nodes[0].tx_array_gain_dbi = -1.0;
    r = ValidateConfig(cfg);
    check(hasError(r, "node 'node0' tx_array_gain_dbi must be >= 0"),
          "gain: negative per-node tx override rejected with node id");

    cfg = makeValid();
    cfg.nodes[1].rx_array_gain_dbi = -1.0;
    r = ValidateConfig(cfg);
    check(hasError(r, "node 'node1' rx_array_gain_dbi must be >= 0"),
          "gain: negative per-node rx override rejected with node id");

    cfg = makeValid();
    cfg.nodes[0].tx_array_gain_dbi = 0.0;
    cfg.nodes[0].rx_array_gain_dbi = 0.0;
    check(ValidateConfig(cfg).ok(), "gain: per-node overrides of exactly 0 accepted");

    // A valid per-node override does not hide an invalid channel default.
    cfg = makeValid();
    cfg.channel.tx_array_gain_dbi  = -3.0;
    cfg.nodes[0].tx_array_gain_dbi = 5.0;
    cfg.nodes[1].tx_array_gain_dbi = 5.0;
    check(hasError(ValidateConfig(cfg), "channel.tx_array_gain_dbi"),
          "gain: channel default checked even when every node overrides it");
}

static void
test_amc_model_rule()
{
    // QUESTION: amc_model has a documented closed set (run-ini-reference.md:49:
    // shannon, table, silvus) and src/config/CLAUDE.md asks for a ValidateConfig
    // rule for constrained keys, but config-validator.cc never checks it; an
    // unknown value only throws later from SinrToCapacity (sinr-capacity.h:303)
    // after the run has started.
    for (const char* amc : {"shannon", "table", "silvus"})
    {
        auto cfg = makeValid();
        cfg.channel.amc_model = amc;
        check(ValidateConfig(cfg).ok(), std::string("amc: '") + amc + "' accepted");
    }
    auto cfg = makeValid();
    cfg.channel.amc_model = "bogus";
    check(hasError(ValidateConfig(cfg), "amc_model"),
          "amc: unknown amc_model rejected by ValidateConfig [QUESTION: not validated]");
}

// =====================================================================
// ValidateConfig -- traffic and routing
// =====================================================================

static void
test_traffic_rules()
{
    for (const char* m : {"constant", "poisson", "on_off"})
    {
        auto cfg = makeValid();
        cfg.mesh.traffic.model = m;
        check(ValidateConfig(cfg).ok(), std::string("traffic: model '") + m + "' accepted");
    }

    auto cfg = makeValid();
    cfg.mesh.traffic.demand_mbps = 0.0;
    check(hasError(ValidateConfig(cfg), "traffic.demand_mbps must be > 0"),
          "traffic: demand_mbps == 0 rejected");

    cfg = makeValid();
    cfg.mesh.traffic.flow_topology     = "random_pairs";
    cfg.mesh.traffic.random_pair_count = 1;
    check(ValidateConfig(cfg).ok(), "traffic: random_pairs with count 1 accepted");

    cfg = makeValid();
    cfg.mesh.traffic.flow_topology     = "all_pairs";
    cfg.mesh.traffic.random_pair_count = 0;
    check(ValidateConfig(cfg).ok(), "traffic: random_pair_count 0 ignored for all_pairs");

    cfg = makeValid();
    cfg.mesh.traffic.flow_topology   = "all_pairs";
    cfg.mesh.traffic.gateway_node_id = "ghost";
    check(ValidateConfig(cfg).ok(), "traffic: gateway_node_id ignored unless topology is gateway");

    cfg = makeValid();
    cfg.mesh.traffic.flow_topology   = "gateway";
    cfg.mesh.traffic.gateway_node_id = "jam-1";
    cfg.band = "sub-6";
    cfg.jammers.push_back(makeJammer("jam-1"));
    check(hasError(ValidateConfig(cfg), "traffic.gateway_node_id 'jam-1' does not match any node ID"),
          "traffic: gateway id that names a jammer rejected");

    cfg = makeValid();
    cfg.mesh.traffic.flow_topology   = "gateway";
    cfg.mesh.traffic.gateway_node_id = "node1";
    cfg.mesh.traffic.random_pair_count = 0;
    check(ValidateConfig(cfg).ok(), "traffic: gateway topology with a real node accepted");
}

static void
test_routing_rules()
{
    for (const char* a : {"shortest_path", "max_throughput", "min_hop"})
    {
        auto cfg = makeValid();
        cfg.mesh.routing.algorithm = a;
        check(ValidateConfig(cfg).ok(), std::string("routing: '") + a + "' accepted");
    }
    auto cfg = makeValid();
    cfg.mesh.routing.algorithm = "";
    check(hasError(ValidateConfig(cfg), "routing.algorithm: unknown value ''"),
          "routing: empty algorithm rejected");
}

// =====================================================================
// ValidateConfig -- RL (validator-owned rules)
// =====================================================================

static void
test_rl_validator_rules()
{
    // Legacy RL base: no controlled_nodes key.
    auto legacy = makeValid();
    legacy.rl.enabled = true;
    check(ValidateConfig(legacy).ok(), "rl: default legacy RL config accepted");

    auto cfg = legacy;
    cfg.rl.action_type = "hybrid";
    check(hasError(ValidateConfig(cfg), "rl.action_type: unknown value 'hybrid'"),
          "rl: unknown action_type rejected");

    cfg = legacy;
    cfg.rl.reward_type = "all_links_los";
    check(ValidateConfig(cfg).ok(), "rl: reward_type all_links_los accepted");

    cfg = legacy;
    cfg.rl.action_type         = "continuous";
    cfg.rl.arrival_threshold_m = 0.0;
    check(hasError(ValidateConfig(cfg), "rl.arrival_threshold_m must be > 0"),
          "rl: continuous with arrival_threshold_m == 0 rejected");

    cfg = legacy;
    cfg.rl.action_type = "continuous";
    cfg.rl.step_size_m = 0.0;
    check(!hasError(ValidateConfig(cfg), "rl.step_size_m"),
          "rl: step_size_m not checked in legacy continuous mode");

    cfg = legacy;
    cfg.rl.action_type         = "discrete";
    cfg.rl.arrival_threshold_m = 0.0;
    check(ValidateConfig(cfg).ok(), "rl: arrival_threshold_m not checked in discrete mode");

    cfg = legacy;
    cfg.rl.step_size_m = 0.0;
    check(hasError(ValidateConfig(cfg), "rl.step_size_m must be > 0"),
          "rl: discrete step_size_m == 0 rejected");

    cfg = legacy;
    cfg.rl.x_min = cfg.rl.x_max = 5.0;
    check(hasError(ValidateConfig(cfg), "rl.x_min must be < rl.x_max"),
          "rl: x_min == x_max rejected (strict)");

    cfg = legacy;
    cfg.rl.y_min = cfg.rl.y_max = 5.0;
    check(hasError(ValidateConfig(cfg), "rl.y_min must be < rl.y_max"),
          "rl: y_min == y_max rejected (strict)");

    cfg = legacy;
    cfg.rl.y_min = 10.0;
    cfg.rl.y_max = -10.0;
    check(hasError(ValidateConfig(cfg), "rl.y_min must be < rl.y_max"),
          "rl: inverted y bounds rejected");

    cfg = legacy;
    cfg.rl.z_min = cfg.rl.z_max = 50.0;
    check(hasError(ValidateConfig(cfg), "rl.z_min must be < rl.z_max"),
          "rl: z_min == z_max rejected (strict)");

    // controlled_node_id: validator rejects an unmatched id even though the
    // resolver would fall back to the last node.
    cfg = legacy;
    cfg.rl.controlled_node_id = "ghost";
    check(hasError(ValidateConfig(cfg), "rl.controlled_node_id 'ghost' does not match any node ID"),
          "rl: unmatched controlled_node_id rejected by the validator");
    check(ResolveRlControl(cfg).ok(), "rl: resolver alone accepts unmatched legacy id (fallback)");

    cfg = legacy;
    cfg.band = "sub-6";
    cfg.jammers.push_back(makeJammer("jam-1"));
    cfg.rl.controlled_node_id = "jam-1";
    check(hasError(ValidateConfig(cfg), "rl.controlled_node_id 'jam-1' does not match any node ID"),
          "rl: controlled_node_id naming a jammer rejected");

    cfg = legacy;
    cfg.rl.controlled_node_id = "node0";
    check(ValidateConfig(cfg).ok(), "rl: matching controlled_node_id accepted");

    // RL disabled: no RL rule runs at all.
    cfg = makeValid();
    cfg.rl.enabled              = false;
    cfg.rl.action_type          = "hybrid";
    cfg.rl.reward_type          = "nope";
    cfg.rl.step_size_m          = -1.0;
    cfg.rl.x_min                = 10.0;
    cfg.rl.x_max                = -10.0;
    cfg.rl.controlled_node_id   = "ghost";
    cfg.rl.controlled_nodes_set = true;
    cfg.rl.controlled_nodes     = "";
    cfg.rl.decision_interval_s  = -1.0;
    check(ValidateConfig(cfg).ok(), "rl: disabled RL ignores every RL field");
}

static void
test_rl_validator_interactions()
{
    // A controlled waypoint node without waypoints: validator must report, not throw.
    auto cfg = makeRlCfg();
    cfg.nodes[1].mobility = "waypoint";
    cfg.nodes[1].waypoints.clear();
    cfg.rl.controlled_nodes = "node-1";
    bool threw = false;
    auto r = validateNoThrow(cfg, threw);
    check(!threw, "rl interaction: controlled waypoint node without waypoints does not throw");
    check(hasError(r, "need at least 2 waypoints (got 0)") &&
              hasError(r, "waypoint node 'node-1' has no waypoints"),
          "rl interaction: both node rule and resolver rule reported");

    // Legacy RL with no nodes: no underflowed index, both errors reported.
    cfg = makeValid();
    cfg.nodes.clear();
    cfg.rl.enabled = true;
    r = validateNoThrow(cfg, threw);
    check(!threw, "rl interaction: legacy RL with no nodes does not throw");
    check(hasError(r, "at least 2 nodes required (got 0)") &&
              hasError(r, "rl control requires at least one mesh node"),
          "rl interaction: no-node errors from validator and resolver");

    // Centralized: bad timing reported by both layers.
    cfg = makeRlCfg();
    cfg.tick_s = 20.0;
    r = ValidateConfig(cfg);
    check(hasError(r, "tick_s (") && hasError(r, "rl timing is invalid"),
          "rl interaction: tick > duration reported by validator and resolver");
}

// =====================================================================
// ValidateConfig -- jammers and buildings
// =====================================================================

static void
test_jammer_rules()
{
    auto base = makeValid();
    base.band = "sub-6";
    base.jammers.push_back(makeJammer("jam-1"));
    check(ValidateConfig(base).ok(), "jammer: valid constant jammer accepted");

    auto cfg = base;
    cfg.jammers[0].type = "random";
    cfg.jammers[0].random_walk = RandomWalkParams{};
    check(ValidateConfig(cfg).ok(), "jammer: valid random jammer accepted");

    cfg = base;
    cfg.jammers[0].type = "pulsed";
    check(hasError(ValidateConfig(cfg), "jammer 'jam-1' type: unknown value 'pulsed'"),
          "jammer: unknown type rejected with id");

    for (double d : {0.0, 1.0, 0.5})
    {
        cfg = base;
        cfg.jammers[0].duty_cycle = d;
        check(ValidateConfig(cfg).ok(), "jammer: duty_cycle " + std::to_string(d) + " accepted");
    }
    for (double d : {-0.01, 1.01})
    {
        cfg = base;
        cfg.jammers[0].duty_cycle = d;
        check(hasError(ValidateConfig(cfg), "jammer 'jam-1': duty_cycle must be in [0, 1]"),
              "jammer: duty_cycle " + std::to_string(d) + " rejected");
    }

    for (double bw : {360.0, 1e-6, 60.0})
    {
        cfg = base;
        cfg.jammers[0].beamwidth_deg = bw;
        check(ValidateConfig(cfg).ok(), "jammer: beamwidth " + std::to_string(bw) + " accepted");
    }
    for (double bw : {0.0, -10.0, 360.0001})
    {
        cfg = base;
        cfg.jammers[0].beamwidth_deg = bw;
        check(hasError(ValidateConfig(cfg), "beamwidth_deg must be in (0, 360]"),
              "jammer: beamwidth " + std::to_string(bw) + " rejected");
    }

    cfg = base;
    cfg.jammers[0].intervals = {{0.0, 1.0}, {2.0, 3.5}};
    check(ValidateConfig(cfg).ok(), "jammer: intervals starting at 0 accepted");

    cfg = base;
    cfg.jammers[0].intervals = {{-1.0, 1.0}};
    check(hasError(ValidateConfig(cfg), "interval start must be >= 0"),
          "jammer: negative interval start rejected");

    cfg = base;
    cfg.jammers[0].intervals = {{2.0, 2.0}};
    check(hasError(ValidateConfig(cfg), "interval end must be > start"),
          "jammer: empty interval (end == start) rejected");

    cfg = base;
    cfg.jammers[0].intervals = {{3.0, 1.0}};
    check(hasError(ValidateConfig(cfg), "interval end must be > start"),
          "jammer: reversed interval rejected");

    cfg = base;
    cfg.jammers[0].intervals = {{0.0, 1.0}, {-2.0, -3.0}, {5.0, 4.0}};
    auto r = ValidateConfig(cfg);
    check(countIn(r.errors, "interval end must be > start") == 2 &&
              countIn(r.errors, "interval start must be >= 0") == 1,
          "jammer: every bad interval reported");

    cfg = base;
    cfg.jammers[0].type = "random";
    cfg.jammers[0].random_walk.x_min = cfg.jammers[0].random_walk.x_max = 5.0;
    check(hasError(ValidateConfig(cfg), "random_walk x_min must be < x_max"),
          "jammer: random type x_min == x_max rejected");

    cfg = base;
    cfg.jammers[0].type = "random";
    cfg.jammers[0].random_walk.y_min = 50.0;
    cfg.jammers[0].random_walk.y_max = -50.0;
    check(hasError(ValidateConfig(cfg), "random_walk y_min must be < y_max"),
          "jammer: random type inverted y rejected");

    cfg = base;
    cfg.jammers[0].type = "constant";
    cfg.jammers[0].random_walk.x_min = 50.0;
    cfg.jammers[0].random_walk.x_max = -50.0;
    check(ValidateConfig(cfg).ok(), "jammer: random_walk bounds ignored for constant type");

    cfg = base;
    cfg.jammers.push_back(makeJammer("jam-2"));
    cfg.jammers[0].duty_cycle = 2.0;
    cfg.jammers[1].duty_cycle = -1.0;
    r = ValidateConfig(cfg);
    check(hasError(r, "jammer 'jam-1': duty_cycle") && hasError(r, "jammer 'jam-2': duty_cycle"),
          "jammer: each jammer reported separately");
}

static void
test_building_rules()
{
    auto cfg = makeValid();
    cfg.buildings.push_back(makeBuilding("b1"));
    check(ValidateConfig(cfg).ok(), "building: valid building accepted");

    auto c = cfg;
    c.buildings[0].x_max = c.buildings[0].x_min;
    check(hasError(ValidateConfig(c), "building 'b1': x_min must be < x_max"),
          "building: x_min == x_max rejected");

    c = cfg;
    c.buildings[0].y_min = 20.0;
    auto r = ValidateConfig(c);
    check(hasError(r, "building 'b1': y_min must be < y_max") && !hasError(r, "x_min"),
          "building: inverted y rejected alone");

    c = cfg;
    c.buildings[0].z_max = -1.0;
    check(hasError(ValidateConfig(c), "building 'b1': z_min must be < z_max"),
          "building: inverted z rejected");

    c = cfg;
    c.buildings.push_back(makeBuilding("b2"));
    c.buildings[0].z_max = 0.0;
    c.buildings[1].x_max = -5.0;
    r = ValidateConfig(c);
    check(hasError(r, "building 'b1'") && hasError(r, "building 'b2'"),
          "building: each building reported separately");
}

// =====================================================================
// ValidateConfig -- collect-all and purity
// =====================================================================

static void
test_collect_all_domains()
{
    auto cfg = makeRlCfg();
    cfg.warmup_s                   = -1.0;                // timing
    cfg.nodes[0].node_type         = "boat";              // nodes
    cfg.channel.condition_model    = "x";                 // channel
    cfg.mesh.traffic.model         = "burst";             // traffic
    cfg.mesh.routing.algorithm     = "flood";             // routing
    cfg.rl.reward_type             = "nope";              // rl (validator)
    cfg.rl.controlled_nodes        = "ghost";             // rl (resolver)
    cfg.baseline.algorithm         = "annealing";         // baseline
    cfg.jammers.push_back(makeJammer("jam-1"));
    cfg.jammers[0].beamwidth_deg   = 0.0;                 // jammer
    cfg.buildings.push_back(makeBuilding("b1"));
    cfg.buildings[0].z_max         = 0.0;                 // building

    auto r = ValidateConfig(cfg);
    const std::vector<std::string> expect = {
        "warmup_s must be >= 0",
        "node 'node-0' node_type",
        "channel.condition_model",
        "traffic.model",
        "routing.algorithm",
        "rl.reward_type",
        "rl.controlled_nodes: unknown node id 'ghost'",
        "baseline.algorithm",
        "jammer 'jam-1': beamwidth_deg",
        "building 'b1': z_min",
    };
    for (const auto& e : expect)
    {
        check(hasError(r, e), "collect-all: error present: " + e);
    }
    check(r.errors.size() == expect.size(),
          "collect-all: exactly one error per injected fault (got " +
              std::to_string(r.errors.size()) + ")");

    auto r2 = ValidateConfig(cfg);
    check(r.errors == r2.errors, "collect-all: validation is deterministic");
}

// =====================================================================
// ValidateConfig -- non-finite inputs (NaN / inf)
// =====================================================================

static void
test_validator_rejects_nan()
{
    // Every comparison with NaN is false, so each rule documented as "> 0",
    // ">= 0", "in [0, 1]" or "min < max" (config-validator.h table) must be
    // written so that NaN fails it.
    struct Case
    {
        const char* name;
        void (*mutate)(SimConfig&);
        const char* expect;
    };
    const std::vector<Case> cases = {
        {"duration_s", [](SimConfig& c) { c.duration_s = kNaN; }, "duration_s"},
        {"tick_s", [](SimConfig& c) { c.tick_s = kNaN; }, "tick_s"},
        {"warmup_s", [](SimConfig& c) { c.warmup_s = kNaN; }, "warmup_s"},
        {"frequency_ghz", [](SimConfig& c) { c.channel.frequency_ghz = kNaN; }, "frequency_ghz"},
        {"bandwidth_mhz", [](SimConfig& c) { c.channel.bandwidth_mhz = kNaN; }, "bandwidth_mhz"},
        {"demand_mbps", [](SimConfig& c) { c.mesh.traffic.demand_mbps = kNaN; }, "demand_mbps"},
        {"channel tx gain", [](SimConfig& c) { c.channel.tx_array_gain_dbi = kNaN; },
         "tx_array_gain_dbi"},
        {"node rx gain", [](SimConfig& c) { c.nodes[0].rx_array_gain_dbi = kNaN; },
         "rx_array_gain_dbi"},
        {"legacy rl step_size_m",
         [](SimConfig& c) { c.rl.enabled = true; c.rl.step_size_m = kNaN; }, "step_size_m"},
        {"legacy rl x_min",
         [](SimConfig& c) { c.rl.enabled = true; c.rl.x_min = kNaN; }, "x_min"},
        {"jammer duty_cycle",
         [](SimConfig& c) { c.jammers.push_back(makeJammer("j")); c.jammers[0].duty_cycle = kNaN; },
         "duty_cycle"},
        {"jammer beamwidth",
         [](SimConfig& c) { c.jammers.push_back(makeJammer("j")); c.jammers[0].beamwidth_deg = kNaN; },
         "beamwidth_deg"},
        {"jammer interval end",
         [](SimConfig& c) { c.jammers.push_back(makeJammer("j")); c.jammers[0].intervals = {{0.0, kNaN}}; },
         "interval"},
        {"building x_max",
         [](SimConfig& c) { c.buildings.push_back(makeBuilding("b")); c.buildings[0].x_max = kNaN; },
         "x_min must be < x_max"},
        {"waypoint t",
         [](SimConfig& c) {
             c.nodes[1].mobility  = "waypoint";
             c.nodes[1].waypoints = {{kNaN, 0, 0, 10}, {1.0, 0, 0, 10}};
         },
         "waypoint"},
    };
    for (const auto& c : cases)
    {
        auto cfg = makeValid();
        c.mutate(cfg);
        auto r = ValidateConfig(cfg);
        check(!r.ok() && hasError(r, c.expect),
              std::string("nan: NaN ") + c.name + " rejected");
    }
}

static void
test_validator_infinite_duration()
{
    // An infinite duration_s satisfies the literal "> 0" rule, but the
    // non-RL loop in sim.cc:251 computes static_cast<uint32_t>(inf / tick_s),
    // which is undefined behavior; ComputeTickCount treats non-finite as invalid.
    auto cfg = makeValid();
    cfg.duration_s = kInf;
    check(hasError(ValidateConfig(cfg), "duration_s"),
          "inf: infinite duration_s rejected by ValidateConfig");

    // With RL enabled the resolver already catches it.
    cfg.rl.enabled = true;
    check(hasError(ValidateConfig(cfg), "rl timing is invalid"),
          "inf: infinite duration_s rejected via resolver when RL is enabled");
}

static void
test_loader_nan_repro()
{
    // NaN through a real run.ini (std::stod accepts "nan") must fail validation.
    std::string tmpl = (std::filesystem::temp_directory_path() / "config-rules-XXXXXX").string();
    std::vector<char> buf(tmpl.begin(), tmpl.end());
    buf.push_back('\0');
    char* dir = mkdtemp(buf.data());
    if (dir == nullptr)
    {
        check(false, "loader-nan: could not create temp dir");
        return;
    }
    const std::filesystem::path root(dir);
    {
        std::ofstream ini(root / "run.ini");
        ini << "[scenario]\nname = nan-repro\nduration_s = nan\ntick_s = 0.1\n"
               "nodes_file = nodes.json\n[output]\ndir = "
            << (root / "out").string() << "\n";
        std::ofstream nodes(root / "nodes.json");
        nodes << R"([{"id":"a","position":{"x":0,"y":0,"z":10}},)"
                 R"({"id":"b","position":{"x":50,"y":0,"z":10}}])";
    }
    try
    {
        SimConfig cfg = ConfigLoader::Load((root / "run.ini").string());
        check(std::isnan(cfg.duration_s), "loader-nan: run.ini 'duration_s = nan' loads as NaN");
        check(!ValidateConfig(cfg).ok(),
              "loader-nan: NaN duration from run.ini rejected");
    }
    catch (const std::exception& e)
    {
        check(false, std::string("loader-nan: unexpected exception: ") + e.what());
    }
    std::error_code ec;
    std::filesystem::remove_all(root, ec);
}

// =====================================================================
// ComputeTickCount
// =====================================================================

static void
test_tick_count_boundaries()
{
    check(ComputeTickCount(1.0, 1.0, true) == 1 && ComputeTickCount(1.0, 1.0, false) == 1,
          "ticks: ratio exactly 1 gives 1 in both modes");
    check(ComputeTickCount(0.9999999, 1.0, true) == 0,
          "ticks: ratio below 1 gives 0 even within the robust tolerance (doc)");
    check(ComputeTickCount(0.7, 0.1, false) == 6, "ticks: legacy 0.7/0.1 truncates to 6");
    check(ComputeTickCount(0.7, 0.1, true) == 7, "ticks: robust 0.7/0.1 rounds to 7");

    // 1e-6 tolerance on either side of an integer.
    check(ComputeTickCount(3.0 - 5e-7, 1.0, true) == 3, "ticks: robust 2.9999995 rounds up to 3");
    check(ComputeTickCount(3.0 - 5e-7, 1.0, false) == 2, "ticks: legacy 2.9999995 truncates to 2");
    check(ComputeTickCount(3.0 - 2e-6, 1.0, true) == 2, "ticks: robust 2.999998 floors to 2");
    check(ComputeTickCount(3.0 + 5e-7, 1.0, true) == 3, "ticks: robust 3.0000005 gives 3");
    check(ComputeTickCount(3.0 + 2e-6, 1.0, true) == 3, "ticks: robust 3.000002 floors to 3");
    check(ComputeTickCount(3.5, 1.0, true) == 3, "ticks: robust 3.5 floors to 3 (not rounded)");
    check(ComputeTickCount(3.9, 1.0, true) == 3, "ticks: robust 3.9 floors to 3");

    // Invalid inputs.
    check(ComputeTickCount(-1.0, -0.1, true) == 0 && ComputeTickCount(-1.0, -0.1, false) == 0,
          "ticks: both negative gives 0 (positive ratio not trusted)");
    check(ComputeTickCount(1.0, -0.1, true) == 0, "ticks: negative tick gives 0");
    check(ComputeTickCount(0.0, 0.1, false) == 0, "ticks: zero duration gives 0");
    check(ComputeTickCount(kInf, 1.0, false) == 0, "ticks: infinite duration gives 0");
    check(ComputeTickCount(1.0, kInf, true) == 0, "ticks: infinite tick gives 0");
    check(ComputeTickCount(kNaN, 1.0, true) == 0 && ComputeTickCount(1.0, kNaN, false) == 0,
          "ticks: NaN inputs give 0");
    check(ComputeTickCount(1.0, 1e-320, true) == 0, "ticks: denormal tick (ratio overflows) gives 0");

    // uint32 range.
    check(ComputeTickCount(4294967294.0, 1.0, false) == 4294967294u,
          "ticks: ratio UINT32_MAX-1 accepted");
    check(ComputeTickCount(4294967296.0, 1.0, true) == 0 &&
              ComputeTickCount(4294967296.0, 1.0, false) == 0,
          "ticks: ratio above UINT32_MAX gives 0");
}

// =====================================================================
// ResolveRlControl -- mode, defaults, legacy
// =====================================================================

static void
test_resolver_disabled_defaults()
{
    auto cfg = makeRlCfg();
    cfg.rl.enabled          = false;
    cfg.rl.controlled_nodes = "ghost";
    cfg.tick_s              = 0.0;
    auto r = ResolveRlControl(cfg);
    check(r.ok(), "disabled: errors ignored when RL is disabled");
    check(r.control_mode == "legacy" && r.num_slots == 0 && r.num_ticks == 0 &&
              r.decision_interval_ticks == 1 && r.controlled_indices.empty(),
          "disabled: every resolved field at its default");
}

static void
test_resolver_legacy_ignores_centralized_rules()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes_set = false;
    cfg.rl.controlled_nodes     = "node-0";  // value without the key presence flag
    cfg.rl.action_type          = "continuous";
    cfg.rl.action_profile       = "teleport";
    cfg.rl.decision_interval_s  = 0.15;
    cfg.rl.max_controlled_nodes = 65;
    cfg.nodes[2].position       = Position{9000.0, 9000.0, 900.0};  // outside [rl] bounds
    auto r = ResolveRlControl(cfg);
    check(r.ok(), "legacy: centralized-only rules (profile, cadence, slots, start bounds) skipped");
    check(r.control_mode == "legacy", "legacy: controlled_nodes value without key flag stays legacy");
    check(r.controlled_indices == std::vector<uint32_t>({2}),
          "legacy: controlled_nodes value ignored; last node selected");
    check(r.num_slots == 1 && r.decision_interval_ticks == 1,
          "legacy: one slot and one-tick cadence regardless of decision_interval_s");

    cfg.rl.decision_interval_s  = kNaN;
    cfg.rl.max_controlled_nodes = -3;
    check(ResolveRlControl(cfg).ok(), "legacy: NaN decision interval and negative slot count ignored");
}

static void
test_resolver_legacy_edge_cases()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes_set = false;
    cfg.nodes.clear();
    bool threw = false;
    auto r = resolveNoThrow(cfg, threw);
    check(!threw, "legacy: empty node list does not throw");
    check(hasResErr(r, "rl control requires at least one mesh node") &&
              r.controlled_indices.empty(),
          "legacy: empty node list reported, no index selected");

    cfg = makeRlCfg(1);
    cfg.rl.controlled_nodes_set = false;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.controlled_indices == std::vector<uint32_t>({0}),
          "legacy: single node selected by default");

    cfg = makeRlCfg();
    cfg.rl.controlled_nodes_set = false;
    cfg.rl.controlled_node_id   = "node-0";
    r = ResolveRlControl(cfg);
    check(r.controlled_indices == std::vector<uint32_t>({0}), "legacy: first node selectable by id");

    cfg = makeRlCfg();
    cfg.rl.controlled_nodes_set = false;
    cfg.duration_s = 0.1;
    cfg.tick_s     = 0.1;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.num_ticks == 1, "legacy: duration == tick gives one tick");
}

// =====================================================================
// ResolveRlControl -- centralized selection
// =====================================================================

static void
test_resolver_selection_tokens()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = " node-0 , , node-2 ,";
    auto r = ResolveRlControl(cfg);
    check(r.ok() && r.controlled_indices == std::vector<uint32_t>({0, 2}),
          "select: whitespace and empty tokens ignored");

    cfg.rl.controlled_nodes = "  all  ";
    r = ResolveRlControl(cfg);
    check(r.ok() && r.controlled_indices == std::vector<uint32_t>({0, 1, 2}),
          "select: padded 'all' selects every node");

    cfg.rl.controlled_nodes = " , ,, ";
    r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl.controlled_nodes is set but empty"),
          "select: only separators counts as empty");

    cfg.rl.controlled_nodes = "all, all";
    check(!ResolveRlControl(cfg).ok(), "select: repeated 'all' rejected");

    cfg.rl.controlled_nodes = "ghost1, node-1, ghost2";
    r = ResolveRlControl(cfg);
    check(hasResErr(r, "unknown node id 'ghost1'") && hasResErr(r, "unknown node id 'ghost2'"),
          "select: every unknown id reported");

    cfg.rl.controlled_nodes = "node-1, ghost, node-1";
    r = ResolveRlControl(cfg);
    check(hasResErr(r, "unknown node id 'ghost'") && hasResErr(r, "duplicate id 'node-1'"),
          "select: unknown and duplicate reported together");

    cfg.rl.controlled_nodes = "node-2";
    r = ResolveRlControl(cfg);
    check(r.ok() && r.controlled_indices == std::vector<uint32_t>({2}) && r.num_slots == 1,
          "select: single explicit id gives one slot");

    // An id shared by a node and a jammer resolves to the node.
    cfg.jammers.push_back(makeJammer("node-1"));
    cfg.rl.controlled_nodes = "node-1";
    r = ResolveRlControl(cfg);
    check(r.ok() && r.controlled_indices == std::vector<uint32_t>({1}),
          "select: node id wins over a jammer with the same id");
}

static void
test_resolver_slot_counts()
{
    auto cfg = makeRlCfg(64);
    auto r = ResolveRlControl(cfg);
    check(r.ok() && r.num_slots == 64, "slots: 'all' over 64 nodes auto-sizes to 64");

    cfg = makeRlCfg(65);
    r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl.max_controlled_nodes (65) exceeds the maximum of 64"),
          "slots: 'all' over 65 nodes exceeds the 64-slot cap");

    cfg = makeRlCfg();
    cfg.rl.controlled_nodes     = "node-0, node-1";
    cfg.rl.max_controlled_nodes = 2;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.num_slots == 2, "slots: max == controlled count accepted");

    cfg.rl.max_controlled_nodes = 64;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.num_slots == 64, "slots: max == 64 with padding accepted");

    cfg.rl.max_controlled_nodes = -1;
    r = ResolveRlControl(cfg);
    check(!hasResErr(r, "is smaller than") && r.num_slots == 0,
          "slots: negative max reports only the sign error");
}

// =====================================================================
// ResolveRlControl -- cadence
// =====================================================================

static void
test_resolver_cadence()
{
    auto cfg = makeRlCfg();  // duration 10, tick 0.1, num_ticks 100

    cfg.rl.decision_interval_s = 0.1;
    auto r = ResolveRlControl(cfg);
    check(r.ok() && r.decision_interval_ticks == 1, "cadence: interval == tick gives k = 1");

    cfg.rl.decision_interval_s = 10.0;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.decision_interval_ticks == 100 && r.num_ticks == 100,
          "cadence: interval == duration gives k == num_ticks");

    cfg.rl.decision_interval_s = 0.3;  // 0.3/0.1 = 2.9999999999999996
    r = ResolveRlControl(cfg);
    check(r.ok() && r.decision_interval_ticks == 3, "cadence: fp-noisy 0.3/0.1 rounds to k = 3");

    cfg.rl.decision_interval_s = 0.50000005;  // k = 5.0000005, within 1e-6
    r = ResolveRlControl(cfg);
    check(r.ok() && r.decision_interval_ticks == 5, "cadence: ratio within 1e-6 accepted");

    cfg.rl.decision_interval_s = 0.5000002;  // k = 5.000002, outside 1e-6
    check(hasResErr(ResolveRlControl(cfg), "integer multiple of tick_s"),
          "cadence: ratio 2e-6 off an integer rejected");

    cfg.rl.decision_interval_s = 0.05;
    check(hasResErr(ResolveRlControl(cfg), "integer multiple of tick_s"),
          "cadence: half a tick rejected");

    cfg.rl.decision_interval_s = 1e-9;
    check(hasResErr(ResolveRlControl(cfg), "integer multiple of tick_s"),
          "cadence: tiny positive interval (k rounds to 0) rejected");

    cfg.rl.decision_interval_s = 10.1;
    check(hasResErr(ResolveRlControl(cfg), "rl.decision_interval_s exceeds duration_s"),
          "cadence: k = num_ticks + 1 rejected");

    cfg.rl.decision_interval_s = 1e300;
    check(hasResErr(ResolveRlControl(cfg), "rl.decision_interval_s exceeds duration_s"),
          "cadence: huge interval rejected without overflow");

    cfg.rl.decision_interval_s = -0.0;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.decision_interval_ticks == 1, "cadence: -0.0 treated as 0 (one tick)");

    // Partial final window is allowed (src/rl/README.md "Partial windows").
    cfg = makeRlCfg();
    cfg.duration_s             = 1.0;
    cfg.rl.decision_interval_s = 0.3;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.num_ticks == 10 && r.decision_interval_ticks == 3,
          "cadence: k that does not divide num_ticks accepted");

    // Cadence integer check is skipped when timing is already invalid.
    cfg = makeRlCfg();
    cfg.tick_s                 = 0.0;
    cfg.rl.decision_interval_s = 0.15;
    r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl timing is invalid") && !hasResErr(r, "integer multiple") &&
              !hasResErr(r, "exceeds duration_s"),
          "cadence: invalid timing suppresses the derived cadence errors");

    // The 1e-6 tolerance also applies to the centralized tick count.
    cfg = makeRlCfg();
    cfg.duration_s = 0.7;
    r = ResolveRlControl(cfg);
    check(r.ok() && r.num_ticks == 7, "cadence: centralized 0.7/0.1 gives 7 ticks");
}

// =====================================================================
// ResolveRlControl -- start positions
// =====================================================================

static void
test_resolver_start_positions()
{
    // Default bounds: x [-1000, 2000], y [-1000, 1000], z [0, 100].
    auto cfg = makeRlCfg();
    cfg.nodes[1].position = Position{-1000.0, 1000.0, 0.0};
    cfg.nodes[2].position = Position{2000.0, -1000.0, 100.0};
    check(ResolveRlControl(cfg).ok(), "start: positions exactly on the bounds accepted (inclusive)");

    cfg.nodes[2].position.z = 100.001;
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "node 'node-2' starts at") && hasResErr(r, "outside the [rl] bounds"),
          "start: z just above z_max rejected");

    cfg = makeRlCfg();
    cfg.nodes[1].position.y = -1000.5;
    check(hasResErr(ResolveRlControl(cfg), "node 'node-1' starts at"),
          "start: y just below y_min rejected");

    cfg = makeRlCfg();
    cfg.nodes[0].position   = Position{5000.0, 0.0, 10.0};
    cfg.rl.controlled_nodes = "node-1, node-2";
    check(ResolveRlControl(cfg).ok(), "start: uncontrolled node outside bounds ignored");

    cfg = makeRlCfg();
    cfg.nodes[1].mobility  = "waypoint";
    cfg.nodes[1].position  = Position{5000.0, 0.0, 10.0};
    cfg.nodes[1].waypoints = {{0.0, 0.0, 0.0, 10.0}, {1.0, 9000.0, 0.0, 10.0}};
    check(ResolveRlControl(cfg).ok(),
          "start: waypoint node uses first waypoint, not position or later waypoints");

    cfg.nodes[1].position  = Position{0.0, 0.0, 10.0};
    cfg.nodes[1].waypoints = {{0.0, 5000.0, 0.0, 10.0}, {1.0, 0.0, 0.0, 10.0}};
    r = ResolveRlControl(cfg);
    check(hasResErr(r, "node 'node-1' starts at (5000,0,10)"),
          "start: waypoint node with first waypoint outside rejected");

    cfg = makeRlCfg();
    cfg.nodes[1].position.z = kInf;
    check(hasResErr(ResolveRlControl(cfg), "node 'node-1' has a non-finite start position"),
          "start: infinite z rejected");

    // Unordered bounds: one bounds error, no per-node "outside" errors.
    cfg = makeRlCfg();
    cfg.rl.x_min = cfg.rl.x_max = 0.0;
    r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl bounds must be finite and ordered") &&
              !hasResErr(r, "outside the [rl] bounds"),
          "start: equal x bounds rejected once; start checks skipped");

    cfg = makeRlCfg();
    cfg.rl.z_min = kNaN;
    check(hasResErr(ResolveRlControl(cfg), "rl bounds must be finite and ordered"),
          "start: NaN bound rejected in centralized mode");

    cfg = makeRlCfg();
    cfg.rl.step_size_m = -5.0;
    check(hasResErr(ResolveRlControl(cfg), "rl.step_size_m must be finite and > 0"),
          "start: negative step size rejected in centralized mode");

    cfg = makeRlCfg();
    cfg.rl.step_size_m = kInf;
    check(hasResErr(ResolveRlControl(cfg), "rl.step_size_m must be finite and > 0"),
          "start: infinite step size rejected in centralized mode");
}

static void
test_resolver_collects_all()
{
    auto cfg = makeRlCfg();
    cfg.rl.action_type          = "continuous";
    cfg.rl.action_profile       = "move_3d";
    cfg.rl.controlled_nodes     = "node-0, ghost";
    cfg.rl.controlled_node_id   = "node-1";
    cfg.rl.max_controlled_nodes = -1;
    cfg.rl.decision_interval_s  = 0.15;
    cfg.rl.step_size_m          = 0.0;
    cfg.nodes[0].position.x     = 1e6;
    bool threw = false;
    auto r = resolveNoThrow(cfg, threw);
    check(!threw, "collect: resolver does not throw on many faults");
    const std::vector<std::string> expect = {
        "mutually exclusive",
        "rl.action_type 'continuous'",
        "'move_3d' is reserved",
        "unknown node id 'ghost'",
        "rl.max_controlled_nodes must be >= 0",
        "integer multiple of tick_s",
        "rl.step_size_m must be finite and > 0",
        "node 'node-0' starts at",
    };
    for (const auto& e : expect)
    {
        check(hasResErr(r, e), "collect: resolver error present: " + e);
    }
    check(r.control_mode == "centralized", "collect: mode still centralized when errors exist");
}

// =====================================================================
// ApplyRlControl / ControlledStartPosition / MaxSpeedForType
// =====================================================================

static void
test_apply_rl_control_cases()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes_set = false;
    cfg.duration_s              = 0.7;
    auto r = ResolveRlControl(cfg);
    ApplyRlControl(cfg, r);
    check(cfg.rl.control_mode == "legacy" &&
              cfg.rl.controlled_indices == std::vector<uint32_t>({2}) && cfg.rl.num_slots == 1 &&
              cfg.rl.decision_interval_ticks == 1 && cfg.rl.num_ticks == 6,
          "apply: legacy resolution copied (truncated 6 ticks)");

    // A failed apply leaves the previously applied fields untouched.
    RlControlResolution bad = r;
    bad.control_mode        = "centralized";
    bad.controlled_indices  = {0, 1};
    bad.num_slots           = 9;
    bad.num_ticks           = 999;
    bad.errors.push_back("boom");
    bool threw = false;
    try
    {
        ApplyRlControl(cfg, bad);
    }
    catch (const std::invalid_argument&)
    {
        threw = true;
    }
    check(threw, "apply: errors throw std::invalid_argument");
    check(cfg.rl.control_mode == "legacy" && cfg.rl.num_slots == 1 && cfg.rl.num_ticks == 6 &&
              cfg.rl.controlled_indices == std::vector<uint32_t>({2}),
          "apply: throwing leaves cfg.rl unchanged");

    // Disabled resolution applies defaults.
    auto off = makeRlCfg();
    off.rl.enabled = false;
    off.rl.num_ticks = 42;
    ApplyRlControl(off, ResolveRlControl(off));
    check(off.rl.num_ticks == 0 && off.rl.num_slots == 0 && off.rl.control_mode == "legacy",
          "apply: disabled resolution resets resolved fields");
}

static void
test_controlled_start_position_cases()
{
    NodeSpec rw = makeNode("rw", 1.0, 2.0, 3.0);
    rw.mobility  = "random_walk";
    rw.waypoints = {{0.0, 9.0, 9.0, 9.0}, {1.0, 8.0, 8.0, 8.0}};
    Position p = ControlledStartPosition(rw);
    check(p.x == 1.0 && p.y == 2.0 && p.z == 3.0,
          "csp: non-waypoint mobility ignores a waypoints list");

    NodeSpec cv = makeNode("cv", 4.0, 5.0, 6.0);
    cv.mobility = "constant_velocity";
    cv.velocity = Velocity{1.0, 1.0, 0.0};
    p = ControlledStartPosition(cv);
    check(p.x == 4.0 && p.y == 5.0 && p.z == 6.0, "csp: constant_velocity uses position");

    NodeSpec wp = makeNode("wp", 0.0, 0.0, 0.0);
    wp.mobility  = "waypoint";
    wp.waypoints = {{2.5, 7.0, 8.0, 9.0}, {5.0, 1.0, 1.0, 1.0}};
    p = ControlledStartPosition(wp);
    check(p.x == 7.0 && p.y == 8.0 && p.z == 9.0,
          "csp: first waypoint used even when its t > 0");
}

static void
test_max_speed_for_type()
{
    check(MaxSpeedForType("drone") == 20.0, "speed: drone cap 20 m/s");
    check(MaxSpeedForType("vehicle") == 15.0, "speed: vehicle cap 15 m/s");
    check(MaxSpeedForType("pedestrian") == 1.5, "speed: pedestrian cap 1.5 m/s");
    check(MaxSpeedForType("") == 20.0 && MaxSpeedForType("boat") == 20.0,
          "speed: unknown type falls back to the drone cap");
}

// =====================================================================
// ApplyLayout
// =====================================================================

/// node0 fixed at (1,2,10); node1 random_walk at (10,0,1.5) in x[0,100] y[-50,50].
static SimConfig
makeLayoutCfg()
{
    auto cfg = makeValid();
    cfg.nodes[0].position = {1.0, 2.0, 10.0};
    auto& rn              = cfg.nodes[1];
    rn.mobility           = "random_walk";
    rn.position           = {10.0, 0.0, 1.5};
    rn.random_walk.x_min  = 0.0;
    rn.random_walk.x_max  = 100.0;
    rn.random_walk.y_min  = -50.0;
    rn.random_walk.y_max  = 50.0;
    rn.random_walk.speed_mps = 2.0;
    return cfg;
}

static void
test_layout_atomic()
{
    auto cfg  = makeLayoutCfg();
    auto errs = ApplyLayout(cfg, {{50.0, 60.0, 10.0}, {500.0, 0.0, 1.5}});
    check(errs.size() == 1 && hasIn(errs, "node 'node1'"),
          "layout-atomic: only the bad node reported");
    check(cfg.nodes[0].position.x == 1.0 && cfg.nodes[0].position.y == 2.0,
          "layout-atomic: valid earlier node not mutated when a later node fails");

    // Waypoint node valid, later node invalid -> no waypoint shifted.
    cfg = makeValid();
    cfg.nodes[0].mobility  = "waypoint";
    cfg.nodes[0].position  = {0.0, 0.0, 5.0};
    cfg.nodes[0].waypoints = {{0.0, 1.0, 1.0, 5.0}, {2.0, 3.0, 3.0, 5.0}};
    const auto before      = cfg.nodes[0].waypoints;
    errs = ApplyLayout(cfg, {{100.0, 100.0, 5.0}, {0.0, 0.0, 99.0}});
    check(hasIn(errs, "node 'node1': z 99 differs"), "layout-atomic: later z mismatch reported");
    check(cfg.nodes[0].waypoints[0].x == before[0].x && cfg.nodes[0].waypoints[1].y == before[1].y &&
              cfg.nodes[0].position.x == 0.0,
          "layout-atomic: earlier waypoint node untouched");
}

static void
test_layout_error_collection()
{
    auto cfg  = makeLayoutCfg();
    auto errs = ApplyLayout(cfg, {{0.0, 0.0, 11.0}, {200.0, 0.0, 1.5}});
    check(errs.size() == 2 && hasIn(errs, "node 'node0': z 11") &&
              hasIn(errs, "node 'node1': (200, 0) is outside its random_walk bounds"),
          "layout-errors: errors from several nodes collected");

    errs = ApplyLayout(cfg, {{1.0, 2.0, 10.0}, {200.0, 0.0, 0.0}});
    check(errs.size() == 2 && countIn(errs, "node 'node1'") == 2,
          "layout-errors: z and walk-bound errors on one node both reported");

    errs = ApplyLayout(cfg, {{kNaN, 2.0, 999.0}, {10.0, 0.0, 1.5}});
    check(errs.size() == 1 && hasIn(errs, "node 'node0': non-finite position"),
          "layout-errors: non-finite node reports only the non-finite error");

    errs = ApplyLayout(cfg, {});
    check(errs.size() == 1 && hasIn(errs, "layout has 0 positions, expected 2"),
          "layout-errors: empty layout rejected for a 2-node config");

    auto empty = makeValid();
    empty.nodes.clear();
    errs = ApplyLayout(empty, {});
    check(errs.empty(), "layout-errors: empty layout on empty node list is a no-op");

    // Random walk z checked against position.z.
    errs = ApplyLayout(cfg, {{1.0, 2.0, 10.0}, {10.0, 0.0, 0.0}});
    check(hasIn(errs, "node 'node1': z 0 differs from start z 1.5"),
          "layout-errors: random walk z compared to position.z");
}

static void
test_layout_random_walk_control_modes()
{
    // Legacy RL control keeps the node's own mobility, so walk bounds still apply.
    auto cfg = makeLayoutCfg();
    cfg.rl.enabled            = true;
    cfg.rl.control_mode       = "legacy";
    cfg.rl.controlled_indices = {1};
    auto errs = ApplyLayout(cfg, {{1.0, 2.0, 10.0}, {500.0, 0.0, 1.5}});
    check(hasIn(errs, "outside its random_walk bounds"),
          "layout-rw: legacy-controlled random walk node still bounded");

    // Resolved fields without rl.enabled do not count as central control.
    cfg = makeLayoutCfg();
    cfg.rl.enabled            = false;
    cfg.rl.control_mode       = "centralized";
    cfg.rl.controlled_indices = {1};
    errs = ApplyLayout(cfg, {{1.0, 2.0, 10.0}, {500.0, 0.0, 1.5}});
    check(hasIn(errs, "outside its random_walk bounds"),
          "layout-rw: disabled RL keeps walk bounds");

    // Via the real resolver: centrally controlled walk node is unbounded.
    cfg = makeLayoutCfg();
    cfg.rl.enabled              = true;
    cfg.rl.controlled_nodes_set = true;
    cfg.rl.controlled_nodes     = "node1";
    auto res = ResolveRlControl(cfg);
    check(res.ok(), "layout-rw: resolver accepts the controlled walk node");
    ApplyRlControl(cfg, res);
    errs = ApplyLayout(cfg, {{1.0, 2.0, 10.0}, {500.0, -300.0, 1.5}});
    check(errs.empty() && cfg.nodes[1].position.x == 500.0 && cfg.nodes[1].position.y == -300.0,
          "layout-rw: resolved centralized control lifts walk bounds");
    check(cfg.nodes[1].mobility == "random_walk" && cfg.nodes[1].random_walk.x_max == 100.0 &&
              cfg.nodes[1].random_walk.speed_mps == 2.0,
          "layout-rw: mobility kind and walk params unchanged");
}

static void
test_layout_waypoint_parity()
{
    // Same arithmetic as scripts/baselines/effective_inputs.py rewrite_nodes:
    // dx = x - start_x; waypoint.x = waypoint.x + dx; position.x = x.
    auto cfg = makeValid();
    auto& wn = cfg.nodes[1];
    wn.mobility  = "waypoint";
    wn.position  = {42.0, 43.0, 7.0};
    wn.waypoints = {{0.0, 0.1, 0.2, 3.0}, {1.5, 1.7, -2.3, 4.0}, {9.0, 1e6 + 0.3, 4.4, 5.0}};
    cfg.nodes[0].velocity = Velocity{1.0, 2.0, 3.0};
    cfg.nodes[0].mobility = "constant_velocity";
    cfg.nodes[0].position = {0.0, 0.0, 10.0};
    const auto orig = wn.waypoints;
    const double tx = 0.3, ty = -0.7;

    auto errs = ApplyLayout(cfg, {{-5.0, 6.0, 10.0}, {tx, ty, 3.0}});
    check(errs.empty(), "layout-wp: waypoint layout applies");
    volatile double dx = tx - orig[0].x;
    volatile double dy = ty - orig[0].y;
    bool same = wn.waypoints.size() == orig.size();
    for (size_t i = 0; same && i < orig.size(); ++i)
    {
        same = wn.waypoints[i].x == orig[i].x + dx && wn.waypoints[i].y == orig[i].y + dy &&
               wn.waypoints[i].z == orig[i].z && wn.waypoints[i].t == orig[i].t;
    }
    check(same, "layout-wp: every waypoint shifted with rewrite_nodes arithmetic, z/t kept");
    check(wn.position.x == tx && wn.position.y == ty && wn.position.z == 7.0,
          "layout-wp: position x/y set to the exact target, z kept");
    check(cfg.nodes[0].velocity.vx == 1.0 && cfg.nodes[0].velocity.vy == 2.0 &&
              cfg.nodes[0].mobility == "constant_velocity" && cfg.nodes[0].position.x == -5.0,
          "layout-wp: constant_velocity node moves, velocity kept");

    // z tolerance uses the first waypoint's z.
    errs = ApplyLayout(cfg, {{-5.0, 6.0, 10.0}, {tx, ty, 3.0 + 2e-6}});
    check(hasIn(errs, "node 'node1': z"), "layout-wp: z 2e-6 off the first waypoint rejected");
    errs = ApplyLayout(cfg, {{-5.0, 6.0, 10.0}, {tx, ty, 3.0 - 9e-7}});
    check(errs.empty() && wn.waypoints[0].z == 3.0,
          "layout-wp: z within 1e-6 accepted, waypoint z unchanged");

    // Centrally controlled waypoint node: start position follows the target.
    auto c2 = makeRlCfg();
    c2.nodes[1].mobility  = "waypoint";
    c2.nodes[1].waypoints = {{0.0, 10.0, 20.0, 10.0}, {1.0, 15.0, 20.0, 10.0}};
    c2.rl.controlled_nodes = "node-1";
    auto res = ResolveRlControl(c2);
    check(res.ok(), "layout-wp: controlled waypoint node resolves");
    ApplyRlControl(c2, res);
    errs = ApplyLayout(c2, {{0.0, 20.0, 10.0}, {300.0, -40.0, 10.0}, {20.0, 20.0, 10.0}});
    Position s = ControlledStartPosition(c2.nodes[1]);
    check(errs.empty() && s.x == 300.0 && s.y == -40.0 && s.z == 10.0,
          "layout-wp: controlled waypoint start follows the layout");
    check(c2.nodes[1].waypoints[1].x == 305.0 && c2.nodes[1].waypoints[1].y == -40.0,
          "layout-wp: controlled waypoint path translated");
}

static void
test_layout_leaves_other_state()
{
    auto cfg = makeLayoutCfg();
    cfg.band = "sub-6";
    cfg.jammers.push_back(makeJammer("jam-1"));
    cfg.jammers[0].waypoints = {{0.0, 1.0, 1.0, 1.0}, {1.0, 2.0, 2.0, 2.0}};
    cfg.buildings.push_back(makeBuilding("b1"));
    cfg.rl.enabled            = true;
    cfg.rl.x_min              = -5.0;
    cfg.rl.num_ticks          = 77;
    cfg.rl.controlled_indices = {0};
    auto errs = ApplyLayout(cfg, {{3.0, 4.0, 10.0}, {20.0, 30.0, 1.5}});
    check(errs.empty(), "layout-other: layout applies");
    check(cfg.jammers[0].waypoints[0].x == 1.0 && cfg.jammers[0].waypoints[1].y == 2.0,
          "layout-other: jammer waypoints untouched");
    check(cfg.buildings[0].x_max == 10.0, "layout-other: buildings untouched");
    check(cfg.rl.x_min == -5.0 && cfg.rl.num_ticks == 77 &&
              cfg.rl.controlled_indices == std::vector<uint32_t>({0}),
          "layout-other: rl fields untouched");
    check(cfg.nodes[0].id == "node0" && cfg.nodes[1].id == "node1" && cfg.nodes.size() == 2,
          "layout-other: node ids and order unchanged");
}

// ---- main ----

/**
 * @fn main
 * @brief Run every config-rules test and print a pass/fail count.
 * @return 0 when every check passed, 1 otherwise.
 */
int
main()
{
    // ValidateConfig
    test_timing_boundaries();
    test_nodes_mobility_and_type_values();
    test_waypoint_rules();
    test_channel_rules();
    test_array_gain_rules();
    test_amc_model_rule();
    test_traffic_rules();
    test_routing_rules();
    test_rl_validator_rules();
    test_rl_validator_interactions();
    test_jammer_rules();
    test_building_rules();
    test_collect_all_domains();
    test_validator_rejects_nan();
    test_validator_infinite_duration();
    test_loader_nan_repro();

    // ComputeTickCount / ResolveRlControl
    test_tick_count_boundaries();
    test_resolver_disabled_defaults();
    test_resolver_legacy_ignores_centralized_rules();
    test_resolver_legacy_edge_cases();
    test_resolver_selection_tokens();
    test_resolver_slot_counts();
    test_resolver_cadence();
    test_resolver_start_positions();
    test_resolver_collects_all();

    // ApplyRlControl / ControlledStartPosition / speed caps
    test_apply_rl_control_cases();
    test_controlled_start_position_cases();
    test_max_speed_for_type();

    // ApplyLayout
    test_layout_atomic();
    test_layout_error_collection();
    test_layout_random_walk_control_modes();
    test_layout_waypoint_parity();
    test_layout_leaves_other_state();

    std::cout << "\n" << g_pass << " passed, " << g_fail << " failed.\n";
    if (g_fail > 0)
    {
        std::cout << "SOME TESTS FAILED.\n";
        return 1;
    }
    std::cout << "All tests passed.\n";
    return 0;
}
