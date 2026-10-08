/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file ns3-mobility-stub.h
 * @brief Stub for ns3/mobility-model.h so viz-writer.cc compiles without ns-3.
 *
 * Provides ns3::Vector and a MobilityModel whose position is set directly by
 * the test. ns3::Ptr comes from the shared random-variable stub (pulled in via
 * ns3/random-variable-stream.h) so traffic-matrix.h and this header agree on
 * one Ptr definition. Not behavioral beyond GetPosition().
 */
#pragma once

#include "ns3/random-variable-stream.h"

namespace ns3
{

struct Vector
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

class MobilityModel
{
  public:
    MobilityModel() = default;
    MobilityModel(double x, double y, double z) : m_pos{x, y, z} {}
    Vector GetPosition() const { return m_pos; }
    void SetPosition(const Vector& v) { m_pos = v; }

  private:
    Vector m_pos;
};

}  // namespace ns3
