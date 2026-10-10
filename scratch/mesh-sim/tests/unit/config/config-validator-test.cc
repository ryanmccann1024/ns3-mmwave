/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/*
 * Unit tests for config validation and seed parsing.
 * Standalone binary -- no ns-3 dependency.
 *
 * Build:  see mesh-sim-config-test target in CMakeLists.txt
 * Run:    ./mesh-sim-config-test
 */

#include "src/config/config-loader.h"
#include "src/config/config-validator.h"
#include "src/config/rl-control.h"
#include "src/util/string-utils.h"

#include <cassert>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <fstream>
#include <iostream>
#include <limits>
#include <random>
#include <string>
#include <vector>

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

static SimConfig
makeValid()
{
    SimConfig cfg;
    cfg.scenario_name = "test";
    cfg.seed       = 42;
    cfg.run_id     = 1;
    cfg.duration_s = 10.0;
    cfg.warmup_s   = 0.0;
    cfg.tick_s     = 0.1;

    cfg.channel.frequency_ghz = 28.0;
    cfg.channel.bandwidth_mhz = 400.0;
    cfg.channel.channel_model  = "3gpp";
    cfg.channel.scenario       = "UMi";

    cfg.mesh.traffic.model         = "constant";
    cfg.mesh.traffic.demand_mbps   = 10.0;
    cfg.mesh.traffic.flow_topology = "all_pairs";
    cfg.mesh.routing.algorithm     = "shortest_path";

    NodeSpec n1;
    n1.id       = "node0";
    n1.mobility = "fixed";
    n1.node_type = "drone";
    NodeSpec n2;
    n2.id       = "node1";
    n2.mobility = "fixed";
    n2.node_type = "drone";
    cfg.nodes.push_back(n1);
    cfg.nodes.push_back(n2);

    return cfg;
}

static bool
hasError(const ValidationResult& r, const std::string& substr)
{
    for (const auto& e : r.errors)
    {
        if (e.find(substr) != std::string::npos)
            return true;
    }
    return false;
}

// ---- config validation tests ----

static void
test_valid_config()
{
    auto r = ValidateConfig(makeValid());
    check(r.ok(), "valid config should pass");
}

static void
test_zero_duration()
{
    auto cfg = makeValid();
    cfg.duration_s = 0.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "zero duration rejected");
    check(hasError(r, "duration_s"), "error mentions duration_s");
}

static void
test_negative_duration()
{
    auto cfg = makeValid();
    cfg.duration_s = -1.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "negative duration rejected");
}

static void
test_zero_tick()
{
    auto cfg = makeValid();
    cfg.tick_s = 0.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "zero tick rejected");
}

static void
test_tick_exceeds_duration()
{
    auto cfg = makeValid();
    cfg.tick_s = 20.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "tick > duration rejected");
    check(hasError(r, "tick_s"), "error mentions tick_s");
}

static void
test_negative_warmup()
{
    auto cfg = makeValid();
    cfg.warmup_s = -1.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "negative warmup rejected");
}

static void
test_warmup_exceeds_duration()
{
    auto cfg = makeValid();
    cfg.warmup_s = 10.0;  // == duration_s
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "warmup >= duration rejected");
}

static void
test_non_finite_warmup()
{
    for (double value : {std::numeric_limits<double>::infinity(),
                         std::numeric_limits<double>::quiet_NaN()})
    {
        auto cfg = makeValid();
        cfg.warmup_s = value;
        check(hasError(ValidateConfig(cfg), "warmup_s must be finite"),
              "non-finite warmup rejected before simulation");
    }
}

static void
test_too_few_nodes()
{
    auto cfg = makeValid();
    cfg.nodes.clear();
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "zero nodes rejected");
    check(hasError(r, "2 nodes"), "error mentions 2 nodes");

    cfg.nodes.push_back(NodeSpec{"solo", "peer", "fixed", {}, {}, {}});
    r = ValidateConfig(cfg);
    check(!r.ok(), "one node rejected");
}

