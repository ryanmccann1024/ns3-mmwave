/** @file mission-bridge-test.cc
 * @brief Bridge tests for mission facts and building movement vetoes.
 */

#include "bridge-test-support.h"

namespace bridge_test
{

static void
test_mission_wire_facts()
{
    isolated("mission wire facts", [] {
        SimConfig cfg = centralCfg(3, {0, 1, 2}, 3);
        cfg.rl.mission.kind = "recovery";
        World world;
        world.AddCvmm(10, 10, 10);
        world.AddCvmm(20, 20, 10);
        world.AddCvmm(30, 30, 10);
        const auto links = makeTable(3);
        Io io;
        RlBridge bridge(cfg);
        bridge.WriteInit();
        const auto init = io.Last();
        check(init["mission"]["kind"] == "recovery" && init["mission"]["version"] == 1,
              "init identifies the mission payload");
        bridge.SetAvailable({true, false, true});
        bridge.AccumulateTick(0.1,
                              links,
                              {flow(0, 2, 10, 8, true), flow(1, 2, 4, 0, false)},
                              world.mobs);
        bridge.Step(1, 0.1, world.mobs, links, true);
        const auto step = io.Last();
        const auto& facts = step.at("facts");
        const auto& mission = facts.at("mission");
        check(facts["node_available"] == json::array({true, false, true}),
              "availability follows the configured node order");
        check(facts["window"]["demand_mbps_sum"] == 14 &&
                  mission["survivor_demand_mbps_sum"] == 10 &&
                  mission["survivor_delivered_mbps_sum"] == 8,
              "original demand retains dropout flows while survivor demand excludes them");
        check(mission["survivor_node_service"] == json({{10, 8}, {0, 0}, {10, 8}}),
              "survivor service rows retain the failed peer's roster slot");
    });
}

static void
test_building_mask_and_veto()
{
    isolated("building mask and veto", [] {
        SimConfig cfg = centralCfg(1, {0}, 1);
        cfg.rl.avoid_buildings = true;
        cfg.rl.building_clearance_m = 0.5;
        BuildingSpec building;
        building.x_min = 51.25;
        building.x_max = 52.0;
        building.y_min = 49.0;
        building.y_max = 51.0;
        building.z_min = 0.0;
        building.z_max = 12.0;
        cfg.buildings.push_back(building);
        for (bool maskBuildingMoves : {true, false})
        {
            cfg.rl.mask_building_moves = maskBuildingMoves;
            World world;
            world.AddCvmm(50, 50, 10);
            Io io("{\"action\":[1]}\n");
            RlBridge bridge(cfg);
            const auto links = makeTable(1);
            bridge.Step(0, 0.0, world.mobs, links, false);
            check(io.Last()["mask"][1] == (maskBuildingMoves ? 0 : 1),
                  "east is masked only when building masking is enabled");
            bridge.ApplyAction(world.mobs);
            check(world.Vel(0).x == 0.0, "building clearance holds the node in both modes");
            bridge.Step(1, 0.1, world.mobs, links, true);
            const auto rejected = io.Last()["facts"]["safety"]["building_rejected_slots"];
            check(rejected == (maskBuildingMoves ? json::array() : json::array({0})),
                  "an unmasked proposal veto is reported as a building rejection");
        }
    });
}

void
testMissionBridge()
{
    test_mission_wire_facts();
    test_building_mask_and_veto();
}

}  // namespace bridge_test
