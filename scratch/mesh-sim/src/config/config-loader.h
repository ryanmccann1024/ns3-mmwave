/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file config-loader.h
 * @brief Parses @c run.ini and the JSON files it references into a fully
 *        populated @ref SimConfig.
 *
 * No ns-3 headers. Missing keys take the defaults listed below; the loader
 * does not range-check values (see @ref ValidateConfig).
 *
 * | Section        | Key fields loaded                                                    |
 * |----------------|----------------------------------------------------------------------|
 * | @c scenario  | @c name, @c seed, @c run_id, @c duration_s, @c warmup_s, @c tick_s, @c nodes_file, @c buildings_file |
 * | @c output   | @c dir, @c viz_tick_ms                                               |
 * | @c channel   | @c frequency_ghz, @c tx_power_dbm, @c scenario, @c channel_model, @c blockage_enabled, @c beamforming_model, @c amc_model, @c noise_figure_db, @c bandwidth_mhz, @c tx_array_gain_dbi, @c rx_array_gain_dbi |
 * | @c nyu_channel | All @ref NyuChannelConfig fields; only applied when @c channel_model is @c "nyu" |
 * | @c traffic   | @c model, @c demand_mbps, @c arrival_rate_hz, @c on_time_s, @c off_time_s, @c holding_time_s, @c flow_topology, @c random_pair_count, @c gateway_node_id |
 * | @c routing   | @c algorithm, @c max_hops                                            |
 * | @c rl        | @c enabled, @c controlled_nodes, @c max_controlled_nodes, @c action_profile, @c decision_interval_s, @c reward_type, @c step_size_m, @c x_min/x_max/y_min/y_max/z_min/z_max |
 * | @c rl        | (centralized control) @c controlled_nodes, @c max_controlled_nodes, @c action_profile, @c decision_interval_s. Presence of the @c controlled_nodes key alone selects centralized mode (@c controlled_nodes_set) |
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
     * override. Does not validate ranges or enum values (except @c channel_model). When @c [output]
     * @c dir is empty the timestamped directory is derived from the local
     * clock and assumes the run.ini lives three levels below the mesh-sim
     * root (for example @c inputs/baselines/foo/run.ini). Reads files only;
     * creates no directories.
     */
    static SimConfig Load(const std::string& run_config_path,
                          const std::string& positions_override_path = "");
};

}  // namespace mesh_sim