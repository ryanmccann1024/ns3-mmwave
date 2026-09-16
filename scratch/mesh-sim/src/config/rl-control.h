/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file rl-control.h
 * @brief Pure resolution of the @c [rl] control selectors into slots, cadence,
 *        and tick counts.
 *
 * Single source of truth shared by @ref ValidateConfig (which reports the
 * errors) and @c sim.cc (which applies the resolved fields). No ns-3 headers.
 */
#pragma once

#include "src/domain/node-spec.h"
#include "src/domain/sim-config.h"

#include <cstdint>
#include <string>
#include <vector>

namespace mesh_sim
{

/**
 * @brief Result of a @ref ResolveRlControl call.
 *
 * On success @c errors is empty and the resolved fields are meaningful.
 * On failure @c errors holds one human-readable string per problem found and
 * the resolved fields must not be applied.
 */
struct RlControlResolution
{
    std::vector<std::string> errors;           ///< One entry per resolution failure;
                                               ///<   empty on success.
    std::string control_mode;                  ///< @c "legacy" or @c "centralized".
    std::vector<uint32_t> controlled_indices;  ///< Slot-order node indices
                                               ///<   (legacy: exactly one entry).
    uint32_t num_slots = 0;                    ///< Slot count @c M (legacy: 1).
    uint32_t decision_interval_ticks = 1;      ///< Decision cadence @c k in ticks.
    uint32_t num_ticks = 0;                    ///< Loop tick count for this mode.

    /**
     * @brief Return @c true if no resolution errors were found.
     * @return @c true when @c errors is empty, @c false otherwise.
     */
    bool ok() const { return errors.empty(); }
};

/// Resolve the RL control mode, controlled slots, cadence, and tick count.
RlControlResolution ResolveRlControl(const SimConfig& cfg);

/// Copy a successful resolution into @c cfg.rl's resolved fields.
void ApplyRlControl(SimConfig& cfg, const RlControlResolution& r);

/// Return the loop tick count for a duration/tick pair (@c robust rounds to a tolerance).
uint32_t ComputeTickCount(double duration_s, double tick_s, bool robust);

/// Return a node's control start position (first waypoint for waypoint mobility).
Position ControlledStartPosition(const NodeSpec& spec);

}  // namespace mesh_sim