static void
test_unknown_traffic_model()
{
    auto cfg = makeValid();
    cfg.mesh.traffic.model = "burst";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "unknown traffic model rejected");
    check(hasError(r, "traffic.model"), "error mentions traffic.model");
}

static void
test_unknown_flow_topology()
{
    auto cfg = makeValid();
    cfg.mesh.traffic.flow_topology = "star";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "unknown flow topology rejected");
}

static void
test_unknown_routing_algorithm()
{
    auto cfg = makeValid();
    cfg.mesh.routing.algorithm = "aodv";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "unknown routing algorithm rejected");
}

static void
test_unknown_channel_scenario()
{
    auto cfg = makeValid();
    cfg.channel.scenario = "Rural";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "unknown channel scenario rejected");
}

static void
test_unknown_channel_model()
{
    auto cfg = makeValid();
    cfg.channel.channel_model = "ray_trace";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "unknown channel model rejected");
}

static void
test_unknown_mobility()
{
    auto cfg = makeValid();
    cfg.nodes[0].mobility = "teleport";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "unknown mobility rejected");
    check(hasError(r, "node0"), "error mentions the node ID");
}

static void
test_negative_bandwidth()
{
    auto cfg = makeValid();
    cfg.channel.bandwidth_mhz = -10.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "negative bandwidth rejected");
}

static void
test_negative_frequency()
{
    auto cfg = makeValid();
    cfg.channel.frequency_ghz = 0.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "zero frequency rejected");
}

static void
test_negative_demand()
{
    auto cfg = makeValid();
    cfg.mesh.traffic.demand_mbps = -5.0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "negative demand rejected");
}

static void
test_gateway_missing_id()
{
    auto cfg = makeValid();
    cfg.mesh.traffic.flow_topology = "gateway";
    cfg.mesh.traffic.gateway_node_id = "";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "gateway without ID rejected");
    check(hasError(r, "gateway_node_id"), "error mentions gateway_node_id");
}

static void
test_gateway_nonexistent_node()
{
    auto cfg = makeValid();
    cfg.mesh.traffic.flow_topology = "gateway";
    cfg.mesh.traffic.gateway_node_id = "nonexistent";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "gateway with bad node ID rejected");
    check(hasError(r, "nonexistent"), "error mentions the bad ID");
}

static void
test_gateway_valid()
{
    auto cfg = makeValid();
    cfg.mesh.traffic.flow_topology = "gateway";
    cfg.mesh.traffic.gateway_node_id = "node0";
    auto r = ValidateConfig(cfg);
    check(r.ok(), "gateway with valid node ID accepted");
}

static void
test_random_pairs_zero_count()
{
    auto cfg = makeValid();
    cfg.mesh.traffic.flow_topology = "random_pairs";
    cfg.mesh.traffic.random_pair_count = 0;
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "random_pairs with zero count rejected");
}

static void
test_building_inverted_bounds()
{
    auto cfg = makeValid();
    BuildingSpec b;
    b.id    = "bad-building";
    b.x_min = 10.0;
    b.x_max = 5.0;  // inverted
    b.y_min = 0.0;
    b.y_max = 10.0;
    b.z_min = 0.0;
    b.z_max = 10.0;
    cfg.buildings.push_back(b);
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "inverted building bounds rejected");
    check(hasError(r, "x_min"), "error mentions x_min");
}

static void
test_multiple_errors()
{
    auto cfg = makeValid();
    cfg.duration_s = 0.0;
    cfg.channel.frequency_ghz = -1.0;
    cfg.mesh.traffic.model = "invalid";
    auto r = ValidateConfig(cfg);
    check(r.errors.size() >= 3, "multiple errors reported at once");
}

// ---- loader-backed scenario helper ----

