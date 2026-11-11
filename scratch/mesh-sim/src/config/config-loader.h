/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file config-loader.h
 * @brief Parses @c run.ini and the JSON files it references into a fully
 *        populated @ref mesh_sim::SimConfig.
 *
 * No ns-3 headers. Missing keys take the defaults listed below; the loader
 * does not range-check values (see @ref mesh_sim::ValidateConfig).
 *
 * See @ref src_config_run_ini_reference for the complete key and default tables.
 * The loader reads scenario and output settings, channel models, flow-level
 * traffic and routing, RL controls, and optional mission settings.
 */
#pragma once

#include "src/domain/sim-config.h"
#include <string>

namespace mesh_sim
{

/**
 * @brief Static factory that loads a complete @ref SimConfig from disk.
 *
 */
class ConfigLoader
{
  public:
    /**
     * @fn ConfigLoader::Load
     * @brief Load a @ref SimConfig from a @c run.ini file and its referenced assets.
     *
     * @param run_config_path          Path to the @c run.ini file (required).
     * @param positions_override_path  Optional path to a positions-override
     *                                 JSON file. Positions are applied after
     *                                 @c nodes.json is loaded. Pass an empty
     *                                 string (the default) to skip.
     * @return Fully populated @ref SimConfig ready for validation and use.
     * @throws std::runtime_error  If @c channel_model is neither @c "3gpp"
     *                             nor @c "nyu"; if the nodes file cannot be
     *                             opened; if a @c jammers_file or
     *                             @c buildings_file is specified but cannot
     *                             be opened; or if
     *                             @c positions_override_path is non-empty but
     *                             the file cannot be opened.
     * @throws std::invalid_argument / std::out_of_range  From @c std::stoul /
     *                             @c std::stod on a non-numeric or overflowing
     *                             INI value.
     * @throws nlohmann::json::exception  On malformed JSON, a node without
     *                             @c id, or a positions-override entry that
     *                             is not a 3-element numeric array.
     *
     * Steps: parse @c run.ini; fill the sections above; load the nodes,
     * jammers, and buildings files in that order; apply the positions
     * override. Does not validate ranges or enum values (except @c channel_model and strict query
     * option parsing). Building entries require explicit numeric bounds; nested and flat
     * representations may not conflict. When @c [output]
     * @c dir is empty the timestamped directory is derived from the local
     * clock and assumes the run.ini lives three levels below the mesh-sim
     * root (for example @c inputs/baselines/foo/run.ini). Reads files only;
     * creates no directories.
     */
    static SimConfig Load(const std::string& run_config_path,
                          const std::string& positions_override_path = "");
};

}  // namespace mesh_sim
