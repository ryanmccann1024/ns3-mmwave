"""Availability gates, team cohesion, demanded-path signal, target progress and arrival shaping."""

import math

from scripts.rl.env.rewards.objectives import investigation


def gated_context(facts, contract, inputs):
    w = facts["window"]
    gate = facts.get("deployment")
    ok = bool(w["scored_ticks"]) and (
        gate is None or (gate["active"] and gate["eligible_ticks"] == w["scored_ticks"])
    )
    result = {"phase3_eligible": ok}
    if inputs is not None:
        dt = inputs["elapsed_ticks"] * contract["tick_s"]
        fractions = []
        for slot, node in enumerate(contract["slot_node_ids"]):
            if node is None:
                continue
            i = contract["node_ids"].index(node)
            if not facts["node_available"][i]:
                continue
            moved = math.dist(facts["nodes"][i][:2], inputs["previous_nodes"][i][:2])
            permitted = dt * contract["slot_speed_mps"][slot]
            fractions.append(min(1.0, moved / permitted) if permitted > 0 else 0.0)
        result["phase3_travel"] = sum(fractions) / len(fractions) if fractions and ok else None
    return result


def worst_proximity(w, r, c, p, x):
    m = c["mission"]
    b = c["bounds"]
    d = math.hypot(b["x_max"] - b["x_min"], b["y_max"] - b["y_min"])
    excess = [
        max(0.0, math.dist(n[:2], [m["goal_x"], m["goal_y"]]) - m["team_radius_m"])
        for n, a in zip(x["nodes"], x["node_available"])
        if a
    ]
    return (max(0.0, 1 - max(excess) / d), True) if excess else (0.0, False)


def weakest(w, r, c, p, x, survivor=False):
    if not x["phase3_eligible"]:
        return 0.0, False
    service = x["mission"]["survivor_node_service"] if survivor else x["node_service"]
    ratios = [
        max(0.0, min(1.0, v / d))
        for (d, v), a in zip(service, x["node_available"])
        if a and d > 1e-9
    ]
    return (min(ratios), True) if ratios else (0.0, False)


def boundary(w, r, c, p, x):
    if not x["phase3_eligible"]:
        return 0.0, False
    if "boundary_contacted_slots" not in x["safety"]:
        raise ValueError("boundary-contact reward needs the rebuilt simulator telemetry")
    slots = [
        s
        for s, n in enumerate(c["slot_node_ids"])
        if n is not None and x["node_available"][c["node_ids"].index(n)]
    ]
    contacts = set(x["safety"]["boundary_contacted_slots"])
    if contacts - set(slots):
        raise ValueError("unavailable slot has a boundary contact")
    return (len(contacts) / len(slots), True) if slots else (0.0, False)


def role_proximity(w, r, c, p, x, followers=False, follow_leader=False):
    """Fixed investigator identity; no routing oracle or forced follower actions."""
    m = c["mission"]
    lead = c["node_ids"].index(m["investigator_id"])
    if not x["node_available"][lead]:
        return 0.0, False
    goal = [m["goal_x"], m["goal_y"]]
    radius = m["team_radius_m"]
    b = c["bounds"]
    diagonal = math.hypot(b["x_max"] - b["x_min"], b["y_max"] - b["y_min"])
    lead_pos = x["nodes"][lead][:2]
    target = lead_pos if follow_leader and math.dist(lead_pos, goal) > radius else goal
    selected = [
        i
        for i, a in enumerate(x["node_available"])
        if a and ((i != lead) if followers else (i == lead))
    ]
    values = [
        max(0.0, 1 - max(0.0, math.dist(x["nodes"][i][:2], target) - radius) / diagonal)
        for i in selected
    ]
    return (sum(values) / len(values), True) if values else (0.0, False)