namespace
{

// Writes a throwaway scenario dir and loads it; extraChannel/extraRl are raw INI lines.
class TempScenario
{
  public:
    TempScenario(const std::string& extraChannel, const std::string& extraRl)
    {
        static int          counter = 0;
        static std::random_device rd;
        static const auto   salt = rd();
        m_dir = std::filesystem::temp_directory_path() /
                ("mesh-sim-cfg-test-" + std::to_string(salt) + "-" +
                 std::to_string(++counter));
        std::filesystem::remove_all(m_dir);
        std::filesystem::create_directories(m_dir / "out");

        std::ofstream ini(m_dir / "run.ini");
        ini << "[scenario]\nname = temp\nnodes_file = nodes.json\n"
            << "duration_s = 10.0\ntick_s = 0.1\n"
            << "[output]\ndir = out\n"
            << "[channel]\n" << extraChannel
            << "[rl]\nenabled = true\n" << extraRl;
        ini.close();

        std::ofstream nodes(m_dir / "nodes.json");
        nodes << R"([{"id":"node0","mobility":"fixed"},)"
              << R"({"id":"node1","mobility":"fixed"}])";
        nodes.close();
    }

    ~TempScenario()
    {
        std::error_code ec;
        std::filesystem::remove_all(m_dir, ec);
    }

    SimConfig Load() const { return ConfigLoader::Load((m_dir / "run.ini").string()); }

  private:
    std::filesystem::path m_dir;
};

}  // namespace

// ---- band tests ----

static void
test_band_default()
{
    TempScenario s("", "");
    auto cfg = s.Load();
    check(cfg.band == "mmwave", "missing band resolves to mmwave");
    check(cfg.band_source == "default", "missing band records source default");
}

static void
test_band_from_ini()
{
    TempScenario s("band = sub-6\n", "");
    auto cfg = s.Load();
    check(cfg.band == "sub-6", "[channel] band = sub-6 loaded");
    check(cfg.band_source == "run.ini", "ini band records source run.ini");
}

static void
test_band_invalid_rejected()
{
    auto cfg = makeValid();
    cfg.band = "lte";
    auto r = ValidateConfig(cfg);
    check(!r.ok(), "invalid band rejected");
    check(hasError(r, "channel.band"), "error mentions channel.band");
    check(hasError(r, "'mmwave'") && hasError(r, "'sub-6'"),
          "band error lists both valid values");
}

// ---- reward tests ----

static void
test_reward_alias_normalized()
{
    TempScenario s("", "reward_type = mean_sinr\n");
    auto cfg = s.Load();
    check(cfg.rl.reward_type == "all_links_los", "mean_sinr normalized to all_links_los");
    check(cfg.rl.reward_type_alias == "mean_sinr", "alias recorded as mean_sinr");
}

static void
test_reward_canonical_unchanged()
{
    TempScenario s("", "reward_type = all_links_los\n");
    auto cfg = s.Load();
    check(cfg.rl.reward_type == "all_links_los", "all_links_los preserved");
    check(cfg.rl.reward_type_alias.empty(), "no alias for canonical reward");
}

static void
test_reward_unknown_rejected()
{
    auto cfg = makeValid();
    cfg.rl.enabled     = true;
    cfg.rl.reward_type = "bogus";
    auto r = ValidateConfig(cfg);
    check(hasError(r, "rl.reward_type"), "unknown reward_type rejected");
}

static void
test_reward_legacy_name_not_valid()
{
    auto cfg = makeValid();
    cfg.rl.enabled     = true;
    cfg.rl.reward_type = "mean_sinr";
    auto r = ValidateConfig(cfg);
    check(hasError(r, "rl.reward_type"), "un-normalized mean_sinr rejected by validator");
}

// ---- rl z-bounds tests ----
// Assert on the relevant bounds error independently of selector validation.

static void
test_rl_inverted_z_bounds()
{
    auto cfg = makeValid();
    cfg.rl.enabled = true;
    cfg.rl.z_min   = 10.0;
    cfg.rl.z_max   =  5.0;
    auto r = ValidateConfig(cfg);
    check(hasError(r, "rl.z_min"), "inverted rl z bounds rejected");
}

static void
test_rl_valid_z_bounds()
{
    auto cfg = makeValid();
    cfg.rl.enabled = true;
    cfg.rl.z_min   =  0.0;
    cfg.rl.z_max   = 50.0;
    auto r = ValidateConfig(cfg);
    check(!hasError(r, "rl.z_min"), "valid rl z bounds accepted");
}

