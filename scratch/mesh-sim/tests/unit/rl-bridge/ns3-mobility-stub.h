/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file ns3-mobility-stub.h
 * @brief Deterministic ns-3 mobility stubs for the RL bridge unit tests.
 *
 * Provides a non-owning Ptr, Vector, a MobilityModel whose position and
 * velocity are set directly by the test, and a ConstantVelocityMobilityModel
 * that records SetVelocity calls. Nothing moves on its own: the test advances
 * positions with ConstantVelocityMobilityModel::AdvanceForTest, standing in
 * for Simulator::Run. The RNG types exist only so traffic-matrix.h (pulled in
 * by mesh-router.h) compiles.
 *
 * The Makefile symlinks this file as ns3/constant-velocity-mobility-model.h
 * and ns3/random-variable-stream.h.
 */
#pragma once

#include <cstdint>

namespace ns3
{

// --- Ptr (non-owning; tests own the objects) ---

template <typename T>
class Ptr
{
  public:
    Ptr() = default;
    Ptr(T* p) : m_ptr(p) {}
    T* operator->() const { return m_ptr; }
    T& operator*() const { return *m_ptr; }
    operator bool() const { return m_ptr != nullptr; }
    T* Get() const { return m_ptr; }
  private:
    T* m_ptr = nullptr;
};

// --- RNG types referenced by traffic-matrix.h (not behavioral) ---

class RandomVariableStream {};
class UniformRandomVariable : public RandomVariableStream {};
class ExponentialRandomVariable : public RandomVariableStream {};

// --- Vector ---

struct Vector
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    Vector() = default;
    Vector(double x_, double y_, double z_) : x(x_), y(y_), z(z_) {}
};

// --- MobilityModel: position/velocity are plain test-controlled state ---

class MobilityModel
{
  public:
    virtual ~MobilityModel() = default;

    Vector GetPosition() const { return m_pos; }
    void   SetPosition(const Vector& p) { m_pos = p; }
    Vector GetVelocity() const { return m_vel; }

    /// Test hook: velocity reported for a non-controllable model (e.g. a random walk).
    void SetTestVelocity(const Vector& v) { m_vel = v; }

    /// ns-3 GetObject aggregation lookup, reduced to a dynamic_cast.
    template <typename T>
    Ptr<T> GetObject()
    {
        return Ptr<T>(dynamic_cast<T*>(this));
    }

  protected:
    Vector m_pos;
    Vector m_vel;
};

// --- ConstantVelocityMobilityModel: records every SetVelocity call ---

class ConstantVelocityMobilityModel : public MobilityModel
{
  public:
    void SetVelocity(const Vector& v)
    {
        m_vel = v;
        ++m_setVelocityCalls;
    }

    /// Test hook standing in for Simulator::Run: move for @p dt seconds at the current velocity.
    void AdvanceForTest(double dt)
    {
        m_pos.x += m_vel.x * dt;
        m_pos.y += m_vel.y * dt;
        m_pos.z += m_vel.z * dt;
    }

    uint32_t SetVelocityCalls() const { return m_setVelocityCalls; }

  private:
    uint32_t m_setVelocityCalls = 0;
};

}  // namespace ns3
