#pragma once
#include "src/domain/query-config.h"

#include <functional>
#include <ostream>
#include <string>

namespace mesh_sim::query
{
void InstallTerminationForwarding();
bool RunChild(const std::function<std::string()>& evaluate,
              const QueryConfig& policy,
              std::ostream& out,
              std::string& body,
              std::string& failure);
} // namespace mesh_sim::query