// ---- baseline selector tests ----

static void
test_baseline_default_is_none()
{
    auto cfg = makeValid();
    check(cfg.baseline.algorithm == "none", "baseline.algorithm defaults to none");
    auto r = ValidateConfig(cfg);
    check(r.ok(), "default baseline.algorithm passes validation");
}

static void
test_baseline_known_values_accepted()
{
    for (const std::string algo : {"none", "geometric", "optimization"})
    {
        for (bool rlEnabled : {false, true})
        {
            auto cfg = makeValid();
            cfg.rl.enabled         = rlEnabled;
            cfg.baseline.algorithm = algo;
            auto r = ValidateConfig(cfg);
            check(!hasError(r, "baseline.algorithm"),
                  "baseline.algorithm '" + algo + "' accepted with rl.enabled=" +
                      (rlEnabled ? "true" : "false"));
            if (!rlEnabled)
            {
                check(r.ok(), "baseline.algorithm '" + algo + "' passes with RL disabled");
            }
        }
    }
}

static void
test_baseline_unknown_rejected()
{
    for (bool rlEnabled : {false, true})
    {
        auto cfg = makeValid();
        cfg.rl.enabled         = rlEnabled;
        cfg.baseline.algorithm = "annealing";
        auto r = ValidateConfig(cfg);
        check(!r.ok(), "unknown baseline.algorithm rejected");
        check(hasError(r, "baseline.algorithm: unknown value 'annealing'"),
              "unknown baseline.algorithm error names the field and value");
    }
}

// ---- seed parsing tests ----

static void
test_seed_single()
{
    auto seeds = parseSeedList("42");
    check(seeds.size() == 1 && seeds[0] == 42, "single seed");
}

static void
test_seed_multiple()
{
    auto seeds = parseSeedList("1,2,3");
    check(seeds.size() == 3, "multiple seeds count");
    check(seeds[0] == 1 && seeds[1] == 2 && seeds[2] == 3, "multiple seeds values");
}

static void
test_seed_empty()
{
    auto seeds = parseSeedList("");
    check(seeds.empty(), "empty string returns empty vector");
}

static void
test_seed_skip_empty_tokens()
{
    auto seeds = parseSeedList("1,,3");
    check(seeds.size() == 2, "empty tokens skipped count");
    check(seeds[0] == 1 && seeds[1] == 3, "empty tokens skipped values");
}

// ---- rl centralized control resolution tests ----

static SimConfig
makeRlCfg(size_t n = 3)
{
    SimConfig cfg = makeValid();
    cfg.nodes.clear();
    for (size_t i = 0; i < n; ++i)
    {
        NodeSpec s;
        s.id        = std::string("node-") + static_cast<char>('a' + static_cast<int>(i));
        s.mobility  = "fixed";
        s.node_type = "drone";
        s.position  = Position{10.0 * static_cast<double>(i), 20.0, 10.0};
        cfg.nodes.push_back(s);
    }
    cfg.rl.enabled             = true;
    cfg.rl.controlled_nodes_set = true;
    cfg.rl.controlled_nodes    = "all";
    return cfg;
}

static bool
hasResErr(const RlControlResolution& r, const std::string& substr)
{
    for (const auto& e : r.errors)
    {
        if (e.find(substr) != std::string::npos)
            return true;
    }
    return false;
}

static void
test_rl_disabled_has_no_control()
{
    auto cfg = makeRlCfg();
    cfg.rl.enabled = false;
    auto r = ResolveRlControl(cfg);
    check(r.ok(), "disabled rl resolves without errors");
    check(r.control_mode == "disabled", "disabled rl resolves to disabled mode");
    check(r.controlled_indices.empty(), "disabled rl resolves no slots");
}

