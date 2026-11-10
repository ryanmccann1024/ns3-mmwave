# Mission reward formulas {#mesh_sim_rl_mission_rewards}

This reference gives the implemented formulas used by the mission reward
families. It accompanies the [observation and reward catalog](@ref src_rl_policy_inputs).
The coefficients are experimental design choices, not established optimal
weights. Change them through explicit component parameters or component weights;
keep the resolved choice in the saved model identity.

## Measurements and units

All fractions below are clipped to [0,1] unless noted. Only currently available
peers contribute. Service excludes endpoints with no offered demand.

| Symbol | Definition |
| --- | --- |
| D | Delivered/offered traffic in the scored decision window; recovery uses surviving critical demand. |
| F | Mean of the lowest ceil(N/3) endpoint service ratios among N available demanded peers. |
| L | Mean of the lowest ceil(P/3) demanded-pair path signal scores, for P eligible pairs. |
| I | Largest horizontal minimum-spanning-tree edge / 150 m, clipped to one. This is geometric isolation, not a radio cutoff. |
| T | Mean available-peer actual XY distance / permitted XY distance in the decision window, each clipped to one. |
| B | Fraction of available control slots that actually contacted the field boundary. Being near it costs nothing. |
| J | Fraction of available control slots whose requested movement was rejected for peer separation. |
| A | Fraction of available peers within the horizontal target radius. |
| K | One when all available peers belong to the current radio-connected team; otherwise zero. |
| C | Measured connected outdoor coverage fraction. |
| Q | Half the mean plus half the minimum of exp(-e_i/100 m), where e_i is peer i's distance beyond the target radius. |
| P | Potential shaping: s(gamma Phi_now - Q_previous); Phi_now = Q except zero at the terminal decision. Default s=10, gamma=0.99. |

A widest path maximizes its weakest link SINR. A path with bottleneck b dB has
signal score sigmoid((b+6.7)/4), where sigmoid(x)=1/(1+exp(-x)); the implementation
clips the exponential argument to [-60,60] for numerical stability. L uses the
lowest third of demanded pairs. Whole-team support G instead uses the weakest
pair among all available peers; G=0 with fewer than two peers. Neither guarantees
sufficient capacity to deliver every offered flow.

## Individual shaping components

| Component | Calculation and rules |
| --- | --- |
| `available_team_closeness_v1` | clip(1 - mean available-peer XY pair distance / field diagonal,0,1); invalid with fewer than two available peers or during a forced prefix. |
| `demanded_path_sinr_margin_v1` | Mean eligible demanded-pair sigmoid signal score. A bottleneck at least 10 dB scores one; relevant delivery at least 0.95 also returns one. Invalid without an available demanded pair. Recovery pairs matching ground/vehicle suffixes; coverage/jamming use available demanded pairs. |
| `target_proximity_potential_v1` | q_now + s(gamma Phi_now - q_previous), with q the mean clip(1 - excess target distance / field diagonal,0,1). Defaults s=50 and gamma=0.99. Terminal Phi_now=0; the correction is not clipped away. |
| `available_target_arrival_fraction_v1` | A measured after the decision; departure removes that peer's contribution. No traffic requirement. |

The field diagonal is sqrt(width^2+height^2); a 400 m square has diagonal
565.7 m. It is a geometric normalizer, not a weight or an allowed radio range.
For example, peers 100 m apart in that square have closeness 1-100/565.7=0.823.

## Fixed coordinated formulas

Every row also subtracts 0.02 B + 0.02 J.

| Mission | Reward before boundary/rejection costs |
| --- | --- |
| Recovery/jamming | 0.50 D + 0.40 F + 0.10 L - 0.05 I - 0.02 T |
| Investigation | 0.45 Q + 0.45 A + 0.10 K + P - 0.02 T |
| Coverage | 0.85 C + 0.15 F - 0.02 T |

The larger task/service coefficients make those measurements the main objective.
Small travel/contact coefficients are regularizers. They are starting designs;
their effectiveness depends on the scenario and must be compared experimentally.

## Measured-state priorities

Adaptive rewards choose weights from measured state, never future event times.
Every row below also subtracts 0.02 B + 0.02 J.

| Mission/state | Reward before boundary/rejection costs |
| --- | --- |
| Service: restore | (0.60-l) D + 0.40 F + l L - 0.05 I - 0.002 T; l=0.10+0.20(1-current active-pair LOS fraction) |
| Service: settle | 0.65 D + 0.35 F - 0.05 I - 0.05 T |
| Investigation: approach | 0.70 Q + 0.30 A + P - 0.002 T |
| Investigation: assemble/dwell | 0.10 Q + 0.70 A + 0.20 K + P - 0.01 T |
| Investigation: settle | 0.10 Q + 0.60 A + 0.20 K + 0.10 D + P - 0.05 T |
| Coverage: expand | 0.95 C + 0.05 F - 0.002 T |
| Coverage: settle | 0.75 C + 0.25 F - 0.05 T |

Service settles after 30 s with D>=0.90 and worst-peer service>=0.80. It falls
back after 5 s below D=0.85 or worst-peer service=0.70, or immediately below
D=0.50 or worst-peer service=0.20. Coverage additionally requires its saved area
target and relapses below target-0.02. Investigation assembles when every
available peer is inside the target radius, settles after 30 s of connected
arrival, and falls back after a 5 s loss. A peer more than 10 m beyond the target
radius immediately returns the controller to approach. Forced/ineligible windows reset dwell.

## Radio and sufficient-area variants

`coordinated_service_bridge_v1` replaces the geometric cost 0.05 I with
team_penalty(1-G), using the adaptive service formula above. The default team
penalty is 0.05; the supported explicit range is [0,1].
`coordinated_coverage_sufficient_v1` replaces C with min(C,coverage_goal) in the
adaptive coverage formula. Coverage_goal defaults to 0.9 and may be explicitly
set in [0.01,1]. This rewards attaining sufficient area rather than continuing
to maximize raw area. These substitutions do not add an extra clustering term.

## Source and verification

Source owners: `scripts/rl/env/rewards/{shaping,coordination,radio}.py` and
`env/state/{coordination,measurements}.py`. The registry owns resolved parameter
ranges and schema text. Tests in `scripts/rl/tests/env/` verify boundary cases,
arrival/departure, potential telescoping, low-tail measurements and state
transitions using synthetic decision facts and optional recorded trajectories.
Saved descriptor text and historical context keys stay frozen for compatibility.
