"""Mission service, maintenance, progress, and measured approach/response/settling terms."""

import math


def register_service_terms(component_type, registry, movement_context):
    def component(name, calculation, formula, bounds=(0.0, 1.0), movement=False, tunable=None):
        registry[name] = component_type(
            name,
            calculation,
            bounds,
            ("mission_state",),
            context_fields=("mission_state", "mission")
            + (("travel_fraction",) if movement else ()),
            contract_fields=("mission",),
            formula=formula,
            context_builder=movement_context if movement else None,
            tunable=tunable or {},
        )

    def field(key):
        return lambda window, reward, contract, parameters, context: (
            context["mission_state"][key],
            True,
        )

    def service_floor(window, reward, contract, parameters, context):
        value = context["worst_node_delivery_fraction"]
        floor = parameters["floor"]
        return (max(0.0, floor - value) / floor, True) if value is not None else (0.0, False)

    registry["weak_service_deficit"] = component_type(
        "weak_service_deficit",
        service_floor,
        (0.0, 1.0),
        ("node_service",),
        context_fields=("worst_node_delivery_fraction",),
        context_builder=movement_context,
        tunable={"floor": (0.8, 0.0, 1.0)},
        formula="max(0,{floor:g}-worst_service)/{floor:g}",
    )

    def progress(window, reward, contract, parameters, context):
        m, s = contract["mission"], context["mission_state"]
        previous = -s["previous_distance_m"] / m["progress_distance_scale_m"]
        current = 0.0 if s["done"] else -s["distance_m"] / m["progress_distance_scale_m"]
        return parameters["gamma"] * current - previous, True

    component(
        "goal_progress",
        progress,
        "gamma*Phi(current)-Phi(previous); Phi=-distance/100m; terminal Phi=0",
        bounds=(None, None),
        tunable={"gamma": (0.995, 0.0, 1.0)},
    )
    component(
        "goal_coverage",
        lambda w, r, c, p, x: (x["mission"]["goal_coverage_fraction"], True),
        "outdoor connected-core coverage inside goal region",
    )
    component(
        "connected_arrival",
        field("connected_arrival"),
        "1 while investigator is inside arrival radius and in a core of at least two peers",
    )
    component(
        "investigator_disconnected",
        lambda w, r, c, p, x: (not x["mission_state"]["investigator_connected"], True),
        "1 while investigator is disconnected",
    )

    def bonus(key):
        return lambda w, r, c, p, x: (
            float(x["mission_state"][key] == x["mission_state"]["time_s"]),
            True,
        )

    component(
        "investigation_complete",
        bonus("investigation_completed_at_s"),
        "one-time bonus after connected arrival and local coverage persist for dwell_s",
    )
    for name, key in [
        ("survivor_delivery_ratio", "survivor_delivery"),
        ("survivor_fair_service", "survivor_fair_service"),
        ("survivor_worst_service", "survivor_worst_service"),
    ]:
        component(
            name,
            field(key),
            "service over flows whose endpoints are available; failed demand remains separately measured",
        )

    def deficit(key, target):
        def calc(w, r, c, p, x):
            s = x["mission_state"]
            if s["failure_at_s"] is None:
                return 0.0, True
            threshold = c["mission"][target] if target != "coverage_target" else s[target]
            return max(0.0, threshold - s[key]) / threshold if threshold > 0 else 0.0, True

        return calc

    component(
        "recovery_delivery_deficit",
        deficit("survivor_delivery", "recovery_delivery_target"),
        "post-failure max(0,target-survivor_delivery)/target",
    )

    def coverage_deficit(w, r, c, p, x):
        s = x["mission_state"]
        target = s["coverage_target"]
        return (
            max(0.0, target - x["coverage_fraction"]) / target
            if s["failure_at_s"] is not None and target > 0
            else 0.0
        ), True

    registry["recovery_coverage_deficit"] = component_type(
        "recovery_coverage_deficit",
        coverage_deficit,
        (0.0, 1.0),
        ("mission_state", "coverage"),
        context_fields=("mission_state", "coverage_fraction"),
        context_builder=movement_context,
        contract_fields=("mission",),
        formula="post-failure coverage deficit relative to 0.9 times pre-failure 60s mean",
    )
    component(
        "recovery_worst_service",
        lambda w, r, c, p, x: (
            x["mission_state"]["survivor_worst_service"]
            if x["mission_state"]["failure_at_s"] is not None
            else 0.0,
            True,
        ),
        "worst surviving-peer service after failure; zero before",
    )
    component(
        "recovery_complete",
        bonus("recovery_completed_at_s"),
        "one-time bonus after survivor delivery, coverage and worst service meet targets for dwell_s",
    )

    def movement(w, r, c, p, x):
        if x["travel_fraction"] is None:
            return 0.0, False
        return (0.02 + 0.08 * x["mission_state"]["previous_survivor_health"]) * x[
            "travel_fraction"
        ], True

    component(
        "recovery_movement_cost",
        movement,
        "(0.02+0.08*previous survivor health)*travel_fraction",
        bounds=(0.0, 0.1),
        movement=True,
    )

    def rejected(w, r, c, p, x):
        slots = set(x["safety"]["building_rejected_slots"]) | set(
            x["safety"]["peer_rejected_slots"]
        )
        return len(slots) / c["num_controlled"], True

    registry["collision_attempt_fraction"] = component_type(
        "collision_attempt_fraction",
        rejected,
        (0.0, 1.0),
        ("safety",),
        context_fields=("safety",),
        contract_fields=("navigation", "unsafe_separation_m", "avoid_node_collisions"),
        formula="unique slots with physically blocked wall or peer collision proposals / controlled peers",
    )
    component(
        "team_arrival_fraction",
        field("team_arrival_fraction"),
        "fraction of available peers inside team radius",
    )
    component(
        "team_disconnected",
        lambda w, r, c, p, x: (not x["mission_state"]["team_connected"], True),
        "1 while available team is split across connected components",
    )


