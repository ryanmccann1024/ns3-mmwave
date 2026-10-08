/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file ns3-eval-jammer-stub.h
 * @brief Deterministic stand-ins for the ns-3 headers used by
 *        link-evaluator.cc and jammer-model.cc.
 *
 * The suite Makefile symlinks this one file as ns3/mobility-model.h,
 * ns3/propagation-loss-model.h and ns3/channel-condition-model.h. It provides
 * only the API surface those sources use:
 *
 * - ns3::Ptr<T> (shared_ptr-backed, converts Derived -> Base and T -> const T)
 * - ns3::Vector, ns3::MobilityModel (fixed position, 3-D Euclidean distance)
 * - ns3::PropagationLossModel (virtual CalcRxPower; tests subclass it)
 * - ns3::ChannelCondition / ns3::ChannelConditionModel (tests subclass it)
 * - NS_ASSERT_MSG, which throws ns3_stub::AssertFailure instead of aborting,
 *   so the size-mismatch assertion in JammerModel::Configure is observable.
 *
 * Nothing here draws random numbers; every value is set by the test.
 */
#pragma once

#include <cmath>
#include <cstddef>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

namespace ns3_stub
{
/// Thrown by the NS_ASSERT_MSG stub when its condition is false.
struct AssertFailure : std::runtime_error
{
    explicit AssertFailure(const std::string& m) : std::runtime_error(m) {}
};
}  // namespace ns3_stub

#ifndef NS_ASSERT_MSG
#define NS_ASSERT_MSG(cond, msg)                                                   \
    do                                                                             \
    {                                                                              \
        if (!(cond))                                                               \
        {                                                                          \
            throw ns3_stub::AssertFailure(std::string("NS_ASSERT_MSG: ") + (msg)); \
        }                                                                          \
    } while (0)
#endif
#ifndef NS_ASSERT
#define NS_ASSERT(cond) NS_ASSERT_MSG(cond, #cond)
#endif

namespace ns3
{

template <typename T>
class Ptr
{
  public:
    Ptr() = default;
    Ptr(std::nullptr_t) {}
    explicit Ptr(std::shared_ptr<T> p) : m_ptr(std::move(p)) {}
    template <typename U>
    Ptr(const Ptr<U>& o) : m_ptr(o.m_ptr)
    {
    }

    T* operator->() const { return m_ptr.get(); }
    T& operator*() const { return *m_ptr; }
    explicit operator bool() const { return m_ptr != nullptr; }
    T* PeekPointer() const { return m_ptr.get(); }

  private:
    template <typename U>
    friend class Ptr;
    std::shared_ptr<T> m_ptr;
};

template <typename T, typename... Args>
Ptr<T>
CreateObject(Args&&... args)
{
    return Ptr<T>(std::make_shared<T>(std::forward<Args>(args)...));
}

struct Vector
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    Vector() = default;
    Vector(double xx, double yy, double zz) : x(xx), y(yy), z(zz) {}
};

/// Fixed-position mobility model; counts distance/position queries.
class MobilityModel
{
  public:
    MobilityModel() = default;
    explicit MobilityModel(const Vector& p) : m_pos(p) {}
    virtual ~MobilityModel() = default;

    Vector GetPosition() const
    {
        ++m_positionCalls;
        return m_pos;
    }
    void SetPosition(const Vector& p) { m_pos = p; }

    double GetDistanceFrom(Ptr<const MobilityModel> other) const
    {
        ++m_distanceCalls;
        const double dx = m_pos.x - other->m_pos.x;
        const double dy = m_pos.y - other->m_pos.y;
        const double dz = m_pos.z - other->m_pos.z;
        return std::sqrt(dx * dx + dy * dy + dz * dz);
    }

    const Vector& RawPosition() const { return m_pos; }

    mutable int m_positionCalls = 0;  ///< GetPosition calls (test introspection).
    mutable int m_distanceCalls = 0;  ///< GetDistanceFrom calls (test introspection).

  private:
    Vector m_pos;
};

/// Base loss model; tests override CalcRxPower.
class PropagationLossModel
{
  public:
    virtual ~PropagationLossModel() = default;
    virtual double CalcRxPower(double txPowerDbm,
                               Ptr<MobilityModel> a,
                               Ptr<MobilityModel> b) const = 0;
};

class ChannelCondition
{
  public:
    enum LosConditionValue
    {
        LOS,
        NLOS,
        NLOSv,
        LC_ND
    };
    explicit ChannelCondition(LosConditionValue v = LOS) : m_los(v) {}
    LosConditionValue GetLosCondition() const { return m_los; }

  private:
    LosConditionValue m_los;
};

/// Base condition model; tests override GetChannelCondition.
class ChannelConditionModel
{
  public:
    virtual ~ChannelConditionModel() = default;
    virtual Ptr<ChannelCondition> GetChannelCondition(Ptr<const MobilityModel> a,
                                                      Ptr<const MobilityModel> b) const = 0;
};

}  // namespace ns3
