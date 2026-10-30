# RL in Mesh-Sim {#mesh_sim_rl_start}

[TOC]

What reinforcement learning does in Mesh-Sim, how its two processes fit
together, the terms the RL pages use, and the path through the guide.

## 1\. Before you start

- You finished \ref mesh_sim_first_run "Your first run", so you can build and
  run the simulator and you know what a scenario, a tick and a seed are.
- You set up the Python environment: `python3 scripts/rl/bootstrap_venv.py`
  (\ref readme_python_environment "Python environment"). Training needs
  `stable_baselines3`, `sb3_contrib` and `torch`, which it installs.
- RL tools run from `scratch/mesh-sim/` as `.venv/bin/python -m scripts.rl.<tool>`.
  They take the built binary as `--sim-binary <BIN>` and never build it.

This page runs no commands.

## 2\. What RL does here

An RL **policy** moves some of a scenario's nodes during a run, to keep the
mesh connected and the traffic flowing. The simulator is the environment. At
every decision it tells the policy what the network looks like and which moves
are allowed. The policy picks one move per controlled node, and the simulator
applies those moves until the next decision.

You train the policy with MaskablePPO, then evaluate it on seeds it never saw,
next to simple **baselines** such as "never move". The comparison tells you
whether moving during the run paid off.

RL is opt-in. A scenario without an `[rl]` section, or a run without
`--rl-mode` or `[rl] enabled = true`, never starts the RL bridge.

## 3\. The two processes

\image html rl-architecture.svg "Every decision: the simulator sends a step message, the environment turns it into an observation and a reward, the policy picks an allowed move for each controlled node, and the action goes back to the simulator. Each episode starts a fresh simulator."

The C++ simulator and a Python program run side by side. They talk over the
simulator's stdin and stdout, one JSON line per message.

| | C++ simulator (`src/rl/`) | Python (`scripts/rl/`) |
|---|---|---|
| Runs | One process per episode; the bridge runs inside its tick loop | One process that starts a fresh simulator for each episode |
| Owns | Physics, movement, walls, which actions are valid (the **mask**), the built-in per-tick reward, the raw **facts** | What the policy sees (the **observation**), which reward it learns from, training, evaluation, comparison |
| Never does | Choose actions or build the policy's observation | Re-derive masks or move nodes |

The rule is strict: movement limits and action validity are decided once, in
C++. Python validates every message, turns the raw facts into the policy's
inputs, and sends back one integer per controlled node.

## 4\. Terms used in these pages

| Term | Meaning |
|---|---|
| **Controlled node** | A node the policy moves. Listed in `[rl] controlled_nodes`. Every other node follows its own mobility from `nodes.json`. |
| **Slot** | One position in the policy's fixed-length action, mask and observation. Each controlled node has one slot. Extra slots, up to `max_controlled_nodes`, are **padding** and always hold. |
| **Action** | One of five moves per slot: `0` west, `1` east, `2` south, `3` north, `4` hold. A **joint action** is one list with an entry per slot. |
| **Mask** | Five 0/1 flags per slot saying which moves are allowed right now. Hold is always allowed. |
| **Tick** | One simulated time step, `[scenario] tick_s`. Links, traffic and the per-tick reward are computed every tick. |
| **Decision** | A moment when the policy chooses a new joint action, every `decision_interval_s`. The ticks between two decisions are a **decision window**. |
| **Step reward** | The number the policy learns from after each decision: the mean of the window's per-tick rewards, or a weighted mix of Python reward components. |
| **Return** | The sum of an episode's step rewards. |
| **Facts** | The raw per-decision measurements the simulator sends: node positions and velocities, every link's SINR, capacity and LOS, and traffic sums over the window. |
| **Observation preset** | A named recipe that turns facts into the policy's input vector, for example `local_links_v1`. |
| **Contract** | The message and action format both sides agree on. The current one is `mesh_move_2d_v2`. |
| **Episode** | One complete simulator run from reset to the last tick. Training runs many episodes. |
| **Timestep** | One decision, as Stable-Baselines3 counts it. Training budgets are in timesteps. |
| **Warmup** | The first `warmup_s` seconds. Nodes move, but those ticks earn no reward and are not scored. |
| **Seed roles** | Training, model-selection and held-out seeds. They must not overlap, so held-out results measure episodes the policy never saw. |
| **Bundle** | A finished training run: its `train_manifest.json` plus the model file whose digest it records. Evaluation only loads verified bundles. |
| **Baseline** | A fixed policy evaluated next to the model: `hold`, `random_valid`, or a placement planner. |

## 5\. What you will do

Pages 2 to 7 are one tutorial on one scenario, `building-bypass-smoke`, and
share one output folder, `outputs/rl-tutorial/`. Do them in order. Every
number and figure on them comes from that run.

1. \subpage mesh_sim_rl_example "The example scenario": the scenario you will
   use throughout, drawn from above, with its `[rl]` section line by line.
2. \subpage mesh_sim_rl_how_it_works "How a decision works": ticks, windows,
   warmup, the observation, masks and walls, then one real decision traced.
3. \subpage mesh_sim_rl_configure "Configure an RL scenario": every `[rl]`
   setting, observation presets, reward components with formulas, and the
   pre-flight check.
4. \subpage mesh_sim_rl_train "Train a policy": train for 8,192 decisions and
   watch it learn.
5. \subpage mesh_sim_rl_read_training "Read a training run": every file the
   run wrote, the manifest, and what the trained policy actually does.
6. \subpage mesh_sim_rl_evaluate "Evaluate and compare": the model and the
   baselines on held-out seeds, paired statistics, and placement baselines.
7. \subpage mesh_sim_rl_assumptions "Every assumption": every assumption RL
   makes, where it lives in the code, and what it does to your results.
8. \subpage mesh_sim_rl_experiments "Experiments and operations": run a
   batch of trainings, checks and operations with
   `scripts/rl/run-experiments.sh`, read and resume it, then benchmark, tune
   and use a cluster.
9. \subpage mesh_sim_rl_batch_reference "Batch experiment reference": every
   batch field, path rule, task state, operation protocol, schedule, selection
   rule and flag, and the replacements for the retired campaign commands.
10. \subpage mesh_sim_rl_code_map "Where the RL code lives": what each C++ and
    Python module owns, and how a call flows through them.
11. \subpage mesh_sim_rl_extend "Change or extend RL": add a reward component,
    an observation preset, a policy, a metric or a PPO setting.
12. \subpage mesh_sim_rl_add_algorithm "Add an RL algorithm": plug in another
    Stable-Baselines3 algorithm or write your own, with a worked example.

Pages 8 to 12 stand alone once you have done the tutorial.

## 6\. Going further

- \ref src_rl "src/rl": the wire contract, field by field.
- \ref scripts_rl "scripts/rl": every command-line flag and output file.
- \ref mesh_sim_placement_start "Placement baselines": the planners that the
  model is compared against on page 6.

Next: \ref mesh_sim_rl_example "The example scenario"