def register_maintenance_terms(component_type, registry, movement_context):
    def component(
        name,
        calculation,
        formula,
        fields=("mission_state",),
        dependencies=("mission",),
        builder=None,
        tunable=None,
    ):
        registry[name] = component_type(
            name,
            calculation,
            (0.0, 1.0),
            fields,
            context_fields=fields,
            contract_fields=dependencies,
            context_builder=builder,
            formula=formula,
            tunable=tunable or {},
        )

    def active_quality(w, r, c, p, x):
        active = x["node_available"]
        index = 0
        values = []
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                link = x["links"][index]
                index += 1
                if active[i] and active[j]:
                    values.append(max(0.0, min(1.0, (link[0] + 20.0) / 60.0)))
        return (sum(values) / len(values), True) if values else (0.0, False)

    component(
        "active_sinr_quality_v1",
        active_quality,
        "mean clip((SINR + 20)/60,0,1) over available peer pairs; invalid links score 0",
        fields=("links", "node_available"),
        dependencies=("node_ids",),
    )

    component(
        "team_goal_proximity_v1",
        lambda w, r, c, p, x: (
            max(0.0, 1.0 - x["mission_state"]["distance_m"] / p["scale_m"]),
            True,
        ),
        "clip(1 - current team distance outside arrival zones / {scale_m:g},0,1)",
        tunable={"scale_m": (400.0, 1.0, 2000.0)},
    )

    def maintenance(w, r, c, p, x):
        s = x["mission_state"]
        m = c["mission"]
        return (
            float(
                s["failure_at_s"] is not None
                and s["survivor_delivery"] >= m["recovery_delivery_target"]
                and s["survivor_worst_service"] >= m["recovery_worst_target"]
            ),
            True,
        )

    component(
        "survivor_service_maintained_v1",
        maintenance,
        "1 at each post-failure decision meeting current survivor delivery and worst-peer targets; never latched",
    )

    component(
        "decision_travel_v1",
        lambda w, r, c, p, x: ((x["travel_fraction"] or 0.0), x["travel_fraction"] is not None),
        "mean physical movement / slot speed / decision interval; repeated blocked motion costs collision attempts instead",
        fields=("travel_fraction",),
        dependencies=("slot_speed_mps", "decision_interval_s"),
        builder=movement_context,
    )


