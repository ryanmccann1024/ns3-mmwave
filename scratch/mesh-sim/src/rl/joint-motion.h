#pragma once

#include "src/domain/sim-config.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace mesh_sim
{
using MotionPoint = std::array<double, 3>;

inline MotionPoint MotionAt(const MotionPoint& p, const MotionPoint& v,
                            const RlConfig& bounds, double t, bool clipped)
{
    MotionPoint q{p[0]+v[0]*t, p[1]+v[1]*t, p[2]+v[2]*t};
    if (clipped)
    {
        q[0] = std::clamp(q[0], bounds.x_min, bounds.x_max);
        q[1] = std::clamp(q[1], bounds.y_min, bounds.y_max);
    }
    return q;
}

inline double JointPathDistance(const MotionPoint& a, const MotionPoint& av,
                                const MotionPoint& b, const MotionPoint& bv,
                                const RlConfig& bounds, double horizon,
                                bool clipA = true, bool clipB = true)
{
    std::vector<double> times{0.0, horizon};
    const double lo[] = {bounds.x_min, bounds.y_min}, hi[] = {bounds.x_max, bounds.y_max};
    auto addWalls = [&](const MotionPoint& p, const MotionPoint& v, bool clipped) {
        if (!clipped) return;
        for (int axis = 0; axis < 2; ++axis)
            if (v[axis] != 0.0)
            {
                const double t = ((v[axis] > 0.0 ? hi[axis] : lo[axis]) - p[axis]) / v[axis];
                if (t > 0.0 && t < horizon) times.push_back(t);
            }
    };
    addWalls(a, av, clipA); addWalls(b, bv, clipB);
    std::sort(times.begin(), times.end());
    double minimum = INFINITY;
    for (size_t k = 1; k < times.size(); ++k)
    {
        const auto a0 = MotionAt(a, av, bounds, times[k-1], clipA);
        const auto b0 = MotionAt(b, bv, bounds, times[k-1], clipB);
        const auto a1 = MotionAt(a, av, bounds, times[k], clipA);
        const auto b1 = MotionAt(b, bv, bounds, times[k], clipB);
        double numerator = 0.0, denominator = 0.0;
        MotionPoint r{}, delta{};
        for (int axis = 0; axis < 3; ++axis)
        {
            r[axis] = a0[axis]-b0[axis];
            delta[axis] = (a1[axis]-b1[axis])-r[axis];
            numerator += r[axis]*delta[axis];
            denominator += delta[axis]*delta[axis];
        }
        const double u = denominator > 0.0 ? std::clamp(-numerator/denominator, 0.0, 1.0) : 0.0;
        double squared = 0.0;
        for (int axis = 0; axis < 3; ++axis) squared += std::pow(r[axis]+u*delta[axis], 2);
        minimum = std::min(minimum, std::sqrt(squared));
    }
    return minimum;
}

inline std::vector<bool> RejectUnsafeJointMotion(const std::vector<MotionPoint>& positions,
    std::vector<MotionPoint>& velocities, const std::vector<bool>& controlled,
    const RlConfig& bounds, double horizon)
{
    std::vector<bool> rejected(positions.size(), false);
    // Recheck after stopping a node: its stationary path can obstruct another move.
    for (size_t pass = 0; pass <= positions.size(); ++pass)
    {
        bool changed = false;
        for (size_t i = 0; i < positions.size(); ++i)
            for (size_t j = i+1; j < positions.size(); ++j)
            {
                if (JointPathDistance(positions[i], velocities[i], positions[j], velocities[j],
                    bounds, horizon, controlled[i], controlled[j]) >= bounds.unsafe_separation_m) continue;
                for (const auto node : {i, j})
                    if (controlled[node] && velocities[node] != MotionPoint{0,0,0})
                    {
                        velocities[node] = {0,0,0}; rejected[node] = true; changed = true;
                    }
                if (!changed && JointPathDistance(positions[i], velocities[i], positions[j], velocities[j],
                    bounds, horizon, controlled[i], controlled[j]) < bounds.unsafe_separation_m)
                    throw std::runtime_error("node collision cannot be resolved by holding controlled nodes");
            }
        if (!changed) return rejected;
    }
    throw std::runtime_error("joint movement safety did not settle");
}
}