static void
test_rl_selection_order()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "node-c, node-a";
    auto r = ResolveRlControl(cfg);
    check(r.ok(), "explicit id list resolves cleanly");
    check(r.control_mode == "centralized", "controlled_nodes selects centralized mode");
    check(r.controlled_indices == std::vector<uint32_t>({2, 0}),
          "slot order follows token order");
    check(r.num_slots == 2, "auto-sized slot count equals controlled count");
    check(r.decision_interval_ticks == 1, "default decision cadence is one tick");
    check(r.num_ticks == 100, "centralized num_ticks uses the robust count");
}

static void
test_rl_selection_all()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "all";
    auto r = ResolveRlControl(cfg);
    check(r.ok(), "'all' resolves cleanly");
    check(r.controlled_indices == std::vector<uint32_t>({0, 1, 2}),
          "'all' selects every node in file order");
}

static void
test_rl_all_with_ids_rejected()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "all, node-a";
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "'all' cannot be combined with explicit ids"),
          "'all' combined with ids rejected");
}

static void
test_rl_jammer_id_rejected()
{
    auto cfg = makeRlCfg();
    JammerSpec j;
    j.id = "jam-1";
    cfg.jammers.push_back(j);
    cfg.rl.controlled_nodes = "node-a, jam-1";
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "'jam-1' is a jammer id; jammers cannot be RL-controlled"),
          "jammer id rejected with the jammer message");
    check(!hasResErr(r, "unknown node id 'jam-1'"),
          "jammer id not reported as an unknown node");
}

static void
test_rl_unknown_id_rejected()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "node-a, ghost";
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl.controlled_nodes: unknown node id 'ghost'"),
          "unknown id rejected");
}

static void
test_rl_duplicate_token_rejected()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "node-a, node-a";
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl.controlled_nodes: duplicate id 'node-a'"),
          "repeated token rejected");
}

static void
test_rl_removed_keys_rejected()
{
    for (const auto& key : {"controlled_node_id", "action_type", "arrival_threshold_m"})
    {
        TempScenario s("", std::string(key) + " = continuous\n");
        auto cfg = s.Load();
        cfg.rl.enabled = true;
        check(hasResErr(ResolveRlControl(cfg), std::string("rl.") + key + " is no longer supported"),
              "removed RL key reported after enabling RL");
        cfg.rl.enabled = false;
        check(ResolveRlControl(cfg).ok(), "inactive old RL block does not affect simulation");
    }
}

static void
test_rl_gateway_selection_rejected()
{
    auto cfg = makeRlCfg();
    cfg.mesh.traffic.flow_topology = "gateway";
    cfg.mesh.traffic.gateway_node_id = "node-a";
    for (const auto& selector : {"all", "node-c, node-a"})
    {
        cfg.rl.controlled_nodes = selector;
        check(hasResErr(ResolveRlControl(cfg), "active traffic gateway 'node-a'"),
              "active gateway rejected for all and explicit selection");
    }
    cfg.rl.controlled_nodes = "node-b, node-c";
    check(ResolveRlControl(cfg).ok(), "non-gateway nodes remain controllable");
    cfg.mesh.traffic.flow_topology = "all_pairs";
    cfg.rl.controlled_nodes = "all";
    check(ResolveRlControl(cfg).ok(), "inactive gateway label does not block selection");
}

static void
test_rl_empty_selector_rejected()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "";
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl.controlled_nodes is set but empty"),
          "present-but-empty controlled_nodes rejected");
}

static void
test_rl_action_profile()
{
    auto cfg = makeRlCfg();
    cfg.rl.action_profile = "move_3d";
    auto r3 = ResolveRlControl(cfg);
    check(hasResErr(r3, "rl.action_profile 'move_3d' is not supported; use 'move_2d'"),
          "move_3d rejected");

    cfg.rl.action_profile = "teleport";
    auto ru = ResolveRlControl(cfg);
    check(hasResErr(ru, "rl.action_profile: unknown value 'teleport'"),
          "unknown action_profile rejected");
}

