#pragma once
#include "src/domain/probe-spec.h"
#include "src/domain/sim-config.h"
#include "third_party/json.hpp"

#include <istream>
#include <ostream>

namespace mesh_sim::query
{
using json = nlohmann::json;
using ojson = nlohmann::ordered_json;
inline constexpr const char* kContract = "mesh_channel_query_v1";
inline constexpr std::size_t kMaxRequestLineBytes = 16u * 1024u * 1024u;
inline constexpr std::size_t kMaxLayouts = 1024;
inline constexpr std::size_t kMaxProbes = 10000;
enum class LineStatus
{
    kLine,
    kTooLong,
    kEof
};

struct EvaluateRequest
{
    std::vector<std::vector<Position>> layouts;
    bool hasProbes = false;
    ProbeGrid probes;
};

struct Request
{
    ojson id = nullptr;
    bool shutdown = false;
    EvaluateRequest evaluate;
};

bool ParseRequest(const std::string&, std::size_t, Request&, std::string&);
void Emit(std::ostream&, const ojson&);
void EmitError(std::ostream&, const ojson&, const std::string&);
ojson LayoutError(const std::string&);
LineStatus ReadBoundedLine(std::istream&, std::string&, std::size_t);
bool IsBlank(const std::string&);
bool ParseEvaluate(const json&, std::size_t, EvaluateRequest&, std::string&);
ojson BuildInit(const SimConfig&, uint32_t);
} // namespace mesh_sim::query
