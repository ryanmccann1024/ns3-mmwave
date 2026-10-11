#pragma once
#include <cstddef>

namespace mesh_sim
{
struct QueryConfig
{
    double child_deadline_s = 60.0;
    double terminate_grace_s = 1.0;
    std::size_t max_child_response_bytes = 16u * 1024u * 1024u;
    std::size_t max_response_bytes = 64u * 1024u * 1024u;
};
} // namespace mesh_sim
