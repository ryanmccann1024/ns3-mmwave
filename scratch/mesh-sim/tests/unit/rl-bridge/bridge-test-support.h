#pragma once

#include "src/rl/rl-bridge.h"
#include "src/rl/rl-agent.h"
#include "src/eval/link-table.h"
#include "src/domain/link-result.h"
#include "third_party/json.hpp"

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cmath>
#include <cstdio>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace bridge_test
{
using namespace mesh_sim;
using json = nlohmann::json;

// ---- helpers ----

extern int g_pass;
extern int g_fail;

// Writes through C stdio so redirecting std::cerr does not swallow failures.
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
        std::fprintf(stderr, "FAIL: %s\n", name.c_str());
    }
}

// Run @p fn in a forked child; its pass/fail counts come back over a pipe.
// A child that crashes or exits abnormally counts as one failure.
inline void
isolated(const std::string& name, const std::function<void()>& fn)
{
    std::cout.flush();
    std::fflush(stdout);
    std::fflush(stderr);
    int fds[2];
    if (pipe(fds) != 0)
    {
        check(false, name + ": pipe() failed");
        return;
    }
    pid_t pid = fork();
    if (pid < 0)
    {
        check(false, name + ": fork() failed");
        return;
    }
    if (pid == 0)
    {
        close(fds[0]);
        g_pass = 0;
        g_fail = 0;
        fn();
        int counts[2] = {g_pass, g_fail};
        ssize_t w = write(fds[1], counts, sizeof(counts));
        (void)w;
        close(fds[1]);
        std::fflush(stderr);
        _exit(0);
    }
    close(fds[1]);
    int counts[2] = {0, 0};
    ssize_t got = read(fds[0], counts, sizeof(counts));
    close(fds[0]);
    int status = 0;
    waitpid(pid, &status, 0);
    if (got != static_cast<ssize_t>(sizeof(counts)) || !WIFEXITED(status) ||
        WEXITSTATUS(status) != 0)
    {
        std::string why = WIFSIGNALED(status)
                              ? "killed by signal " + std::to_string(WTERMSIG(status))
                              : "exited abnormally";
        check(false, name + ": child " + why + " (crash in code under test?)");
        // Keep whatever the child reported before crashing out of the count.
        return;
    }
    g_pass += counts[0];
    g_fail += counts[1];
}

// Redirects std::cin/cout/cerr to string streams for the object's lifetime.
struct Io
{
    std::istringstream in;
    std::ostringstream out;
    std::ostringstream err;
    std::streambuf* oldIn;
    std::streambuf* oldOut;
    std::streambuf* oldErr;

    explicit Io(const std::string& input = "")
        : in(input)
    {
        oldIn  = std::cin.rdbuf(in.rdbuf());
        oldOut = std::cout.rdbuf(out.rdbuf());
        oldErr = std::cerr.rdbuf(err.rdbuf());
        std::cin.clear();
    }

    ~Io()
    {
        std::cin.rdbuf(oldIn);
        std::cout.rdbuf(oldOut);
        std::cerr.rdbuf(oldErr);
        std::cin.clear();
    }

    std::vector<std::string> RawLines() const
    {
        std::vector<std::string> lines;
        std::istringstream s(out.str());
        std::string line;
        while (std::getline(s, line))
        {
            lines.push_back(line);
        }
        return lines;
    }

    std::vector<json> Lines() const
    {
        std::vector<json> v;
        for (const auto& l : RawLines())
        {
            v.push_back(json::parse(l, nullptr, false));
        }
        return v;
    }

    json Last() const
    {
        auto v = Lines();
        return v.empty() ? json() : v.back();
    }

    std::string Unread()
    {
        std::string rest;
        std::string line;
        while (std::getline(in, line))
        {
            rest += line + "\n";
        }
        return rest;
    }
};

inline int
countOf(const std::string& hay, const std::string& needle)
{
    int n = 0;
    for (size_t p = hay.find(needle); p != std::string::npos; p = hay.find(needle, p + 1))
    {
        ++n;
    }
    return n;
}

// Nodes and their mobility models (stub objects owned here).
struct World
{
    std::vector<std::unique_ptr<ns3::MobilityModel>> owned;
    std::vector<ns3::Ptr<ns3::MobilityModel>> mobs;

