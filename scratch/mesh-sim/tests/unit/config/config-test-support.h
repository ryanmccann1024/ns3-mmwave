#pragma once

#include "src/config/config-loader.h"
#include "src/config/config-validator.h"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <string>

namespace config_test
{
using namespace mesh_sim;

extern int g_pass;
extern int g_fail;

inline void
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

inline SimConfig
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

inline bool
hasError(const ValidationResult& r, const std::string& substr)
{
    for (const auto& e : r.errors)
    {
        if (e.find(substr) != std::string::npos)
            return true;
    }
    return false;
}

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

    void Write(const std::string& file, const std::string& data) const
    {
        std::ofstream out(m_dir / file);
        out << data;
    }

    SimConfig Load() const { return ConfigLoader::Load((m_dir / "run.ini").string()); }

  private:
    std::filesystem::path m_dir;
};

inline SimConfig
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

void testMissionConfig();

}  // namespace config_test
