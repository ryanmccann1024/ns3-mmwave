// Compile real evaluator and jammer logic; deterministic models replace ns-3.
#include "src/eval/link-evaluator.h"
#include <cmath>
#include <iostream>

class Loss : public ns3::PropagationLossModel
{
  public:
    double CalcRxPower(double tx, ns3::Ptr<ns3::MobilityModel>,
                       ns3::Ptr<ns3::MobilityModel>) const override { return tx - 130; }
};
class Condition : public ns3::ChannelConditionModel
{
  public:
    ns3::Ptr<ns3::ChannelCondition> GetChannelCondition(
        ns3::Ptr<const ns3::MobilityModel>, ns3::Ptr<const ns3::MobilityModel>) const override
    { return ns3::CreateObject<ns3::ChannelCondition>(ns3::ChannelCondition::LOS); }
};
int main()
{
    using namespace mesh_sim;
    SimConfig cfg;
    cfg.channel.frequency_ghz = 2.4;
    cfg.channel.bandwidth_mhz = 20;
    cfg.channel.noise_figure_db = 5;
    cfg.nodes.resize(2);
    JammerSpec jammer{}; jammer.id = "jammer"; jammer.enabled = true;
    jammer.tx_power_dbm = 100; jammer.type = "constant";
    jammer.duty_cycle = 1; jammer.beamwidth_deg = 360;
    cfg.jammers = {jammer};
    auto a = ns3::CreateObject<ns3::MobilityModel>(ns3::Vector(0,0,0));
    auto b = ns3::CreateObject<ns3::MobilityModel>(ns3::Vector(100,0,0));
    auto loss = ns3::CreateObject<Loss>();
    auto condition = ns3::CreateObject<Condition>();
    LinkEvaluator reused;
    reused.Configure(cfg, loss, condition, "sub-6", {a});
    const auto jammed = reused.Evaluate(a,b,0,1).sinr_db;
    cfg.jammers.clear();
    reused.Configure(cfg, loss, condition, "sub-6", {});
    LinkEvaluator fresh;
    fresh.Configure(cfg, loss, condition, "sub-6", {});
    const auto clean = fresh.Evaluate(a,b,0,1).sinr_db;
    const auto reset = reused.Evaluate(a,b,0,1).sinr_db;
    if (!(jammed < clean && std::abs(reset-clean) < 1e-9))
    {
        std::cerr << "jammer survived reconfiguration: " << jammed << ", " << reset
                  << ", expected fresh evaluator " << clean << '\n';
        return 1;
    }
    std::cout << "Reconfiguration clears old jammers.\n";
}
