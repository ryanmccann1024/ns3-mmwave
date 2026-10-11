#include "src/config/query-config.h"

#include <cmath>
#include <stdexcept>

namespace mesh_sim
{
QueryConfig
LoadQueryConfig(const IniMap& ini)
{
    QueryConfig cfg;
    const auto section = ini.find("channel_query");
    if (section == ini.end())
        return cfg;
    for (const auto& [key, raw] : section->second)
    {
        std::size_t used = 0;
        if (key == "child_deadline_s" || key == "terminate_grace_s")
        {
            const double value = std::stod(raw, &used);
            if (used != raw.size())
                throw std::runtime_error("channel_query." + key + " must be numeric");
            if (key == "child_deadline_s")
                cfg.child_deadline_s = value;
            else
                cfg.terminate_grace_s = value;
        }
        else if (key == "max_child_response_bytes" || key == "max_response_bytes")
        {
            if (raw.empty() || raw.find_first_not_of("0123456789") != std::string::npos)
                throw std::runtime_error("channel_query." + key + " must be an unsigned integer");
            const auto value = std::stoull(raw, &used);
            if (key == "max_child_response_bytes")
                cfg.max_child_response_bytes = value;
            else
                cfg.max_response_bytes = value;
        }
        else
            throw std::runtime_error("unknown channel_query setting: " + key);
    }
    return cfg;
}

std::vector<std::string>
ValidateQueryConfig(const QueryConfig& cfg)
{
    std::vector<std::string> errors;
    if (!std::isfinite(cfg.child_deadline_s) || cfg.child_deadline_s <= 0 ||
        cfg.child_deadline_s > 86400)
        errors.push_back("channel_query.child_deadline_s must be finite and in (0, 86400]");
    if (!std::isfinite(cfg.terminate_grace_s) || cfg.terminate_grace_s <= 0 ||
        cfg.terminate_grace_s > 60)
        errors.push_back("channel_query.terminate_grace_s must be finite and in (0, 60]");
    if (cfg.max_child_response_bytes < 1024 || cfg.max_child_response_bytes > 16u * 1024u * 1024u)
        errors.push_back("channel_query.max_child_response_bytes must be in [1024, 16777216]");
    if (cfg.max_response_bytes < cfg.max_child_response_bytes + 69632 ||
        cfg.max_response_bytes > 256u * 1024u * 1024u)
        errors.push_back("channel_query.max_response_bytes must hold one child plus framing and be "
                         "<= 268435456");
    return errors;
}
} // namespace mesh_sim