def register_primitives(T, registry):
    def add(name, calc, fields, formula, dependencies=(), builder=None):
        registry[name] = T(
            name,
            calc,
            (0.0, 1.0),
            tuple(f for f in fields if not f.startswith("phase3_")),
            context_fields=fields,
            contract_fields=dependencies,
            context_builder=builder,
            formula=formula,
            zero_demand_rule="no available demand-bearing peer gives zero/invalid; event costs exclude forced/mixed windows",
        )

    add(
        "available_peer_travel_fraction_v1",
        lambda w, r, c, p, x: (x["phase3_travel"] or 0.0, x["phase3_travel"] is not None),
        ("phase3_travel",),
        "mean available controlled peer actual XY travel / permitted travel; zero before event",
        ("slot_speed_mps", "slot_node_ids", "tick_s"),
        gated_context,
    )
    add(
        "worst_peer_target_proximity_v1",
        worst_proximity,
        ("nodes", "node_available"),
        "1 - largest available peer excess distance beyond team radius / field diagonal",
        ("mission", "bounds"),
    )
    add(
        "weakest_survivor_delivery_fraction_v1",
        lambda *args: weakest(*args, survivor=True),
        ("mission", "node_available", "phase3_eligible"),
        "minimum survivor endpoint delivered/offered; exclude failed/zero-demand peers",
        (),
        gated_context,
    )
    add(
        "weakest_active_delivery_fraction_v1",
        weakest,
        ("node_service", "node_available", "phase3_eligible"),
        "minimum available demand-bearing endpoint delivered/offered during emission",
        (),
        gated_context,
    )
    add(
        "boundary_contact_fraction_v1",
        boundary,
        ("safety", "node_available", "phase3_eligible"),
        "fraction available controlled slots moving into a field wall; once per decision, no proximity or HOLD cost",
        ("slot_node_ids", "node_ids"),
        gated_context,
    )
    for name, followers, follow, formula in (
        ("investigator_target_proximity_v1", False, False, "fixed investigator target proximity"),
        (
            "followers_target_proximity_v1",
            True,
            False,
            "mean follower target proximity; neutral-role control",
        ),
        (
            "followers_investigator_then_target_proximity_v1",
            True,
            True,
            "mean follower proximity to investigator until investigator enters target; then follower target proximity; falls back if investigator leaves",
        ),
    ):
        add(
            name,
            lambda w, r, c, p, x, f=followers, l=follow: role_proximity(w, r, c, p, x, f, l),
            ("nodes", "node_available"),
            formula,
            ("mission", "bounds", "node_ids"),
        )


def closeness(w, r, c, p, x):
    if not x["phase3_eligible"] or w["demand_mbps_sum"] <= 1e-9:
        return 0.0, False
    points = [n[:2] for n, a in zip(x["nodes"], x["node_available"]) if a]
    pairs = [math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1 :]]
    diagonal = math.hypot(
        c["bounds"]["x_max"] - c["bounds"]["x_min"], c["bounds"]["y_max"] - c["bounds"]["y_min"]
    )
    return (
        (max(0.0, min(1.0, 1 - sum(pairs) / len(pairs) / diagonal)), True)
        if pairs
        else (0.0, False)
    )


def demanded_path_margin(w, r, c, p, x):
    if not x["phase3_eligible"]:
        return 0.0, False
    ids = c["node_ids"]
    n = len(ids)
    mission = c["mission"]["kind"]
    active = [i for i, a in enumerate(x["node_available"]) if a]
    service = x["mission"]["survivor_node_service"] if mission == "recovery" else x["node_service"]
    active = [i for i in active if service[i][0] > 1e-9]
    if mission == "recovery":
        # The frozen recovery inputs pair matching ground and vehicle suffixes.
        pairs = [
            (i, ids.index("vehicle-" + node.split("-", 1)[1]))
            for i, node in enumerate(ids)
            if node.startswith("ground-") and "vehicle-" + node.split("-", 1)[1] in ids
        ]
        pairs = [(i, j) for i, j in pairs if i in active and j in active]
    elif mission in ("coverage", "jamming"):
        pairs = [(i, j) for i in active for j in active if i < j]
    else:
        raise ValueError(
            "demanded path margin is defined only for the frozen recovery/jamming flow patterns"
        )
    if not pairs:
        return 0.0, False
    floor = -1000.0
    margin = [[floor] * n for _ in range(n)]
    k = 0
    for i in range(n):
        margin[i][i] = float("inf")
        for j in range(i + 1, n):
            sinr = float(x["links"][k][0])
            k += 1
            if i in active and j in active and math.isfinite(sinr) and sinr > -900:
                margin[i][j] = margin[j][i] = sinr
    # Widest SINR path uses current measurements only, including margins below
    # the routing threshold so zero-delivery states can still provide feedback.
    for relay in active:
        for i in active:
            for j in active:
                margin[i][j] = max(margin[i][j], min(margin[i][relay], margin[relay][j]))

    def quality(sinr):
        if sinr >= p["healthy_sinr_db"]:
            return 1.0
        exponent = max(-60.0, min(60.0, (sinr - p["routing_threshold_db"]) / p["scale_db"]))
        return 1 / (1 + math.exp(-exponent))

    score = sum(quality(margin[i][j]) for i, j in pairs) / len(pairs)
    demand = w["demand_mbps_sum"]
    delivery = w["delivered_mbps_sum"] / demand if demand > 1e-9 else 0.0
    if mission == "recovery":
        raw = x["mission"]
        demand = raw["survivor_demand_mbps_sum"]
        delivery = raw["survivor_delivered_mbps_sum"] / demand if demand > 1e-9 else 0.0
    return (1.0 if delivery >= p["healthy_delivery"] else score), True