    ns3::ConstantVelocityMobilityModel* AddCvmm(double x, double y, double z)
    {
        auto m = std::make_unique<ns3::ConstantVelocityMobilityModel>();
        m->SetPosition(ns3::Vector(x, y, z));
        auto* raw = m.get();
        mobs.emplace_back(raw);
        owned.push_back(std::move(m));
        return raw;
    }

    ns3::MobilityModel* AddPlain(double x, double y, double z, ns3::Vector v = ns3::Vector())
    {
        auto m = std::make_unique<ns3::MobilityModel>();
        m->SetPosition(ns3::Vector(x, y, z));
        m->SetTestVelocity(v);
        auto* raw = m.get();
        mobs.emplace_back(raw);
        owned.push_back(std::move(m));
        return raw;
    }

    ns3::ConstantVelocityMobilityModel* Cv(uint32_t i)
    {
        return dynamic_cast<ns3::ConstantVelocityMobilityModel*>(owned[i].get());
    }

    ns3::Vector Pos(uint32_t i) const { return owned[i]->GetPosition(); }
    ns3::Vector Vel(uint32_t i) const { return owned[i]->GetVelocity(); }

    // Stand-in for Simulator::Stop(tick)+Run(): constant-velocity models move.
    void Advance(double dt)
    {
        for (auto& m : owned)
        {
            if (auto* cv = dynamic_cast<ns3::ConstantVelocityMobilityModel*>(m.get()))
            {
                cv->AdvanceForTest(dt);
            }
        }
    }
};

inline NodeSpec
makeNode(const std::string& id, double x, double y, double z,
         const std::string& type = "drone")
{
    NodeSpec n;
    n.id = id;
    n.node_type = type;
    n.position = Position{x, y, z};
    return n;
}

// Centralized config: N drone nodes "n0".."n{N-1}" at the origin, bounds [0,100]^2.
inline SimConfig
centralCfg(uint32_t numNodes, std::vector<uint32_t> controlled, uint32_t slots,
           uint32_t k = 1, uint32_t numTicks = 10, double tickS = 0.1,
           double stepM = 1.0)
{
    SimConfig cfg;
    cfg.tick_s = tickS;
    cfg.duration_s = numTicks * tickS;
    for (uint32_t i = 0; i < numNodes; ++i)
    {
        cfg.nodes.push_back(makeNode("n" + std::to_string(i), 50.0, 50.0, 10.0));
    }
    cfg.rl.enabled = true;
    cfg.rl.control_mode = "centralized";
    cfg.rl.controlled_nodes_set = true;
    cfg.rl.controlled_indices = std::move(controlled);
    cfg.rl.num_slots = slots;
    cfg.rl.decision_interval_ticks = k;
    cfg.rl.num_ticks = numTicks;
    cfg.rl.step_size_m = stepM;
    cfg.rl.x_min = 0.0;
    cfg.rl.x_max = 100.0;
    cfg.rl.y_min = 0.0;
    cfg.rl.y_max = 100.0;
    cfg.rl.z_min = 0.0;
    cfg.rl.z_max = 50.0;
    return cfg;
}


struct L
{
    double sinr;
    double cap;
    bool   los;
};

// Link table where every pair has @p def unless overridden by {i,j} (i<j).
inline LinkTable
makeTable(uint32_t n, L def = {10.0, 100.0, true},
          const std::map<std::pair<uint32_t, uint32_t>, L>& over = {})
{
    std::vector<LinkResult> rs;
    for (uint32_t i = 0; i < n; ++i)
    {
        for (uint32_t j = i + 1; j < n; ++j)
        {
            L l = def;
            auto it = over.find({i, j});
            if (it != over.end())
            {
                l = it->second;
            }
            LinkResult r;
            r.tx_id = i;
            r.rx_id = j;
            r.sinr_db = l.sinr;
            r.capacity_mbps = l.cap;
            r.is_los = l.los;
            rs.push_back(r);
        }
    }
    LinkTable t;
    t.Update(n, rs);
    return t;
}

inline FlowResult
flow(uint32_t s, uint32_t d, double demand, double delivered, bool routable)
{
    FlowResult f;
    f.src = s;
    f.dst = d;
    f.demand_mbps = demand;
    f.delivered_mbps = delivered;
    f.routable = routable;
    return f;
}

void testMissionBridge();

}  // namespace bridge_test