static void
test_rl_max_controlled_nodes()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "node-a, node-b";

    cfg.rl.max_controlled_nodes = 65;
    check(hasResErr(ResolveRlControl(cfg), "rl.max_controlled_nodes (65)"),
          "max_controlled_nodes above 64 rejected");

    cfg.rl.max_controlled_nodes = 1;
    check(hasResErr(ResolveRlControl(cfg),
                    "is smaller than the number of controlled nodes (2)"),
          "max_controlled_nodes below the controlled count rejected");

    cfg.rl.max_controlled_nodes = -1;
    check(hasResErr(ResolveRlControl(cfg),
                    "rl.max_controlled_nodes must be >= 0 (0 means auto-size)"),
          "negative max_controlled_nodes rejected");

    cfg.rl.max_controlled_nodes = 4;
    auto r = ResolveRlControl(cfg);
    check(r.ok() && r.num_slots == 4, "padded slot count accepted");
}

static void
test_rl_decision_interval()
{
    auto cfg = makeRlCfg();

    auto rd = ResolveRlControl(cfg);
    check(rd.ok() && rd.decision_interval_ticks == 1,
          "decision_interval_s = 0 defaults to one tick");

    cfg.rl.decision_interval_s = 0.5;
    auto r5 = ResolveRlControl(cfg);
    check(r5.ok() && r5.decision_interval_ticks == 5,
          "decision_interval_s = 0.5 with tick 0.1 gives k = 5");

    cfg.rl.decision_interval_s = 0.15;
    check(hasResErr(ResolveRlControl(cfg),
                    "rl.decision_interval_s must be an integer multiple of tick_s"),
          "non-integer decision interval rejected");

    cfg.rl.decision_interval_s = 20.0;
    check(hasResErr(ResolveRlControl(cfg), "rl.decision_interval_s exceeds duration_s"),
          "decision interval longer than the run rejected");

    for (double bad : {-0.1, std::numeric_limits<double>::quiet_NaN(),
                       std::numeric_limits<double>::infinity()})
    {
        cfg.rl.decision_interval_s = bad;
        check(hasResErr(ResolveRlControl(cfg),
                        "rl.decision_interval_s must be finite and >= 0"),
              "invalid decision_interval_s rejected");
    }
}

static void
test_rl_tick_counts()
{
    check(ComputeTickCount(0.3, 0.1, true) == 3, "robust tick count of 0.3/0.1 is 3");
    check(ComputeTickCount(0.3, 0.1, false) == 2, "non-RL tick count of 0.3/0.1 is 2");
    check(ComputeTickCount(1.0, 0.1, true) == 10, "robust tick count of 1.0/0.1 is 10");
    check(ComputeTickCount(0.6, 0.1, false) == 5, "non-RL tick count of 0.6/0.1 is 5");

    auto cfg = makeRlCfg();
    cfg.duration_s = 0.3;
    auto rc = ResolveRlControl(cfg);
    check(rc.num_ticks == 3, "centralized resolution uses the robust tick count");

}

static void
test_rl_missing_selection_rejected()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes_set = false;
    cfg.rl.controlled_nodes = "";
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl.controlled_nodes is required"), "missing selector rejected");
    check(r.controlled_indices.empty(), "no implicit last-node selection");
}

static void
test_rl_duplicate_node_ids()
{
    auto cfg = makeRlCfg();
    cfg.nodes[2].id = "node-a";
    cfg.rl.controlled_nodes = "node-a";
    check(hasResErr(ResolveRlControl(cfg),
                    "nodes.json has duplicate node id 'node-a'; ids must be unique"),
          "duplicate nodes.json ids rejected in centralized mode");

    cfg.rl.enabled = false;
    check(!hasResErr(ResolveRlControl(cfg), "duplicate node id"),
          "RL selection checks skipped when disabled");
}

static void
test_rl_start_outside_bounds()
{
    auto cfg = makeRlCfg();
    cfg.nodes[1].position = Position{5000.0, 20.0, 10.0};
    cfg.rl.controlled_nodes = "node-b";
    auto r = ResolveRlControl(cfg);
    check(hasResErr(r, "rl.controlled_nodes: node 'node-b' starts at (5000,20,10), "
                       "outside the [rl] bounds"),
          "controlled start outside the bounds rejected");
}

