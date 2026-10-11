#include "src/config/query-config.h"
#include "src/eval/probe-diagnostics.h"
#include "src/query/channel-query.h"
#include "src/query/child-process.h"
#include "src/query/layout-evaluation.h"
#include "src/query/query-protocol.h"

#include <chrono>
#include <csignal>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <sys/wait.h>
#include <unistd.h>

using namespace mesh_sim;
using namespace mesh_sim::query;
static int passed = 0, failed = 0;

static void
check(bool value, const char* label)
{
    if (value)
        ++passed;
    else
    {
        ++failed;
        std::cerr << "FAIL: " << label << "\n";
    }
}

// The server is exercised with a pure scorer; no simulator is constructed.
namespace mesh_sim
{
uint32_t
ResolveQuerySeed(const CliArgs&, const SimConfig& cfg)
{
    return cfg.seed;
}
} // namespace mesh_sim

namespace mesh_sim::query
{
ojson
EvaluateLayout(const SimConfig&,
               uint32_t,
               const std::vector<Position>&,
               const ProbeGrid*,
               std::ostream&)
{
    return ojson{{"links", ojson::array()},
                 {"coverage", nullptr},
                 {"padding", std::string(30000, 'x')}};
}
} // namespace mesh_sim::query

int
main()
{
    SimConfig cfg;
    NodeSpec node;
    node.id = "node-a";
    node.position.z = 10;
    cfg.nodes = {node, node};
    cfg.nodes[1].id = "node-b";
    cfg.channel.channel_model = "3gpp";
    cfg.channel.scenario = "RMa";
    ProbeGrid probes;
    probes.points.push_back(Position{0, 0, 0});
    probes.height_m = 0;
    check(ProbeDiagnostics(cfg, &probes).size() == 2, "RMa zero-height diagnostic per link");
    probes.height_m = 1.5;
    check(ProbeDiagnostics(cfg, &probes).empty(), "valid RMa heights");
    cfg.channel.scenario = "UMi";
    check(ProbeDiagnostics(cfg, &probes).empty(), "valid UMi heights");
    cfg.nodes[0].position.z = 11;
    check(!ProbeDiagnostics(cfg, &probes).empty(), "UMi transmitter height diagnostic");
    cfg.channel.channel_model = "nyu";
    check(ProbeDiagnostics(cfg, &probes).empty(), "no 3GPP rules for NYU");
    auto init = BuildInit(cfg, 42);
    check(init["limits"]["child_deadline_s"] == cfg.query.child_deadline_s,
          "advertised child policy");
    check(init["limits"]["max_response_bytes"] == cfg.query.max_response_bytes,
          "advertised response bound");
    std::istringstream lines("123456789\nok\n");
    std::string line;
    check(ReadBoundedLine(lines, line, 4) == LineStatus::kTooLong, "bounded line rejects oversize");
    check(ReadBoundedLine(lines, line, 4) == LineStatus::kLine && line == "ok",
          "bounded line recovers");
    EvaluateRequest request;
    std::string error;
    check(!ParseEvaluate(json{{"layouts", json::array({json::array({json::array({0, 0, 0})})})}},
                         2,
                         request,
                         error),
          "roster shape validation");
    auto policy = LoadQueryConfig(
        IniMap{{"channel_query", {{"child_deadline_s", "0.05"}, {"terminate_grace_s", "0.01"}}}});
    check(policy.child_deadline_s == .05 && policy.terminate_grace_s == .01,
          "INI resolves child timeouts");
    check(ValidateQueryConfig(policy).empty(), "valid query settings");
    policy.child_deadline_s = std::numeric_limits<double>::quiet_NaN();
    check(!ValidateQueryConfig(policy).empty(), "nonfinite deadline rejected");
    bool threw = false;
    try
    {
        LoadQueryConfig(IniMap{{"channel_query", {{"child_deadline_s", "1junk"}}}});
    }
    catch (const std::exception&)
    {
        threw = true;
    }
    check(threw, "trailing timeout text rejected");
    threw = false;
    try
    {
        LoadQueryConfig(IniMap{{"channel_query", {{"unknown", "1"}}}});
    }
    catch (const std::exception&)
    {
        threw = true;
    }
    check(threw, "unknown worker setting rejected");
    policy = QueryConfig{};
    policy.child_deadline_s = .2;
    policy.terminate_grace_s = .01;
    std::string body, failure;
    std::ostringstream out;
    check(RunChild([] { return std::string(200000, 'x'); }, policy, out, body, failure) &&
              body.size() == 200000,
          "child pipe drained beyond pipe capacity");
    body.clear();
    failure.clear();
    policy.max_child_response_bytes = 1024;
    check(!RunChild([] { return std::string(200000, 'x'); }, policy, out, body, failure) &&
              failure.find("exceeds") != std::string::npos,
          "oversized child terminated and reaped");
    body.clear();
    failure.clear();
    auto start = std::chrono::steady_clock::now();
    check(!RunChild(
              [] {
                  std::signal(SIGTERM, SIG_IGN);
                  for (;;)
                      pause();
                  return std::string();
              },
              policy,
              out,
              body,
              failure) &&
              failure.find("deadline") != std::string::npos,
          "hung child killed on deadline");
    check(std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() < 2,
          "child timeout bounded");
    int status = 0;
    check(waitpid(-1, &status, WNOHANG) == -1 && errno == ECHILD, "no unreaped child remains");
    cfg.query.max_response_bytes = 100000;
    std::istringstream requests("{\"type\":\"evaluate\",\"request_id\":1,\"layouts\":[[[0,0,10],[1,"
                                "0,10]],[[0,0,10],[1,0,10]]]}\n{\"type\":\"shutdown\"}\n");
    check(RunChannelQuery(cfg, CliArgs{}, requests, out) == 0,
          "server shuts down after oversized batch");
    check(out.str().find("batch response exceeds") != std::string::npos,
          "aggregate response memory bounded");
    std::cout << passed << " passed, " << failed << " failed\n";
    return failed ? 1 : 0;
}
