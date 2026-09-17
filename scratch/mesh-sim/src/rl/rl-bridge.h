/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/*
 * RL bridge: stdin/stdout JSON IPC between the C++ sim and a Python RL agent.
 *
 * Legacy mode (one controlled node, Discrete(7)) writes one message per tick.
 * Centralized mode (`rl.controlled_nodes`) writes an `init` line once, then one
 * `step` message every `decision_interval_ticks` ticks carrying the joint
 * observation, the authoritative per-slot action mask, and the windowed reward;
 * the action is a MultiDiscrete([5]*M) list. C++ owns masks, speed caps, and the
 * per-tick bounds clamp -- Python never re-derives them. See src/rl/README.md.
 */
#pragma once

#include "src/domain/sim-config.h"
#include "src/eval/link-table.h"
#include "src/routing/mesh-router.h"

#include "ns3/constant-velocity-mobility-model.h"

#include <cstdint>
#include <string>
#include <vector>

namespace mesh_sim
{

/// One action-space slot: a resolved controlled node, or padding when !active.
struct ControlSlot
{
    uint32_t    node_index = 0;    ///< Index into SimConfig::nodes (undefined when padding).
    std::string node_id;           ///< Node id (empty when padding).
    double      speed_mps = 0.0;   ///< min(step_size_m / tick_s, MaxSpeedForType(node_type)).
    bool        active = false;    ///< False for padded slots (hold only).
};

class RlBridge
{
  public:
    explicit RlBridge(const SimConfig& cfg);

    // Write the centralized `init` contract line. Call once before the tick loop.
    void WriteInit() const;

    // True when tick `ti` is a centralized decision boundary.
    bool IsDecisionTick(uint32_t ti) const;

    // Clamp each controlled slot's velocity so this tick cannot leave the bounds.
    void BeforeAdvance(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs);

    // Add this tick's reward to the current decision window (centralized).
    void AccumulateTick(const LinkTable& linkTable, const std::vector<FlowResult>& flows);

    // Write obs+reward to stdout, read action from stdin.
    // If done==true, writes final obs but does not read action.
    void Step(uint32_t tick,
              double time_s,
              const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs,
              const LinkTable& linkTable,
              const std::vector<FlowResult>& flowResults,
              bool done);

    // Apply the last received action to the controlled node(s).
    void ApplyAction(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs);

  private:
    RlConfig    m_rl;
    double      m_tickS;
    uint32_t    m_controlledIdx;
    uint32_t    m_numNodes;
    double      m_maxSpeed;
    std::string m_nodeType;

    // Centralized state
    bool                     m_centralized = false;
    std::vector<ControlSlot> m_slots;
    uint32_t                 m_numSlots = 1;
    uint32_t                 m_k = 1;
    uint32_t                 m_numTicks = 0;
    std::vector<int>         m_lastJoint;        ///< Last joint action (4 == hold).
    std::vector<int>         m_lastMask;         ///< Mask sent in the last step message.
    std::vector<uint32_t>    m_revalidatedSlots; ///< Slots held by revalidation, for the next message.
    double                   m_rewardSum = 0.0;
    uint32_t                 m_rewardTicks = 0;
    uint32_t                 m_decision = 0;
    bool                     m_streamClosed = false;

    // Last action received from Python
    int    m_lastDiscreteAction = 0;
    double m_lastTargetX = 0.0;
    double m_lastTargetY = 0.0;
    double m_lastTargetZ = 0.0;

    double ComputeRewardTick(const LinkTable& linkTable,
                             const std::vector<FlowResult>& flows) const;
    void WriteObs(uint32_t tick, double time_s,
                  const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs,
                  const LinkTable& linkTable,
                  double reward, bool done) const;
    void ReadAction();

    void WriteStep(uint32_t tick, double time_s,
                   const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs,
                   const LinkTable& linkTable,
                   const std::vector<int>& mask,
                   double reward, uint32_t ticksInStep, bool done) const;
    std::vector<int> ComputeMask(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs) const;
    void ReadJointAction();
    ns3::Vector ClampVelocityForTick(const ns3::Vector& pos, const ns3::Vector& vel) const;
};

}  // namespace mesh_sim
