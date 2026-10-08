/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file ns3-traffic-extra-stub.h
 * @brief Scriptable ns-3 RNG stubs for the traffic-extra unit tests.
 *
 * Unlike tests/unit/traffic/ns3-traffic-stub.h, draws can be scripted per
 * test so specific Poisson arrival counts, src/dst picks and on/off phase
 * durations can be forced, and every draw is counted.
 *
 * - UniformRandomVariable::GetValue() pops @c traffic_stub::g_uniformScript,
 *   else falls back to a seeded std::mt19937_64 in [0, 1).
 * - UniformRandomVariable::GetInteger(min, max) uses the same uniform source
 *   and the real ns-3 mapping: (uint32_t)(min + u * (max + 1 - min)).
 * - ExponentialRandomVariable::GetValue() pops @c traffic_stub::g_expScript
 *   (an absolute value, ignoring the mean), else returns the configured mean
 *   (ExpFallback::Mean) or a real exponential sample -mean*log(1-u)
 *   (ExpFallback::Random). The mean in effect for each draw is logged.
 *
 * The Makefile symlinks this file as ns3/random-variable-stream.h and ns3/double.h.
 */
#pragma once

#include <cmath>
#include <cstdint>
#include <deque>
#include <random>
#include <string>
#include <vector>

namespace traffic_stub
{

enum class ExpFallback
{
    Mean,
    Random
};

inline std::deque<double>  g_uniformScript;
inline std::deque<double>  g_expScript;
inline std::vector<double> g_expMeans;          ///< Mean in effect for each exp draw.
inline uint64_t            g_uniformDraws = 0;  ///< GetValue + GetInteger calls.
inline uint64_t            g_uniformFallbackDraws = 0;
inline uint64_t            g_expDraws = 0;
inline ExpFallback         g_expFallback = ExpFallback::Mean;
inline std::mt19937_64     g_engine{1};

/** Reset all scripts, counters and the fallback engine. */
inline void
Reset(uint64_t seed = 1, ExpFallback fb = ExpFallback::Mean)
{
    g_uniformScript.clear();
    g_expScript.clear();
    g_expMeans.clear();
    g_uniformDraws = 0;
    g_uniformFallbackDraws = 0;
    g_expDraws = 0;
    g_expFallback = fb;
    g_engine.seed(seed);
}

inline double
EngineU01()
{
    // 53-bit uniform in [0, 1).
    return static_cast<double>(g_engine() >> 11) * (1.0 / 9007199254740992.0);
}

inline double
NextUniform()
{
    ++g_uniformDraws;
    if (!g_uniformScript.empty())
    {
        double v = g_uniformScript.front();
        g_uniformScript.pop_front();
        return v;
    }
    ++g_uniformFallbackDraws;
    return EngineU01();
}

}  // namespace traffic_stub

namespace ns3
{

template <typename T>
class Ptr
{
  public:
    Ptr() = default;
    explicit Ptr(T* p) : m_ptr(p) {}
    T* operator->() const { return m_ptr; }
    T& operator*() const { return *m_ptr; }
    operator bool() const { return m_ptr != nullptr; }
  private:
    T* m_ptr = nullptr;
};

template <typename T>
Ptr<T>
CreateObject()
{
    return Ptr<T>(new T());
}

class DoubleValue
{
  public:
    DoubleValue() = default;
    explicit DoubleValue(double v) : m_val(v) {}
    double Get() const { return m_val; }
  private:
    double m_val = 0.0;
};

class RandomVariableStream
{
  public:
    virtual ~RandomVariableStream() = default;
    virtual void SetAttribute(const std::string&, const DoubleValue&) {}
};

class UniformRandomVariable : public RandomVariableStream
{
  public:
    double GetValue() { return traffic_stub::NextUniform(); }

    uint32_t GetInteger(uint32_t min, uint32_t max)
    {
        double u = traffic_stub::NextUniform();
        return static_cast<uint32_t>(static_cast<double>(min) +
                                     u * (static_cast<double>(max) + 1.0 -
                                          static_cast<double>(min)));
    }
};

class ExponentialRandomVariable : public RandomVariableStream
{
  public:
    void SetAttribute(const std::string& name, const DoubleValue& v) override
    {
        if (name == "Mean")
        {
            m_mean = v.Get();
        }
    }

    double GetValue()
    {
        ++traffic_stub::g_expDraws;
        traffic_stub::g_expMeans.push_back(m_mean);
        if (!traffic_stub::g_expScript.empty())
        {
            double v = traffic_stub::g_expScript.front();
            traffic_stub::g_expScript.pop_front();
            return v;
        }
        if (traffic_stub::g_expFallback == traffic_stub::ExpFallback::Mean)
        {
            return m_mean;
        }
        return -m_mean * std::log(1.0 - traffic_stub::EngineU01());
    }

  private:
    double m_mean = 1.0;
};

}  // namespace ns3