static void
test_rl_validator_reports_resolver_errors()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes = "ghost";
    auto r = ValidateConfig(cfg);
    check(hasError(r, "rl.controlled_nodes: unknown node id 'ghost'"),
          "ValidateConfig appends resolver errors when rl is enabled");

    cfg.rl.enabled = false;
    check(!hasError(ValidateConfig(cfg), "rl.controlled_nodes"),
          "ValidateConfig skips resolver errors when rl is disabled");
}

// ---- rl resolver safety tests ----

static void
test_rl_safety_cases()
{
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();

    struct Case
    {
        const char* name;
        std::function<void(SimConfig&)> mutate;
        const char* expect;
    };

    const std::vector<Case> cases = {
        {"non-finite duration", [nan](SimConfig& c) { c.duration_s = nan; },
         "rl timing is invalid or exceeds the supported tick range"},
        {"infinite duration", [inf](SimConfig& c) { c.duration_s = inf; },
         "rl timing is invalid or exceeds the supported tick range"},
        {"non-finite tick", [nan](SimConfig& c) { c.tick_s = nan; },
         "rl timing is invalid or exceeds the supported tick range"},
        {"zero tick", [](SimConfig& c) { c.tick_s = 0.0; },
         "rl timing is invalid or exceeds the supported tick range"},
        {"tick overflow", [](SimConfig& c) { c.duration_s = 1e12; c.tick_s = 1e-9; },
         "rl timing is invalid or exceeds the supported tick range"},
        {"empty nodes", [](SimConfig& c) { c.nodes.clear(); },
         "rl control requires at least one mesh node"},
        {"non-finite step size", [nan](SimConfig& c) { c.rl.step_size_m = nan; },
         "rl.step_size_m must be finite and > 0"},
        {"zero step size", [](SimConfig& c) { c.rl.step_size_m = 0.0; },
         "rl.step_size_m must be finite and > 0"},
        {"non-finite bound", [inf](SimConfig& c) { c.rl.x_max = inf; },
         "rl bounds must be finite and ordered"},
        {"unordered bounds", [](SimConfig& c) { c.rl.y_min = 10.0; c.rl.y_max = -10.0; },
         "rl bounds must be finite and ordered"},
        {"empty waypoints",
         [](SimConfig& c) {
             c.nodes[1].mobility = "waypoint";
             c.nodes[1].waypoints.clear();
             c.rl.controlled_nodes = "node-b";
         },
         "rl.controlled_nodes: waypoint node 'node-b' has no waypoints"},
        {"non-finite start position",
         [nan](SimConfig& c) {
             c.nodes[1].position = Position{nan, 0.0, 0.0};
             c.rl.controlled_nodes = "node-b";
         },
         "rl.controlled_nodes: node 'node-b' has a non-finite start position"},
    };

    for (const auto& c : cases)
    {
        auto cfg = makeRlCfg();
        c.mutate(cfg);
        RlControlResolution r;
        bool threw = false;
        try
        {
            r = ResolveRlControl(cfg);
        }
        catch (...)
        {
            threw = true;
        }
        check(!threw, std::string("safety case does not throw: ") + c.name);
        check(!threw && hasResErr(r, c.expect),
              std::string("safety case reports an error: ") + c.name);
    }
}

static void
test_controlled_start_position()
{
    NodeSpec fixed;
    fixed.id       = "node-f";
    fixed.mobility = "fixed";
    fixed.position = Position{1.0, 2.0, 3.0};
    const Position pf = ControlledStartPosition(fixed);
    check(pf.x == 1.0 && pf.y == 2.0 && pf.z == 3.0,
          "non-waypoint start position is the configured position");

    NodeSpec wp;
    wp.id       = "node-w";
    wp.mobility = "waypoint";
    wp.waypoints.push_back(Waypoint{0.0, 100.0, 0.0, 10.0});
    wp.waypoints.push_back(Waypoint{1.0, 100.0, 40.0, 10.0});
    const Position pw = ControlledStartPosition(wp);
    check(pw.x == 100.0 && pw.y == 0.0 && pw.z == 10.0,
          "waypoint start position is the first waypoint");

    NodeSpec empty;
    empty.id       = "node-e";
    empty.mobility = "waypoint";
    bool threw = false;
    try
    {
        ControlledStartPosition(empty);
    }
    catch (const std::invalid_argument&)
    {
        threw = true;
    }
    check(threw, "empty waypoint list throws std::invalid_argument");
}