def progress_context(facts, contract, inputs):
    if inputs is None:
        raise ValueError("target potential reward requires previous positions")
    return {"phase4_previous_nodes": inputs["previous_nodes"]}


def target_potential(w, r, c, p, x):
    if c["mission"]["kind"] != "investigation":
        raise ValueError("target potential requires investigation")
    current, valid = investigation(w, r, c, {}, x)
    if not valid:
        return 0.0, False
    previous, _ = investigation(
        w, r, c, {}, dict(nodes=x["phase4_previous_nodes"], node_available=x["node_available"])
    )
    # Zero terminal potential makes the discounted shaping sum telescope to a
    # policy-independent initial constant, including on the final 600 s step.
    phi = 0.0 if x["mission_state"]["done"] else current
    return current + p["potential_scale"] * (p["gamma"] * phi - previous), True


def register_signal(T, registry):
    registry["available_team_closeness_v1"] = T(
        "available_team_closeness_v1",
        closeness,
        (0.0, 1.0),
        ("nodes", "node_available"),
        context_fields=("nodes", "node_available", "phase3_eligible"),
        context_builder=gated_context,
        contract_fields=("bounds",),
        formula="1 - mean available-peer horizontal pair distance / field diagonal; zero before event",
        zero_demand_rule="invalid with fewer than two available peers",
    )
    registry["demanded_path_sinr_margin_v1"] = T(
        "demanded_path_sinr_margin_v1",
        demanded_path_margin,
        (0.0, 1.0),
        ("links", "node_service", "node_available", "mission"),
        parameters={
            "routing_threshold_db": -6.7,
            "scale_db": 4.0,
            "healthy_sinr_db": 10.0,
            "healthy_delivery": 0.95,
        },
        context_fields=("links", "node_service", "node_available", "mission", "phase3_eligible"),
        context_builder=gated_context,
        contract_fields=("node_ids", "mission"),
        formula="mean sigmoid((widest demanded-path SINR - ({routing_threshold_db} dB))/{scale_db} dB); cap at {healthy_sinr_db} dB or delivery >= {healthy_delivery}; no future measurements",
        zero_demand_rule="invalid with no active demanded pair; exclude failed peers and forced/mixed windows",
    )
    registry["target_proximity_potential_v1"] = T(
        "target_proximity_potential_v1",
        target_potential,
        (-50.0, 51.0),
        ("nodes", "node_available", "mission_state"),
        parameters={"gamma": 0.99, "potential_scale": 50.0},
        context_fields=("nodes", "node_available", "mission_state", "phase4_previous_nodes"),
        context_builder=progress_context,
        contract_fields=("mission", "bounds"),
        formula="Q(t) + {potential_scale} * ({gamma} * Phi(t) - Q(t-1)); Q is mean target proximity; Phi(t)=Q(t) except terminal Phi=0",
        zero_demand_rule="invalid with no available peers; terminal correction retained without clipping",
    )


def target_arrival(window, reward, contract, parameters, context):
    """Reward each available peer's current presence, so departing loses its share."""
    if contract["mission"]["kind"] != "investigation":
        raise ValueError("target arrival requires investigation")
    if not context["phase3_eligible"]:
        return 0.0, False
    mission = contract["mission"]
    points = [node for node, active in zip(context["nodes"], context["node_available"]) if active]
    if not points:
        return 0.0, False
    arrived = sum(
        math.hypot(node[0] - mission["goal_x"], node[1] - mission["goal_y"])
        <= mission["team_radius_m"]
        for node in points
    )
    return arrived / len(points), True


def register_arrival(component_type, registry):
    registry["available_target_arrival_fraction_v1"] = component_type(
        "available_target_arrival_fraction_v1",
        target_arrival,
        (0.0, 1.0),
        ("nodes", "node_available"),
        context_fields=("nodes", "node_available", "phase3_eligible"),
        contract_fields=("mission",),
        context_builder=gated_context,
        formula="fraction of currently available peers within the horizontal team target radius; earned each decision while present; departures lose their share",
        zero_demand_rule="target geometry does not depend on offered traffic; invalid with no available peers or forced/mixed event window",
    )


def register(component_type, registry):
    register_primitives(component_type, registry)
    register_signal(component_type, registry)
    register_arrival(component_type, registry)
