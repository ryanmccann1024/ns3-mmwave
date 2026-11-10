/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file rl-motion.cc
 * @brief Applies RL actions, masks unsafe proposals, and enforces motion constraints.
 */

#include "src/rl/joint-motion.h"
#include "src/rl/rl-bridge.h"

#include <algorithm>
#include <cmath>

namespace mesh_sim
{
namespace
{
constexpr double kWallEps = 1e-6;
} // namespace

bool
RlBridge::CrossesBuilding(const ns3::Vector& a, const ns3::Vector& b) const
{
    if (!m_rl.avoid_buildings)
        return false;
    for (const auto& building : m_buildings)
        if (SegmentIntersectsBuilding({a.x, a.y, a.z},
                                      {b.x, b.y, b.z},
                                      building,
                                      m_rl.building_clearance_m))
            return true;
    return false;
}

std::vector<int>
RlBridge::ComputeMask(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs) const
{
    std::vector<int> mask(5 * m_numSlots, 0);
    for (uint32_t i = 0; i < m_numSlots; ++i)
    {
        const auto& slot = m_slots[i];
        if (!slot.active || !m_available[slot.node_index] || m_decisionTimeS < m_rl.control_start_s)
        {
            mask[5 * i + kHold] = 1;
            continue;
        }
        auto p = mobs[slot.node_index]->GetPosition();
        mask[5 * i + 0] = (p.x - m_rl.x_min > kWallEps) ? 1 : 0;
        mask[5 * i + 1] = (m_rl.x_max - p.x > kWallEps) ? 1 : 0;
        mask[5 * i + 2] = (p.y - m_rl.y_min > kWallEps) ? 1 : 0;
        mask[5 * i + 3] = (m_rl.y_max - p.y > kWallEps) ? 1 : 0;
        mask[5 * i + 4] = 1;
        const double d = slot.speed_mps * m_k * m_tickS;
        const ns3::Vector targets[] = {{std::max(m_rl.x_min, p.x - d), p.y, p.z},
                                       {std::min(m_rl.x_max, p.x + d), p.y, p.z},
                                       {p.x, std::max(m_rl.y_min, p.y - d), p.z},
                                       {p.x, std::min(m_rl.y_max, p.y + d), p.z}};
        if (m_rl.mask_building_moves && m_rl.avoid_buildings)
        {
            for (int action = 0; action < kHold; ++action)
            {
                if (CrossesBuilding(p, targets[action]))
                {
                    mask[5 * i + action] = 0;
                }
            }
        }
    }
    return mask;
}

// ---------------------------------------------------------------------------
// Movement: per-tick clamp and action application
// ---------------------------------------------------------------------------

void
RlBridge::RevalidateJointMotion(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs,
                                double horizon_s)
{
    if (!m_rl.avoid_node_collisions)
        return;
    std::vector<MotionPoint> positions, velocities;
    std::vector<bool> controlled(m_numNodes, false);
    for (const auto& mob : mobs)
    {
        const auto p = mob->GetPosition(), v = mob->GetVelocity();
        positions.push_back({p.x, p.y, p.z});
        velocities.push_back({v.x, v.y, v.z});
    }
    for (const auto& slot : m_slots)
        if (slot.active && m_available[slot.node_index])
            controlled[slot.node_index] = true;
    const auto rejected =
        RejectUnsafeJointMotion(positions, velocities, controlled, m_rl, horizon_s, m_available);
    for (uint32_t i = 0; i < m_numSlots; ++i)
    {
        const auto& slot = m_slots[i];
        if (!slot.active || !rejected[slot.node_index])
            continue;
        mobs[slot.node_index]->GetObject<ns3::ConstantVelocityMobilityModel>()->SetVelocity(
            ns3::Vector(0, 0, 0));
        m_lastJoint[i] = kHold;
        if (std::find(m_peerRejected.begin(), m_peerRejected.end(), i) == m_peerRejected.end())
            m_peerRejected.push_back(i);
        if (std::find(m_revalidatedSlots.begin(), m_revalidatedSlots.end(), i) ==
            m_revalidatedSlots.end())
            m_revalidatedSlots.push_back(i);
    }
}

ns3::Vector
RlBridge::ClampVelocityForTick(const ns3::Vector& pos, const ns3::Vector& vel) const
{
    auto clampAxis = [this](double p, double v, double lo, double hi) {
        const double next = p + v * m_tickS;
        if (next > hi)
        {
            return (hi > p) ? (hi - p) / m_tickS : 0.0;
        }
        if (next < lo)
        {
            return (lo < p) ? (lo - p) / m_tickS : 0.0;
        }
        return v;
    };

    return ns3::Vector(clampAxis(pos.x, vel.x, m_rl.x_min, m_rl.x_max),
                       clampAxis(pos.y, vel.y, m_rl.y_min, m_rl.y_max),
                       vel.z);
}

void
RlBridge::BeforeAdvance(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs)
{
    for (const auto& slot : m_slots)
    {
        if (!slot.active || !m_available[slot.node_index])
        {
            continue;
        }
        auto cvmm = mobs[slot.node_index]->GetObject<ns3::ConstantVelocityMobilityModel>();
        if (!cvmm)
        {
            continue;
        }
        auto velocity = m_decisionTimeS < m_rl.control_start_s
                            ? ns3::Vector(0, 0, 0)
                            : ClampVelocityForTick(cvmm->GetPosition(), cvmm->GetVelocity());
        auto p = cvmm->GetPosition();
        if (CrossesBuilding(
                p,
                ns3::Vector(p.x + velocity.x * m_tickS, p.y + velocity.y * m_tickS, p.z)))
            velocity = ns3::Vector(0, 0, 0);
        cvmm->SetVelocity(velocity);
    }
    RevalidateJointMotion(mobs, m_tickS);
    // Telemetry only: inspect the velocity after every physical veto. Do not
    // change motion, masks or observations. Record a moving axis reaching a wall
    // once per slot/decision; HOLD and motion parallel to a wall do not count.
    for (uint32_t i = 0; i < m_numSlots; ++i)
    {
        const auto& slot = m_slots[i];
        if (!slot.active || !m_available[slot.node_index] || m_decisionTimeS < m_rl.control_start_s)
            continue;
        auto cvmm = mobs[slot.node_index]->GetObject<ns3::ConstantVelocityMobilityModel>();
        if (!cvmm)
            continue;
        const auto p = cvmm->GetPosition(), v = cvmm->GetVelocity();
        const auto touches = [this](double pos, double vel, double lo, double hi) {
            return (vel > 0.0 && pos + vel * m_tickS >= hi - 1e-9) ||
                   (vel < 0.0 && pos + vel * m_tickS <= lo + 1e-9);
        };
        if ((touches(p.x, v.x, m_rl.x_min, m_rl.x_max) ||
             touches(p.y, v.y, m_rl.y_min, m_rl.y_max)) &&
            std::find(m_boundaryContacted.begin(), m_boundaryContacted.end(), i) ==
                m_boundaryContacted.end())
            m_boundaryContacted.push_back(i);
    }
}

// ---------------------------------------------------------------------------
// ApplyAction: set the selected velocity and revalidate the joint path.
// ---------------------------------------------------------------------------

void
RlBridge::ApplyAction(const std::vector<ns3::Ptr<ns3::MobilityModel>>& mobs)
{
    for (uint32_t i = 0; i < m_numSlots; ++i)
    {
        const auto& slot = m_slots[i];
        if (!slot.active || !m_available[slot.node_index])
        {
            continue;
        }
        double vx = 0.0;
        double vy = 0.0;
        switch (m_decisionTimeS < m_rl.control_start_s ? kHold : m_lastJoint[i])
        {
        case 0:
            vx = -slot.speed_mps;
            break;
        case 1:
            vx = slot.speed_mps;
            break;
        case 2:
            vy = -slot.speed_mps;
            break;
        case 3:
            vy = slot.speed_mps;
            break;
        default:
            break;
        }
        auto cvmm = mobs[slot.node_index]->GetObject<ns3::ConstantVelocityMobilityModel>();
        if (cvmm)
        {
            const auto p = cvmm->GetPosition();
            const auto end = MotionAt({p.x, p.y, p.z}, {vx, vy, 0}, m_rl, m_k * m_tickS, true);
            if (CrossesBuilding(p, ns3::Vector(end[0], end[1], end[2])))
            {
                vx = 0.0;
                vy = 0.0;
                m_lastJoint[i] = kHold;
                m_buildingRejected.push_back(i);
                if (std::find(m_revalidatedSlots.begin(), m_revalidatedSlots.end(), i) ==
                    m_revalidatedSlots.end())
                    m_revalidatedSlots.push_back(i);
            }
            cvmm->SetVelocity(ns3::Vector(vx, vy, 0.0));
        }
    }
    RevalidateJointMotion(mobs, m_k * m_tickS);
}

} // namespace mesh_sim
