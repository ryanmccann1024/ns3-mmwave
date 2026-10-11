/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file sim-config.h
 * @brief Top-level simulation configuration and runtime metadata POD types.
 *
 * @ref SimConfig is the single root object that flows through the entire
 * simulation.  It is produced by @ref ConfigLoader::Load, validated by
 * @ref ValidateConfig, and then passed by const-reference to every
 * subsystem constructor.
 * @ref TimingInfo is intentionally separate from @ref SimConfig because it
 * is not loaded from any file — it is populated by @c sim.cc after the step
 * loop completes and written to the output JSON by @c MetricsWriter.
 */
#pragma once

#include "channel-config.h"
#include "mesh-config.h"
#include "query-config.h"
#include "node-spec.h"
#include "src/jammer/jammer-spec.h"

#include <chrono>
#include <cstdint>
#include <string>
#include <vector>

namespace mesh_sim
{

/**
 * @brief Wall-clock timing metadata for one simulation run.
 *
 * Not loaded from any configuration file. Populated by @c sim.cc
 * immediately before and after the main step loop, then passed to
 * @c MetricsWriter which converts the @c time_point values to ISO-8601
 * strings in the output JSON.
 */
struct TimingInfo
{
    std::chrono::system_clock::time_point start;  ///< Wall-clock time at sim start.
    std::chrono::system_clock::time_point end;    ///< Wall-clock time at sim end.
    double elapsed_s = 0.0;                        ///< Total wall-clock duration in seconds
                                                   ///<   (@c end - @c start as a double).
};

struct RlConfig
{
    bool        enabled             = false;         ///< Enable RL mode when @c true.
    std::string reward_type         = "throughput";  ///< Reward signal:
                                                     ///<   @c "throughput" or @c "all_links_los".
    std::string reward_type_alias;                   ///< Legacy spelling that was normalized
                                                     ///<   (@c "mean_sinr") or empty.
    double step_size_m          = 50.0;   ///< Per-tick displacement in metres at the configured speed cap.

    // ---- Movement bounding box ---------------------------------------------
    double x_min = -1000.0;  ///< Western boundary of the controlled node's allowed area (m).
    double x_max =  2000.0;  ///< Eastern boundary of the controlled node's allowed area (m).
    double y_min = -1000.0;  ///< Southern boundary of the controlled node's allowed area (m).
    double y_max =  1000.0;  ///< Northern boundary of the controlled node's allowed area (m).
    double z_min = 0.0;      ///< Lower altitude limit of the controlled node's allowed area (m).
    double z_max = 100.0;    ///< Upper altitude limit of the controlled node's allowed area (m).

    // ---- Centralized multi-node control (raw @c [rl] keys) -----------------
    std::vector<std::string> unsupported_keys; ///< Removed INI keys for migration errors.
    std::string controlled_nodes;             ///< @c "all" or a comma-separated list of node
                                              ///<   ids; required when RL is enabled.
    bool        controlled_nodes_set = false; ///< @c true when the @c controlled_nodes key is
                                              ///<   present in @c run.ini.
    int         max_controlled_nodes = 0;     ///< Slot count @c M; @c 0 means the resolved
                                              ///<   controlled-node count.
    std::string action_profile = "move_2d";   ///< Centralized action profile; @c "move_2d" only.
    double      decision_interval_s = 0.0;    ///< Seconds between RL decisions; @c 0 means
                                              ///<   @ref SimConfig::tick_s (one decision per tick).

    // ---- Resolved fields (never from INI; written by @c ApplyRlControl) -----
    std::string control_mode = "disabled";        ///< @c "disabled" or @c "centralized".
    std::vector<uint32_t> controlled_indices;   ///< Slot order indices into
                                                ///<   @ref SimConfig::nodes.
    uint32_t num_slots = 0;                     ///< Resolved slot count @c M.
    uint32_t decision_interval_ticks = 1;       ///< Resolved decision cadence @c k in ticks.
    uint32_t num_ticks = 0;                     ///< Loop tick count for the resolved mode.
};

/// @brief `[baseline]` selector; the binary only guards on it and never plans placements.
struct BaselineConfig
{
    std::string algorithm = "none";  ///< @c "none", @c "geometric", or @c "optimization".
};

/**
 * @brief Root simulation configuration aggregating all subsystem parameters.
 *
 * Produced by @ref ConfigLoader::Load from @c run.ini and the JSON files it
 * references. Validated by @ref ValidateConfig before any ns-3 objects are
 * constructed. Passed by const-reference to every subsystem constructor.
 *
 * **Timing parameters** (all in seconds unless the name says @c _ms)
 * - @c tick_s must be <= @c duration_s.
 * - @c warmup_s samples are excluded from all output metrics but the
 *   simulation still runs for the full @c duration_s.
 * - @c viz_tick_ms controls how frequently CSV position/link snapshots are
 *   written; it is independent of @c tick_s.
 */
struct SimConfig
{
    std::string scenario_name;        ///< Human-readable scenario label (from @c [scenario] name).
    uint32_t    seed       = 42;      ///< RNG seed for ns-3 @c RngSeedManager. @c sim.cc overwrites it
                                       ///<   with each value from the resolved seed list.
    uint32_t    run_id     = 1;       ///< ns-3 RNG run number (@c RngSeedManager::SetRun) and
                                       ///<   output metadata; @c --run-id overrides it.
    double      duration_s = 10.0;    ///< Total simulated time in seconds (must be > 0).
    double      warmup_s   = 0.0;     ///< Seconds to exclude from output metrics (>= 0, and
                                       ///<   < @c duration_s). The run still lasts @c duration_s.
    double      tick_s     = 0.1;     ///< Simulation time step in seconds (default 0.1 = 100 ms);
                                       ///<   must be > 0 and <= @c duration_s.
    std::string output_dir;           ///< Base output directory. Auto-generated as a timestamped
                                       ///<   path under @c outputs/ when empty in @c run.ini;
                                       ///<   @c --output-dir overrides it. @c sim.cc appends
                                       ///<   @c /seed-N per seed.

    ChannelConfig channel;  ///< Radio and channel model parameters.
    MeshConfig    mesh;     ///< Traffic generation and routing parameters.

    std::string band        = "mmwave";   ///< Categorical radio mode: @c "mmwave" or @c "sub-6";
                                           ///<   @c "sub-6" enables the jammer-interference path.
    std::string band_source = "default";  ///< Where @c band came from: @c "cli", @c "run.ini",
                                           ///<   or @c "default".

    uint32_t viz_tick_ms = 100;  ///< Interval in milliseconds between CSV viz snapshots
                                  ///<   (positions, link results); default 100 ms.

    RlConfig rl;  ///< Reinforcement-learning controller parameters.
                   ///<   Ignored when @c rl.enabled is @c false.

    QueryConfig query;
    BaselineConfig baseline;  ///< Placement-baseline selector (@c [baseline] algorithm).

    std::vector<NodeSpec>     nodes;      ///< All simulation nodes, in index order.
                                           ///<   Node IDs assigned by @ref TrafficMatrix
                                           ///<   and the link evaluator are indices into
                                           ///<   this vector.
    std::vector<BuildingSpec> buildings;  ///< Optional building obstacles used for
                                           ///<   deterministic LOS/NLOS classification.
                                           ///<   Empty when no @c buildings_file is set.

    std::vector<JammerSpec> jammers;  ///< Optional jammers from @c jammers_file. Their
                                       ///<   interference applies only when @c band is @c "sub-6".

};

}  // namespace mesh_sim
