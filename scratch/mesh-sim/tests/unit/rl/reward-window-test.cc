#include "src/rl/reward-window.h"

#include <cassert>
#include <cmath>
#include <iostream>

int main()
{
    mesh_sim::RewardWindow window(0.3);
    assert(!window.AddTick(0.0, 1000.0));
    window.AddTick(0.1, -1000.0);
    assert(window.Ticks() == 2 && window.ScoredTicks() == 0);
    assert(window.Mean() == 0.0);
    assert(window.AddTick(0.3, 1.0));
    window.AddTick(0.4, -1.0);
    window.AddTick(0.5, 1.0);
    assert(window.Ticks() == 5 && window.ScoredTicks() == 3);
    assert(std::abs(window.Mean() - 1.0 / 3.0) < 1e-12);

    window.Reset();
    assert(window.Ticks() == 0 && window.ScoredTicks() == 0 && window.Mean() == 0.0);
    window.AddTick(0.6, -1.0);
    assert(window.Ticks() == 1 && window.ScoredTicks() == 1 && window.Mean() == -1.0);

    mesh_sim::RewardWindow noWarmup(0.0);
    noWarmup.AddTick(0.0, 10.0);
    assert(noWarmup.ScoredTicks() == 1 && noWarmup.Mean() == 10.0);
    std::cout << "Reward warmup, boundary, mean, and reset checks passed.\n";
}