static void
test_apply_rl_control()
{
    auto cfg = makeRlCfg();
    cfg.rl.controlled_nodes     = "node-b, node-c";
    cfg.rl.max_controlled_nodes = 3;
    cfg.rl.decision_interval_s  = 0.5;

    auto r = ResolveRlControl(cfg);
    check(r.ok(), "resolution used by ApplyRlControl is valid");
    ApplyRlControl(cfg, r);
    check(cfg.rl.control_mode == "centralized", "ApplyRlControl copies control_mode");
    check(cfg.rl.controlled_indices == std::vector<uint32_t>({1, 2}),
          "ApplyRlControl copies controlled_indices");
    check(cfg.rl.num_slots == 3, "ApplyRlControl copies num_slots");
    check(cfg.rl.decision_interval_ticks == 5,
          "ApplyRlControl copies decision_interval_ticks");
    check(cfg.rl.num_ticks == 100, "ApplyRlControl copies num_ticks");

    RlControlResolution bad;
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
    check(threw, "ApplyRlControl throws on a resolution with errors");
}

// ---- main ----

int
main()
{
    // Config validation
    test_valid_config();
    test_zero_duration();
    test_negative_duration();
    test_zero_tick();
    test_tick_exceeds_duration();
    test_negative_warmup();
    test_warmup_exceeds_duration();
    test_non_finite_warmup();
    test_too_few_nodes();
    test_unknown_traffic_model();
    test_unknown_flow_topology();
    test_unknown_routing_algorithm();
    test_unknown_channel_scenario();
    test_unknown_channel_model();
    test_unknown_mobility();
    test_negative_bandwidth();
    test_negative_frequency();
    test_negative_demand();
    test_gateway_missing_id();
    test_gateway_nonexistent_node();
    test_gateway_valid();
    test_random_pairs_zero_count();
    test_building_inverted_bounds();
    test_multiple_errors();

    // Band resolution and validation
    test_band_default();
    test_band_from_ini();
    test_band_invalid_rejected();

    // Reward naming
    test_reward_alias_normalized();
    test_reward_canonical_unchanged();
    test_reward_unknown_rejected();
    test_reward_legacy_name_not_valid();

    // RL z bounds
    test_rl_inverted_z_bounds();
    test_rl_valid_z_bounds();

    // Baseline selector
    test_baseline_default_is_none();
    test_baseline_known_values_accepted();
    test_baseline_unknown_rejected();

    // RL centralized control resolution
    test_rl_disabled_has_no_control();
    test_rl_selection_order();
    test_rl_selection_all();
    test_rl_all_with_ids_rejected();
    test_rl_jammer_id_rejected();
    test_rl_unknown_id_rejected();
    test_rl_duplicate_token_rejected();
    test_rl_removed_keys_rejected();
    test_rl_gateway_selection_rejected();
    test_rl_empty_selector_rejected();
    test_rl_action_profile();
    test_rl_max_controlled_nodes();
    test_rl_decision_interval();
    test_rl_tick_counts();
    test_rl_missing_selection_rejected();
    test_rl_duplicate_node_ids();
    test_rl_start_outside_bounds();
    test_rl_validator_reports_resolver_errors();

    // RL resolver safety
    test_rl_safety_cases();
    test_controlled_start_position();
    test_apply_rl_control();

    // Seed parsing
    test_seed_single();
    test_seed_multiple();
    test_seed_empty();
    test_seed_skip_empty_tokens();

    std::cout << "\n" << g_pass << " passed, " << g_fail << " failed.\n";
    if (g_fail > 0)
    {
        std::cout << "SOME TESTS FAILED.\n";
        return 1;
    }
    std::cout << "All tests passed.\n";
    return 0;
}
