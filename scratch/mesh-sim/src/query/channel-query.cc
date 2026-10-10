#include "src/query/channel-query.h"

#include "src/eval/probe-diagnostics.h"
#include "src/query/child-process.h"
#include "src/query/layout-evaluation.h"
#include "src/query/query-protocol.h"

#include <chrono>
#include <iostream>

namespace mesh_sim
{
int
RunChannelQuery(const SimConfig& cfg, const CliArgs& args, std::istream& in, std::ostream& out)
{
    using namespace query;
    const uint32_t planningSeed = ResolveQuerySeed(args, cfg);

    ojson init;
    try
    {
        init = BuildInit(cfg, planningSeed);
    }
    catch (const std::exception& e)
    {
        std::cerr << "Error: channel query init failed: " << e.what() << "\n";
        return 1;
    }
    Emit(out, init);
    if (!out)
        return 1;
    InstallTerminationForwarding();

    std::string line;
    while (out)
    {
        const LineStatus status = ReadBoundedLine(in, line, kMaxRequestLineBytes);
        if (status == LineStatus::kEof)
        {
            return 0;
        }
        if (status == LineStatus::kTooLong)
        {
            EmitError(out,
                      nullptr,
                      "request line exceeds " + std::to_string(kMaxRequestLineBytes) + " bytes");
            continue;
        }
        if (IsBlank(line))
        {
            continue;
        }

        Request request;
        std::string err;
        if (!ParseRequest(line, cfg.nodes.size(), request, err))
        {
            EmitError(out, request.id, err);
            continue;
        }
        if (request.shutdown)
            return 0;
        const auto& evalReq = request.evaluate;
        const auto& requestId = request.id;

        const auto t0 = std::chrono::steady_clock::now();
        const ProbeGrid* probes = evalReq.hasProbes ? &evalReq.probes : nullptr;
        for (const auto& diagnostic : ProbeDiagnostics(cfg, probes))
        {
            std::cerr << "channel query warning: " << diagnostic << "\n";
        }
        ojson layouts = ojson::array();
        std::size_t responseBytes = 65536;
        bool responseTooLarge = false;
        for (const auto& layout : evalReq.layouts)
        {
            auto result = EvaluateLayout(cfg, planningSeed, layout, probes, out);
            responseBytes += result.dump().size() + 1;
            if (responseBytes > cfg.query.max_response_bytes)
            {
                responseTooLarge = true;
                break;
            }
            layouts.push_back(std::move(result));
        }
        if (responseTooLarge)
        {
            EmitError(out,
                      requestId,
                      "batch response exceeds max_response_bytes; use smaller batches");
            continue;
        }
        ojson response;
        response["type"] = "result";
        response["request_id"] = requestId;
        response["layouts"] = std::move(layouts);
        response["wall_s"] =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        Emit(out, response);
        if (!out)
        {
            return 1;
        }
    }
    return 1;
}

} // namespace mesh_sim
