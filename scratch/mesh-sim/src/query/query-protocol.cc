#include "src/query/query-protocol.h"

#include "src/config/rl-control.h"
#include "src/eval/sinr-capacity.h"

#include <cmath>

namespace mesh_sim::query
{
void
Emit(std::ostream& out, const ojson& msg)
{
    out << msg.dump(-1, ' ', false, ojson::error_handler_t::replace) << '\n';
    out.flush();
}

void
EmitError(std::ostream& out, const ojson& requestId, const std::string& message)
{
    ojson msg;
    msg["type"] = "error";
    msg["request_id"] = requestId;
    msg["message"] = message;
    Emit(out, msg);
}

ojson
LayoutError(const std::string& message)
{
    ojson e;
    e["error"] = message;
    return e;
}

// Never buffers more than maxBytes; the rest of an oversized line is consumed and dropped.
LineStatus
ReadBoundedLine(std::istream& in, std::string& line, std::size_t maxBytes)
{
    line.clear();
    std::streambuf* sb = in.rdbuf();
    bool any = false;
    bool tooLong = false;
    for (;;)
    {
        const int c = sb->sbumpc();
        if (c == std::char_traits<char>::eof())
        {
            in.setstate(std::ios::eofbit);
            if (!any)
            {
                return LineStatus::kEof;
            }
            return tooLong ? LineStatus::kTooLong : LineStatus::kLine;
        }
        any = true;
        if (c == '\n')
        {
            return tooLong ? LineStatus::kTooLong : LineStatus::kLine;
        }
        if (tooLong)
        {
            continue;
        }
        if (line.size() >= maxBytes)
        {
            tooLong = true;
            std::string().swap(line);
            continue;
        }
        line.push_back(static_cast<char>(c));
    }
}

bool
IsBlank(const std::string& s)
{
    return s.find_first_not_of(" \t\r") == std::string::npos;
}

bool
FiniteNumber(const json& v, double& out)
{
    if (!v.is_number())
    {
        return false;
    }
    out = v.get<double>();
    return std::isfinite(out);
}

bool
ParseEvaluate(const json& req, std::size_t numNodes, EvaluateRequest& out, std::string& err)
{
    if (!req.contains("layouts") || !req["layouts"].is_array() || req["layouts"].empty())
    {
        err = "'layouts' must be a non-empty array";
        return false;
    }
    const json& layouts = req["layouts"];
    if (layouts.size() > kMaxLayouts)
    {
        err = "'layouts' has " + std::to_string(layouts.size()) + " entries; limit is " +
              std::to_string(kMaxLayouts);
        return false;
    }
    out.layouts.reserve(layouts.size());
    for (std::size_t l = 0; l < layouts.size(); ++l)
    {
        const json& layout = layouts[l];
        const std::string where = "layouts[" + std::to_string(l) + "]";
        if (!layout.is_array() || layout.size() != numNodes)
        {
            err = where + " must be an array of " + std::to_string(numNodes) + " [x, y, z] points";
            return false;
        }
        std::vector<Position> positions(numNodes);
        for (std::size_t i = 0; i < numNodes; ++i)
        {
            const json& p = layout[i];
            if (!p.is_array() || p.size() != 3 || !FiniteNumber(p[0], positions[i].x) ||
                !FiniteNumber(p[1], positions[i].y) || !FiniteNumber(p[2], positions[i].z))
            {
                err = where + "[" + std::to_string(i) + "] must be [x, y, z] finite numbers";
                return false;
            }
        }
        out.layouts.push_back(std::move(positions));
    }

    if (!req.contains("probes") || req["probes"].is_null())
    {
        return true;
    }
    const json& probes = req["probes"];
    if (!probes.is_object())
    {
        err = "'probes' must be an object";
        return false;
    }
    ProbeGrid& grid = out.probes;
    for (const auto& [key, field] :
         {std::pair<const char*, double*>{"height_m", &grid.height_m},
          std::pair<const char*, double*>{"rx_gain_dbi", &grid.rx_gain_dbi},
          std::pair<const char*, double*>{"sinr_db", &grid.sinr_db}})
    {
        if (!probes.contains(key) || !FiniteNumber(probes[key], *field))
        {
            err = std::string("'probes.") + key + "' must be a finite number";
            return false;
        }
    }
    if (grid.height_m < 0.0)
    {
        err = "'probes.height_m' must be >= 0";
        return false;
    }
    if (!probes.contains("points") || !probes["points"].is_array())
    {
        err = "'probes.points' must be an array of [x, y] points";
        return false;
    }
    const json& points = probes["points"];
    if (points.size() > kMaxProbes)
    {
        err = "'probes.points' has " + std::to_string(points.size()) + " entries; limit is " +
              std::to_string(kMaxProbes);
        return false;
    }
    grid.points.resize(points.size());
    for (std::size_t k = 0; k < points.size(); ++k)
    {
        const json& p = points[k];
        Position& pos = grid.points[k];
        if (!p.is_array() || p.size() != 2 || !FiniteNumber(p[0], pos.x) ||
            !FiniteNumber(p[1], pos.y))
        {
            err = "probes.points[" + std::to_string(k) + "] must be [x, y] finite numbers";
            return false;
        }
        pos.z = grid.height_m;
    }
    out.hasProbes = true;
    return true;
}

ojson
BuildInit(const SimConfig& cfg, uint32_t planningSeed)
{
    ojson ids = ojson::array();
    ojson types = ojson::array();
    ojson mobility = ojson::array();
    ojson starts = ojson::array();
    for (const auto& spec : cfg.nodes)
    {
        ids.push_back(spec.id);
        types.push_back(spec.node_type);
        mobility.push_back(spec.mobility);
        const Position p = ControlledStartPosition(spec);
        starts.push_back(ojson::array({p.x, p.y, p.z}));
    }
    std::size_t jammersEnabled = 0;
    for (const auto& j : cfg.jammers)
    {
        if (j.enabled)
        {
            ++jammersEnabled;
        }
    }

    const auto& ch = cfg.channel;
    ojson channel;
    channel["frequency_ghz"] = ch.frequency_ghz;
    channel["tx_power_dbm"] = ch.tx_power_dbm;
    channel["bandwidth_mhz"] = ch.bandwidth_mhz;
    channel["noise_figure_db"] = ch.noise_figure_db;
    channel["amc_model"] = ch.amc_model;
    channel["channel_model"] = ch.channel_model;
    channel["scenario"] = ch.scenario;
    channel["condition_model"] = ch.condition_model;
    channel["tx_array_gain_dbi"] = ch.tx_array_gain_dbi;
    channel["rx_array_gain_dbi"] = ch.rx_array_gain_dbi;

    ojson limits;
    limits["max_layouts"] = kMaxLayouts;
    limits["max_probes"] = kMaxProbes;
    limits["max_request_line_bytes"] = kMaxRequestLineBytes;
    limits["max_child_response_bytes"] = cfg.query.max_child_response_bytes;
    limits["max_response_bytes"] = cfg.query.max_response_bytes;
    limits["terminate_grace_s"] = cfg.query.terminate_grace_s;
    limits["child_deadline_s"] = cfg.query.child_deadline_s;

    ojson init;
    init["type"] = "init";
    init["contract"] = kContract;
    init["isolation"] = "fork_per_layout";
    init["node_ids"] = ids;
    init["node_types"] = types;
    init["mobility"] = mobility;
    init["start_positions"] = starts;
    init["controlled_indices"] = cfg.rl.controlled_indices;
    init["rl_enabled"] = cfg.rl.enabled;
    init["band"] = cfg.band;
    init["band_source"] = cfg.band_source;
    init["seed"] = planningSeed;
    init["run_id"] = cfg.run_id;
    init["jammer_seed"] = planningSeed;
    init["sinr_threshold_db"] = SINR_MIN_DB;
    init["jammer_path_enabled"] = (cfg.band == "sub-6" && jammersEnabled > 0);
    init["num_buildings"] = cfg.buildings.size();
    init["channel"] = channel;
    init["limits"] = limits;
    init["time_s"] = 0.0;
    return init;
}

bool
ParseRequest(const std::string& line, std::size_t numNodes, Request& request, std::string& err)
{
    const json req = json::parse(line, nullptr, false);
    if (req.is_discarded())
    {
        err = "malformed JSON request";
        return false;
    }
    if (!req.is_object())
    {
        err = "request must be a JSON object";
        return false;
    }

    if (req.contains("request_id") && !req["request_id"].is_null())
    {
        const json& rid = req["request_id"];
        if (!rid.is_number_integer())
        {
            err = "'request_id' must be an integer";
            return false;
        }
        request.id = rid.is_number_unsigned() ? ojson(rid.get<std::uint64_t>())
                                              : ojson(rid.get<std::int64_t>());
    }
    if (!req.contains("type") || !req["type"].is_string())
    {
        err = "request needs a string 'type'";
        return false;
    }
    const std::string type = req["type"].get<std::string>();
    if (type == "shutdown")
    {
        request.shutdown = true;
        return true;
    }
    if (type != "evaluate")
    {
        err = "unknown request type '" + type + "'";
        return false;
    }

    return ParseEvaluate(req, numNodes, request.evaluate, err);
}

} // namespace mesh_sim::query
