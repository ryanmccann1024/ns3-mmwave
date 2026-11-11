/** @file mission-config-test.cc
 * @brief Configuration tests for missions, control gates, and peer movement safety.
 */

#include "config-test-support.h"

#include <exception>

namespace config_test
{

static void
test_mission_validation()
{
    auto cfg = makeValid();
    auto third = cfg.nodes.front();
    third.id = "node2";
    cfg.nodes.push_back(third);
    cfg.rl.enabled = true;
    cfg.rl.controlled_nodes_set = true;
    cfg.rl.controlled_nodes = "all";
    cfg.rl.coverage_enabled = true;
    cfg.rl.mission.kind = "recovery";
    cfg.nodes[1].failure_at_s = 3.0;
    check(ValidateConfig(cfg).ok(), "pure mission recovery config valid");
    cfg.nodes[1].failure_at_s = 10.0;
    check(!ValidateConfig(cfg).ok(), "pure dropout at duration rejected");
    cfg.nodes[1].failure_at_s = -1.0;
    cfg.rl.mission.kind = "investigation";
    cfg.rl.mission.investigator_id = "node1";
    cfg.rl.controlled_nodes = "node0,node2";
    check(!ValidateConfig(cfg).ok(), "uncontrolled investigator rejected");
    cfg.rl.controlled_nodes = "all";
    check(ValidateConfig(cfg).ok(), "controlled investigator valid");
    cfg.rl.x_max = 100.0;
    check(hasError(ValidateConfig(cfg), "mission goal must be within RL bounds"),
          "investigation rejects a goal outside its bounds");

    cfg.rl.mission.kind = "coverage";
    check(ValidateConfig(cfg).ok(), "coverage ignores an out-of-bounds investigation goal");

    cfg.rl.mission.kind = "recovery";
    cfg.nodes[1].failure_at_s = 3.0;
    check(ValidateConfig(cfg).ok(), "recovery ignores an out-of-bounds investigation goal");
    cfg.nodes[1].failure_at_s = -1.0;
    cfg.rl.mission.kind = "unknown";
    check(!ValidateConfig(cfg).ok(), "unknown mission rejected");
}

static void
test_mission_inputs()
{
    for (const auto& environment : {"RMa", "UMa"})
        for (const auto& mission : {"coverage", "investigation", "recovery"})
            for (const int peers : {3, 6, 9})
            {
                TempScenario scenario(
                    std::string("scenario = ") + environment + "\n[mission]\nkind = " + mission +
                        "\ninvestigator_id = node0\n" +
                        (std::string(mission) == "investigation"
                             ? "team_investigation = true\ngoal_coverage_target = "
                               "0\nteam_delivery_target = 0\n"
                             : "team_investigation = false\ngoal_coverage_target = "
                               "0.8\nteam_delivery_target = 0.8\n"),
                    "controlled_nodes = all\ncoverage_enabled = true\n"
                    "decision_interval_s = 1\ncontrol_start_s = 1\n"
                    "x_min = 0\nx_max = 400\ny_min = 0\ny_max = 400\nz_min = 0\nz_max = 50\n");
                std::string nodes = "[";
                for (int i = 0; i < peers; ++i)
                {
                    if (i)
                        nodes += ",";
                    nodes += "{\"id\":\"node" + std::to_string(i) +
                             "\",\"mobility\":\"fixed\","
                             "\"node_type\":\"drone\",\"position\":{\"x\":" +
                             std::to_string(30 + 20 * i) + ",\"y\":50,\"z\":20}";
                    if (i == 0 && std::string(mission) == "recovery")
                        nodes += ",\"failure_at_s\":3";
                    nodes += "}";
                }
                scenario.Write("nodes.json", nodes + "]");
                auto cfg = scenario.Load();
                check(ValidateConfig(cfg).ok(), "generated mission scenario validates");
                check(cfg.nodes.size() == static_cast<std::size_t>(peers),
                      "mission team size parsed");
                if (std::string(mission) == "recovery")
                {
                    check(cfg.nodes[0].failure_at_s == 3, "permanent relay dropout parsed");
                    cfg.nodes[0].failure_at_s = 3.05;
                    check(!ValidateConfig(cfg).ok(), "unaligned dropout rejected");
                    cfg.nodes[0].failure_at_s = cfg.duration_s;
                    check(!ValidateConfig(cfg).ok(), "dropout at episode end rejected");
                }
                if (std::string(mission) == "investigation")
                {
                    check(cfg.rl.mission.goal_coverage_target == 0 &&
                              cfg.rl.mission.team_delivery_target == 0,
                          "investigation secondary gates may be explicitly disabled");
                    cfg.rl.mission.goal_coverage_target = -0.1;
                    check(!ValidateConfig(cfg).ok(), "negative investigation target rejected");
                    cfg.rl.mission.goal_coverage_target = 0;
                    cfg.rl.mission.team_delivery_target = 1.1;
                    check(!ValidateConfig(cfg).ok(), "investigation delivery above one rejected");
                }
                cfg.rl.control_start_s = -1;
                check(!ValidateConfig(cfg).ok(), "negative control gate rejected");
                cfg.rl.control_start_s = 1.25;
                check(!ValidateConfig(cfg).ok(), "unaligned control gate rejected");
                cfg.rl.control_start_s = cfg.duration_s;
                check(!ValidateConfig(cfg).ok(), "control gate at episode end rejected");
            }
}

void
testMissionConfig()
{
    test_mission_validation();
    test_mission_inputs();
    {
        auto cfg = makeValid();
        cfg.rl.enabled = true;
        cfg.rl.unsafe_separation_m=0;
        check(!ValidateConfig(cfg).errors.empty(), "reject zero unsafe separation");
        cfg.rl.unsafe_separation_m=1;
        cfg.rl.controlled_nodes_set = true;
        cfg.rl.controlled_nodes = "all";
        cfg.rl.coverage_enabled = true;
        cfg.rl.coverage_grid_cells = 0;
        check(!ValidateConfig(cfg).errors.empty(), "reject zero RL coverage cells");
        cfg.rl.coverage_grid_cells=64;
        check(ValidateConfig(cfg).errors.empty(), "accept 1m separation and live coverage");
    }

    {
        auto cfg = makeRlCfg();
        cfg.rl.avoid_node_collisions = true;
        cfg.rl.unsafe_separation_m = 1;
        check(ValidateConfig(cfg).ok(), "joint collision guard accepts separated starts");
        cfg.nodes[1].position = cfg.nodes[0].position;
        check(!ValidateConfig(cfg).ok(), "joint collision guard rejects overlapping starts");
        cfg.nodes[1].position.z += 20;
        check(ValidateConfig(cfg).ok(), "joint collision guard uses 3D separation");
    }

    {
        TempScenario scenario("", "controlled_nodes = all\navoid_node_collisions = true\n");
        check(scenario.Load().rl.avoid_node_collisions, "loader reads joint collision flag");
        TempScenario defaults("", "controlled_nodes = all\n");
        check(!defaults.Load().rl.avoid_node_collisions, "joint collision flag defaults false");
    }

    {
        const std::string fields =
            R"("x_min":10,"x_max":30,"y_min":40,"y_max":60,"z_min":0,"z_max":38)";
        TempScenario flat(
            "[scenario]\nbuildings_file = buildings.json\n",
            "controlled_nodes = all\nbuilding_clearance_m = 2\nmask_building_moves = false\n");
        flat.Write("buildings.json", "[{\"id\":\"wall\"," + fields + "}]");
        auto cfg = flat.Load();
        check(cfg.buildings[0].x_min == 10 && cfg.buildings[0].z_max == 38,
              "flat geometry loaded without default boxes");
        check(cfg.rl.building_clearance_m == 2 && !cfg.rl.mask_building_moves,
              "collision proposal controls loaded");
        flat.Write("buildings.json", "[{\"id\":\"wall\",\"bounds\":{" + fields + "}}]");
        check(flat.Load().buildings[0].y_max == 60, "nested geometry loaded");
        flat.Write("buildings.json", "[{\"id\":\"wall\",\"x_min\":10}]");
        bool threw = false;
        try
        {
            flat.Load();
        }
        catch (const std::exception&)
        {
            threw = true;
        }
        check(threw, "incomplete geometry rejected rather than silently defaulted");
        flat.Write("buildings.json",
                   "[{\"id\":\"wall\",\"x_min\":999,\"bounds\":{" + fields + "}}]");
        threw = false;
        try
        {
            flat.Load();
        }
        catch (const std::exception&)
        {
            threw = true;
        }
        check(threw, "conflicting geometry rejected");
    }
}

}  // namespace config_test