def register_stage_terms(component_type, registry, movement_context):
    def add(
        name, calc, formula, fields, *, movement=False, parameters=None, dependencies=("mission",)
    ):
        registry[name] = component_type(
            name,
            calc,
            (0.0, 1.0),
            fields,
            context_fields=fields,
            context_builder=movement_context if movement else None,
            contract_fields=dependencies,
            formula=formula,
            tunable=parameters or {},
        )

    def approach(w, r, c, p, x):
        m = c["mission"]
        distances = [
            math.hypot(n[0] - m["goal_x"], n[1] - m["goal_y"])
            for n, active in zip(x["nodes"], x["node_available"])
            if active
        ]
        if not distances:
            return 0.0, False
        outside = [max(0.0, d - m["team_radius_m"]) for d in distances]
        # All peers matter, with extra emphasis on the slowest remaining peer.
        remaining = 0.5 * max(outside) + 0.5 * sum(outside) / len(outside)
        remaining += max(0.0, min(distances) - m["arrival_radius_m"])
        return min(1.0, remaining / p["scale_m"]), True

    add(
        "team_approach_cost_v1",
        approach,
        "clip((0.5*max outside team radius + 0.5*mean outside team radius + nearest outside inner radius)/{scale_m:g},0,1)",
        ("nodes", "node_available"),
        parameters={"scale_m": (400.0, 1.0, 2000.0)},
    )

    def setup(w, r, c, p, x):
        s = x["mission_state"]
        if not s["connected_arrival"]:
            return 0.0, True
        return (
            0.5
            + 0.25 * x["mission"]["goal_coverage_fraction"]
            + 0.25 * min(1.0, s["arrival_streak_s"] / c["mission"]["dwell_s"])
        ), True

    add(
        "investigation_setup_v1",
        setup,
        "zero before current connected team arrival; then 0.5 + 0.25*local coverage + 0.25*qualifying dwell fraction; falls back when arrival is lost",
        ("mission_state", "mission"),
    )
    add(
        "investigation_service_deficit_v1",
        lambda w, r, c, p, x: (
            max(0.0, p["floor"] - x["mission_state"]["survivor_delivery"]) / p["floor"],
            True,
        ),
        "max(0,{floor:g}-current service)/{floor:g}; small viability penalty during approach",
        ("mission_state",),
        parameters={"floor": (0.2, 0.01, 1.0)},
    )

    def deployment(w, r, c, p, x):
        if x["mission_state"]["failure_at_s"] is not None:
            return 0.0, True
        b = c["bounds"]
        diagonal = math.hypot(b["x_max"] - b["x_min"], b["y_max"] - b["y_min"])
        return min(1.0, x["origin_fraction"] * diagonal / p["scale_m"]), True

    add(
        "recovery_deployment_cost_v1",
        deployment,
        "before measured failure: clip(mean displacement from original deployment/{scale_m:g},0,1); after failure: zero",
        ("mission_state", "origin_fraction"),
        movement=True,
        parameters={"scale_m": (100.0, 1.0, 2000.0)},
        dependencies=("mission", "bounds", "slot_node_ids"),
    )

    def response(w, r, c, p, x):
        s = x["mission_state"]
        m = c["mission"]
        if s["failure_at_s"] is None:
            return 0.0, True
        deficits = [
            max(0.0, 1 - s["survivor_delivery"] / m["recovery_delivery_target"]),
            max(0.0, 1 - s["survivor_worst_service"] / m["recovery_worst_target"]),
        ]
        if s["coverage_target"] > 0:
            deficits.append(max(0.0, 1 - x["coverage_fraction"] / s["coverage_target"]))
        return max(deficits), True

    add(
        "recovery_response_deficit_v1",
        response,
        "after measured failure: maximum normalized deficit in survivor delivery, worst-peer service and retained geographic coverage; zero before failure",
        ("mission_state", "coverage_fraction"),
        movement=True,
    )

    def settle(w, r, c, p, x):
        deficit, _ = response(w, r, c, p, x)
        s = x["mission_state"]
        if s["failure_at_s"] is None or deficit > 0:
            return 0.0, True
        return 0.5 + 0.5 * min(1.0, s["recovery_streak_s"] / c["mission"]["dwell_s"]), True

    add(
        "recovery_settle_v1",
        settle,
        "only while current delivery, worst-peer service and geographic coverage meet recovery targets: 0.5 + 0.5*qualifying dwell fraction; falls back on service loss",
        ("mission_state", "coverage_fraction"),
        movement=True,
    )


