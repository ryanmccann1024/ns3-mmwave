#pragma once
#include "src/domain/query-config.h"
#include "src/util/ini-parser.h"

#include <string>
#include <vector>

namespace mesh_sim
{
QueryConfig LoadQueryConfig(const IniMap&);
std::vector<std::string> ValidateQueryConfig(const QueryConfig&);
} // namespace mesh_sim
