/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
#pragma once

#include <cstdint>

namespace mesh_sim
{

// Score the same time window as MetricsWriter while keeping decision cadence.
class RewardWindow
{
  public:
    explicit RewardWindow(double warmup_s) : m_warmupS(warmup_s) {}

    void AddTick(double time_s, double reward)
    {
        ++m_ticks;
        if (time_s >= m_warmupS)
        {
            m_sum += reward;
            ++m_scoredTicks;
        }
    }

    double WarmupS() const { return m_warmupS; }
    uint32_t Ticks() const { return m_ticks; }
    uint32_t ScoredTicks() const { return m_scoredTicks; }
    double Mean() const { return m_scoredTicks ? m_sum / m_scoredTicks : 0.0; }
    void Reset() { m_ticks = 0; m_scoredTicks = 0; m_sum = 0.0; }

  private:
    double m_warmupS;
    uint32_t m_ticks = 0;
    uint32_t m_scoredTicks = 0;
    double m_sum = 0.0;
};

}  // namespace mesh_sim
