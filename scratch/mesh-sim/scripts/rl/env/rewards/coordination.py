"""Fixed and state-dependent versions of one coordinated mission reward framework."""


def decomposition(facts, contract, parameters, adaptive):
    state = facts["coordination_v1"]
    terms = dict(state["terms"])
    stage = state["stage"]
    kind = state["mission"]
    weights = {"B": -0.02, "J": -0.02, "T": -0.02}
    if kind in ("recovery", "jamming"):
        weights.update(D=0.5, F=0.4, L=0.1, I=-0.05)
        if adaptive:
            if stage == 2:
                weights.update(D=0.65, F=0.35, L=0.0, T=-0.05)
            else:
                signal = 0.1 + 0.2 * terms["los_deficit"]
                weights.update(D=0.6 - signal, F=0.4, L=signal, T=-0.002)
    elif kind == "investigation":
        weights.update(Q=0.45, A=0.45, K=0.1)
        if adaptive:
            if stage == 0:
                weights.update(Q=0.7, A=0.3, K=0.0, T=-0.002)
            elif stage == 1:
                weights.update(Q=0.1, A=0.7, K=0.2, T=-0.01)
            else:
                weights.update(Q=0.1, A=0.6, K=0.2, D=0.1, T=-0.05)
        phi = 0.0 if facts["mission_state"]["done"] else terms["Q"]
        terms["progress"] = parameters["potential_scale"] * (
            parameters["gamma"] * phi - state["previous_q"]
        )
        weights["progress"] = 1.0
    elif kind == "coverage":
        weights.update(area=0.85, F=0.15)
        if adaptive:
            weights.update(
                area=0.75 if stage == 2 else 0.95,
                F=0.25 if stage == 2 else 0.05,
                T=-0.05 if stage == 2 else -0.002,
            )
    else:
        raise ValueError("unsupported coordinated mission")
    return terms, weights


def calculate(window, reward, contract, parameters, context, adaptive):
    state = context["coordination_v1"]
    kind = state["mission"]
    t = state["terms"]
    if (
        not state["eligible"]
        or not t["active_count"]
        or (kind in ("recovery", "jamming") and t["demand"] <= 1e-9)
    ):
        return 0.0, False
    terms, weights = decomposition(context, contract, parameters, adaptive)
    return sum(terms[k] * weight for k, weight in weights.items()), True


FORMULAS = {
    "service": (
        "0.50 D + 0.40 F + 0.10 L - 0.05 I - 0.02 T - 0.02 B - 0.02 J",
        "restore: (0.60-l) D + 0.40 F + l L - 0.05 I - 0.002 T - 0.02 B - 0.02 J, l=0.10+0.20*(1-current active-pair LOS fraction); settle: 0.65 D + 0.35 F - 0.05 I - 0.05 T - 0.02 B - 0.02 J",
    ),
    "investigation": (
        "0.45 Q + 0.45 A + 0.10 K + P - 0.02 T - 0.02 B - 0.02 J",
        "approach: 0.70 Q + 0.30 A + P - 0.002 T; assemble/dwell: 0.10 Q + 0.70 A + 0.20 K + P - 0.01 T; settle: 0.10 Q + 0.60 A + 0.20 K + 0.10 D + P - 0.05 T; all stages subtract 0.02 B + 0.02 J",
    ),
    "coverage": (
        "0.85 area + 0.15 F - 0.02 T - 0.02 B - 0.02 J",
        "expand: 0.95 area + 0.05 F - 0.002 T - 0.02 B - 0.02 J; settle: 0.75 area + 0.25 F - 0.05 T - 0.02 B - 0.02 J",
    ),
}
DEFINITIONS = " D=relevant delivered/offered; F=mean lowest ceil(active demanded peers/3) endpoint service; L=mean lowest ceil(demanded pairs/3) widest-path sigmoid SINR scores, threshold -6.7 dB and scale 4 dB; I=clip(largest XY minimum-spanning-tree edge/150 m,0,1); T=mean available actual/permitted XY travel; B=actual wall-contact fraction; J=peer-rejected movement fraction; Q=0.5 mean + 0.5 minimum of exp(-excess target distance/100 m); A=available peers inside the target / available peers; K=current full-team radio connectivity; P={potential_scale}*({gamma}*Phi_now-Q_previous), terminal Phi=0, otherwise Phi=Q. No compact-clustering term in coverage. Settling requires 30 s current success; relapse fallback after 5 s, severe loss immediately; coverage threshold {coverage_goal}."


def register(T, registry):
    for kind, formulas in FORMULAS.items():
        for adaptive in (False, True):
            name = f'coordinated_{kind}_{"adaptive" if adaptive else "fixed"}_v1'

            def value(w, r, c, p, x, a=adaptive, k=kind):
                mission = x["coordination_v1"]["mission"]
                if (k == "service" and mission not in ("recovery", "jamming")) or (
                    k != "service" and mission != k
                ):
                    raise ValueError("coordinated reward mission mismatch")
                return calculate(w, r, c, p, x, a)

            registry[name] = T(
                name,
                value,
                (-20.0, 21.0),
                ("coordination_v1",),
                context_fields=("coordination_v1", "mission_state"),
                contract_fields=("mission", "bounds", "node_ids"),
                tunable={
                    "coverage_goal": (0.9, 0.01, 1.0),
                    "gamma": (0.99, 0.0, 1.0),
                    "potential_scale": (10.0, 0.0, 20.0),
                    "mission_code": (
                        2 if kind == "service" else 1 if kind == "investigation" else 0,
                        -1.0,
                        3.0,
                    ),
                },
                fact_extensions=("coordination_v1",),
                formula=formulas[int(adaptive)] + DEFINITIONS,
                zero_demand_rule="invalid during forced/mixed windows or with no active peers; service requires offered demand; failed peers excluded; geometric arrival does not require traffic",
            )
