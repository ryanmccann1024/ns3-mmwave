/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
#pragma once

#include "src/domain/sim-config.h"
#include "src/rl/reward-window.h"
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
    void AccumulateTick(double time_s, const LinkTable& linkTable, const std::vector<FlowResult>& flows);

    // Write obs+reward to stdout, read action from stdin.
    // If done==true, writes final obs but does not read action.
    void Step(uint32_t tick,
              double time_s,
              const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs,
              const LinkTable& linkTable,
              bool done);

    // Apply the last received action to the controlled node(s).
    void ApplyAction(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs);

  private:
    RlConfig    m_rl;
    double      m_tickS;
    uint32_t    m_numNodes;

    RewardWindow m_rewardWindow;
    std::vector<ControlSlot> m_slots;
    uint32_t                 m_numSlots = 1;
    uint32_t                 m_k = 1;
    uint32_t                 m_numTicks = 0;
    std::vector<int>         m_lastJoint;        ///< Last joint action (4 == hold).
    std::vector<int>         m_lastMask;         ///< Mask sent in the last step message.
    std::vector<uint32_t>    m_revalidatedSlots; ///< Slots held by revalidation, for the next message.
    uint32_t                 m_decision = 0;
    bool                     m_streamClosed = false;

    double ComputeRewardTick(const LinkTable& linkTable,
                             const std::vector<FlowResult>& flows) const;
    void WriteStep(uint32_t tick, double time_s,
                   const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs,
                   const LinkTable& linkTable,
                   const std::vector<int>& mask,
                   double reward, uint32_t ticksInStep, uint32_t scoredTicks, bool done) const;
    std::vector<int> ComputeMask(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs) const;
    void ReadJointAction();
    ns3::Vector ClampVelocityForTick(const ns3::Vector& pos, const ns3::Vector& vel) const;
};

}  // namespace mesh_sim