def register_progress_terms(component_type, registry, movement_context):
    def add(name, calc, formula, fields, *, bounds=(0.0, 1.0), movement=False, tunable=None):
        registry[name] = component_type(
            name,
            calc,
            bounds,
            fields,
            context_fields=fields,
            context_builder=movement_context if movement else None,
            contract_fields=("mission",),
            formula=formula,
            tunable=tunable or {},
        )

    def health(x):
        s = x["mission_state"]
        return min(1.0, s["survivor_delivery"] / 0.9, s["survivor_worst_service"] / 0.8)

    def recovered(x):
        s = x["mission_state"]
        return (
            s["failure_at_s"] is not None
            and health(x) >= 1
            and x["coverage_fraction"] >= s["coverage_target"]
        )

    add(
        "team_distance_delta_v2",
        lambda w, r, c, p, x: (
            max(
                -1.0,
                min(
                    1.0,
                    (x["mission_state"]["previous_distance_m"] - x["mission_state"]["distance_m"])
                    / p["scale_m"],
                ),
            ),
            True,
        ),
        "clip((previous measured team distance - current measured team distance)/{scale_m:g},-1,1); no terminal distance reset",
        ("mission_state",),
        bounds=(-1.0, 1.0),
        tunable={"scale_m": (5.0, 0.0, 100.0)},
    )
    add(
        "service_gated_coverage_v2",
        lambda w, r, c, p, x: (x["coverage_fraction"] * health(x), True),
        "outdoor connected coverage * min(1, survivor delivery/0.9, worst survivor service/0.8)",
        ("coverage_fraction", "mission_state"),
        movement=True,
    )

    def coverage_ready(x, p):
        return health(x) >= 1 and x["coverage_fraction"] >= p["coverage_target"]

    add(
        "coverage_target_maintained_v2",
        lambda w, r, c, p, x: (float(coverage_ready(x, p)), True),
        "1 while coverage >= {coverage_target:g}, delivery >= 0.9 and worst service >= 0.8; otherwise 0",
        ("coverage_fraction", "mission_state"),
        movement=True,
        tunable={"coverage_target": (0.85, 0.0, 1.0)},
    )

    def travel(ready):
        def calc(w, r, c, p, x):
            value = x["travel_fraction"]
            return (
                (p["moving_cost"] if ready(x, p) else p["approach_cost"]) * (value or 0.0),
                value is not None,
            )

        return calc

    parameters = {"approach_cost": (0.01, 0.0, 1.0), "moving_cost": (0.2, 0.0, 1.0)}
    for name, ready, fields, extra, description in (
        (
            "coverage_settle_cost_v2",
            coverage_ready,
            ("coverage_fraction", "mission_state", "travel_fraction"),
            {"coverage_target": (0.85, 0.0, 1.0)},
            "coverage and service targets hold",
        ),
        (
            "investigation_settle_cost_v2",
            lambda x, p: x["mission_state"]["connected_arrival"],
            ("mission_state", "travel_fraction"),
            {},
            "current connected team arrival holds",
        ),
        (
            "recovery_settle_cost_v2",
            lambda x, p: recovered(x),
            ("coverage_fraction", "mission_state", "travel_fraction"),
            {},
            "current recovery service and coverage targets hold",
        ),
        (
            "service_settle_cost_v2",
            lambda x, p: health(x) >= 1,
            ("mission_state", "travel_fraction"),
            {},
            "current delivery and worst-service targets hold",
        ),
    ):
        add(
            name,
            travel(ready),
            "actual movement fraction * ({moving_cost:g} when "
            + description
            + "; {approach_cost:g} otherwise)",
            fields,
            movement=True,
            tunable={**parameters, **extra},
        )

    add(
        "post_failure_service_v2",
        lambda w, r, c, p, x: (
            (
                0.5 * x["mission_state"]["survivor_delivery"]
                + 0.5 * x["mission_state"]["survivor_worst_service"]
            )
            if x["mission_state"]["failure_at_s"] is not None
            else 0.0,
            True,
        ),
        "after measured failure: 0.5*current survivor delivery + 0.5*current worst survivor service; zero before",
        ("mission_state",),
    )

    def quality(w, r, c, p, x):
        if x["mission_state"]["failure_at_s"] is None:
            return 0.0, True
        return registry["active_sinr_quality_v1"].value(w, r, c, x)

    add(
        "post_failure_sinr_v2",
        quality,
        "after measured failure: mean available-pair SINR quality clipped from -20 to 40 dB; zero before",
        ("mission_state", "links", "node_available"),
    )

    def coverage_deficit(w, r, c, p, x):
        s = x["mission_state"]
        target = s["coverage_target"]
        return (
            max(0.0, 1 - x["coverage_fraction"] / target)
            if s["failure_at_s"] is not None and target > 0
            else 0.0
        ), True

    add(
        "post_failure_coverage_deficit_v2",
        coverage_deficit,
        "after measured failure: max(0,1-current outdoor coverage/measured recovery coverage target); zero for no target",
        ("mission_state", "coverage_fraction"),
        movement=True,
    )


def register(component_type, registry, movement_context):
    register_service_terms(component_type, registry, movement_context)
    register_maintenance_terms(component_type, registry, movement_context)
    register_stage_terms(component_type, registry, movement_context)
    register_progress_terms(component_type, registry, movement_context)
