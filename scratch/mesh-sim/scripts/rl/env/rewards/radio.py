"""Opt-in radio bridge support and sufficient-area rewards; historical math is frozen."""

import math
from scripts.rl.env.state.measurements import global_bridge_support
from scripts.rl.env.rewards.coordination import decomposition as previous_decomposition

DEFINITIONS = (
    " D=relevant delivered/offered, survivor critical demand in recovery; "
    "F=mean lowest ceil(active demanded endpoints/3) service ratios; "
    "T=mean available actual/permitted XY travel; B=actual wall-contact fraction; "
    "J=peer-rejected movement fraction. No charge for being near a wall or HOLD. "
    "Settling requires 30 s with D>=0.90 and worst-peer service>=0.80; "
    "relapse after 5 s with D<0.85 or worst-peer<0.70, immediately below D=0.50 or worst-peer=0.20. "
)


def decomposition(facts, contract, parameters):
    terms, weights = previous_decomposition(facts, contract, parameters, True)
    if facts["coordination_v1"]["mission"] in ("recovery", "jamming"):
        weights.pop("I")
        terms["radio_deficit"] = 1 - global_bridge_support(facts, contract)
        weights["radio_deficit"] = -parameters["team_penalty"]
    elif facts["coordination_v1"]["mission"] == "coverage":
        terms["useful_area"] = min(terms["area"], parameters["coverage_goal"])
        weights["useful_area"] = weights.pop("area")
    else:
        raise ValueError("Phase 7 reward requires service or coverage mission")
    return terms, weights


def register(T, registry):
    for kind in ("service", "coverage"):
        name = (
            f"coordinated_{kind}_bridge_v1"
            if kind == "service"
            else "coordinated_coverage_sufficient_v1"
        )

        def calculate(w, r, c, p, x, expected=kind):
            state = x["coordination_v1"]
            t = state["terms"]
            mission = state["mission"]
            if (expected == "service" and mission not in ("recovery", "jamming")) or (
                expected == "coverage" and mission != "coverage"
            ):
                raise ValueError("Phase 7 reward mission mismatch")
            if (
                not state["eligible"]
                or not t["active_count"]
                or (expected == "service" and t["demand"] <= 1e-9)
            ):
                return 0.0, False
            terms, weights = decomposition(x, c, p)
            return sum(terms[k] * v for k, v in weights.items()), True

        formula = (
            "restore: (0.60-s) D + 0.40 F + s L - {team_penalty}(1-G) - 0.002 T - 0.02 B - 0.02 J; s=0.10+0.20*(1-current active-pair LOS fraction); "
            "settle: 0.65 D + 0.35 F - {team_penalty}(1-G) - 0.05 T - 0.02 B - 0.02 J. "
            "G=sigmoid((weakest active-pair widest-path SINR_dB+6.7)/4); all current available pairs, not just demanded pairs; fewer than two peers G=0. "
            "G is radio support, not a capacity guarantee. The old XY isolation penalty is replaced, not added. "
            if kind == "service"
            else "expand: 0.95 C_useful + 0.05 F - 0.002 T - 0.02 B - 0.02 J; settle: 0.75 C_useful + 0.25 F - 0.05 T - 0.02 B - 0.02 J; "
            "C_useful=min(actual connected outdoor area fraction,{coverage_goal}); sufficient-area objective, not maximization of raw area. "
        )
        definitions = DEFINITIONS + (
            "L=mean lowest ceil(demanded pairs/3) widest-path sigmoid SINR scores using the same -6.7 dB threshold and 4 dB scale. "
            if kind == "service"
            else "Coverage also requires actual area>={coverage_goal} to settle and relapses below target-0.02. No compact-clustering term. "
        )
        registry[name] = T(
            name,
            calculate,
            (-20.0, 21.0),
            ("coordination_v1",),
            context_fields=("coordination_v1", "mission_state", "links", "node_available"),
            contract_fields=("mission", "bounds", "node_ids"),
            tunable={
                "coverage_goal": (0.9, 0.01, 1.0),
                "gamma": (0.99, 0.0, 1.0),
                "potential_scale": (10.0, 0.0, 20.0),
                "mission_code": (2 if kind == "service" else 0, -1.0, 3.0),
                "team_penalty": (0.05, 0.0, 1.0),
            },
            fact_extensions=("coordination_v1",),
            formula=formula + definitions,
            zero_demand_rule="invalid forced/mixed windows; no active peers invalid; service requires offered demand; failed peers excluded",
        )
