"""Generate every figure in the RL guide (docs/rl/) from one set of real runs.

Figures (all written to docs/diagrams/):

rl-architecture.svg   the two processes and the JSON bridge between them
rl-example-map.svg    the example scenario from above: bounds, building, shadow
rl-timing.svg         ticks, decision windows and warmup, from real telemetry
rl-observation.svg    the local_links_v1 vector at two real decisions
rl-trace.svg          one held-out episode tick by tick: SINR, reward, position
rl-learning-curve.svg training returns, model-selection returns and entropy
rl-trajectories.svg   where node-b went: trained policy, baselines, early/late training
rl-eval-metrics.svg   per-policy means with 95% intervals on the held-out seeds
rl-paired.svg         the paired per-seed differences compare reports
rl-custom.svg         the hand-written Q-learning example learning
rl-sequence.svg       one episode as a sequence of messages
rl-code-flow.svg      which file calls which, for train, evaluate and compare

The runs use only tracked scenarios: inputs/baselines/building-bypass-smoke
(training seed 1, model-selection seed 2, held-out seeds 11-15) and
inputs/baselines/channel-scored-example (placement policies). Run from docs/
with the project venv. Pass an already built binary to delete and redo every
run under ../outputs/rl-tutorial/ (about 10 minutes), or nothing to redraw the
figures from the existing runs:

    ../.venv/bin/python diagrams/rl-tutorial.py --sim-binary <BIN>
    ../.venv/bin/python diagrams/rl-tutorial.py

The commands it runs are the ones printed on the guide's pages; their stdout
and stderr go to ../outputs/rl-tutorial/logs/.
"""
import argparse
import csv
import glob
import json
import math
import os
import shutil
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # scratch/mesh-sim
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "outputs", "rl-tutorial")
EXAMPLE = "inputs/baselines/building-bypass-smoke"
PLACEMENT = "inputs/baselines/channel-scored-example"
PY = os.path.join(ROOT, ".venv", "bin", "python")
MATRIX = "inputs/experiments/bypass-smoke-matrix.json"

INK, MUTED, GRID, EDGE = "#1f2d3a", "#5b6b7b", "#e6e9ec", "#c9cfd5"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
PALE_BLUE, PALE_RED, NEUTRAL = "#d6e6f2", "#f3d9d6", "#eef0f2"
# Each policy has a color, a marker and a line style, so no pair is told apart by color alone.
POLICY = {"model": (BLUE, "o", "-", "trained model"),
          "hold": (INK, "s", (0, (1, 2)), "hold"),
          "random_valid": (AMBER, "^", (0, (5, 3)), "random_valid"),
          "qtable": (GREEN, "D", "-.", "qtable (custom)")}

plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
plt.rcParams["svg.fonttype"] = "none"


# ---------------------------------------------------------------- running

def commands(sim):
    """The guide's commands in order: (log name, argv, expected exit codes)."""
    run_ini = f"{EXAMPLE}/run.ini"
    out = "outputs/rl-tutorial"
    m = [PY, "-m"]
    return [
        ("validate", m + ["scripts.rl.validate_config", "--sim-binary", sim, "--run-config", run_ini,
                          "--output-dir", f"{out}/preflight", "--launch", "--json"], (0,)),
        ("train", m + ["scripts.rl.train", "--sim-binary", sim, "--run-config", run_ini,
                       "--output-dir", f"{out}/train", "m-ppo", "--total-timesteps", "8192",
                       "--n-steps", "256", "--seed", "1", "--checkpoint-every-steps", "2048",
                       "--keep-checkpoints", "2", "--eval-every-steps", "256",
                       "--eval-episodes", "1", "--eval-seed", "2"], (0,)),
        ("inspect", m + ["scripts.rl.inspect_model", "--run-dir", f"{out}/train"], (0,)),
        ("evaluate", m + ["scripts.rl.evaluate", "--sim-binary", sim, "--run-dir", f"{out}/train",
                          "--output-dir", f"{out}/eval", "--seeds", "11-15",
                          "--policies", "model,hold,random_valid"], (0,)),
        ("overlap", m + ["scripts.rl.evaluate", "--sim-binary", sim, "--run-dir", f"{out}/train",
                         "--output-dir", f"{out}/eval-overlap", "--seeds", "1,11",
                         "--policies", "model,hold"], (1,)),
        ("compare", m + ["scripts.rl.compare", "--eval-dirs", f"{out}/eval",
                         "--output-dir", f"{out}/compare"], (0,)),
        ("placement-train", m + ["scripts.rl.train", "--sim-binary", sim, "--run-config",
                                 f"{PLACEMENT}/run.ini", "--output-dir", f"{out}/placement/train",
                                 "--verbose", "0", "m-ppo", "--seed", "101", "--total-timesteps",
                                 "256", "--n-steps", "64", "--eval-every-steps", "128",
                                 "--eval-seed", "301"], (0,)),
        ("placement-evaluate", m + ["scripts.rl.evaluate", "--run-dir", f"{out}/placement/train",
                                    "--model", "best", "--sim-binary", sim, "--run-config",
                                    f"{PLACEMENT}/run-zero-cost.ini", "--allow-different-scenario",
                                    "--output-dir", f"{out}/placement/zero-cost/eval",
                                    "--seeds", "801,802,803",
                                    "--policies", "model,hold,geometric,optimization"], (0,)),
        ("placement-compare", m + ["scripts.rl.compare", "--eval-dirs",
                                   f"{out}/placement/zero-cost/eval", "--output-dir",
                                   f"{out}/placement/zero-cost/compare"], (1,)),
        ("custom", [PY, f"{out}/custom-algorithm/qtable.py", "--sim-binary", sim,
                    "--steps", "600"], (0,)),
        ("custom-as-model", [PY, f"{out}/custom-algorithm/qtable.py", "--sim-binary", sim,
                             "--load", f"{out}/custom-algorithm/qtable.json", "--name", "model"],
         (0,)),
        ("custom-compare", m + ["scripts.rl.compare", "--eval-dirs",
                                f"{out}/custom-algorithm/eval-as-model", "--output-dir",
                                f"{out}/custom-algorithm/compare"], (0,)),
        ("unmasked", [PY, f"{out}/custom-algorithm/unmasked.py", sim], (0,)),
        ("extend-examples", [PY, f"{out}/extend-examples/check.py"], (0,)),
        ("matrix-plan", m + ["scripts.rl.experiment", "plan", "--matrix", MATRIX, "--output-root",
                             f"{out}/matrix", "--sim-binary", sim, "--rows", "local-delivery"], (0,)),
        ("matrix-run", m + ["scripts.rl.experiment", "run", "--matrix", MATRIX, "--output-root",
                            f"{out}/matrix", "--sim-binary", sim, "--rows", "local-delivery"], (0,)),
        ("matrix-status", m + ["scripts.rl.experiment", "status", "--output-root",
                               f"{out}/matrix"], (0,)),
        ("bench-plan", m + ["scripts.rl.experiment", "plan", "--matrix", MATRIX, "--output-root",
                            f"{out}/bench", "--sim-binary", sim, "--rows", "local-delivery"], (0,)),
        ("bench-run", m + ["scripts.rl.ops.benchmark", "run", "--output-root", f"{out}/bench",
                           "--task-index", "0"], (0,)),
        ("bench-estimate", m + ["scripts.rl.ops.benchmark", "estimate", "--benchmark",
                                f"{out}/bench/benchmark/task-0000.json", "--target-matrix", MATRIX,
                                "--safety-factor", "2.0", "--output",
                                f"{out}/bench/benchmark/estimate.json"], (0,)),
        ("tune-dry-run", m + ["scripts.rl.ops.tune", "--study",
                              "inputs/experiments/bypass-smoke-study.json", "--output-root",
                              f"{out}/tune", "--sim-binary", sim, "--dry-run"], (0,)),
    ]


def capture(sim):
    """Delete the previous runs (keeping the two hand-written example scripts) and redo them."""
    sources = [os.path.join(OUT, "custom-algorithm", "qtable.py"),
               os.path.join(OUT, "custom-algorithm", "unmasked.py"),
               os.path.join(OUT, "extend-examples", "check.py")]
    kept = {path: open(path).read() for path in sources}
    shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "logs"))
    for path, text in kept.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
    env = dict(os.environ, PYTHONPATH=ROOT)
    for name, argv, ok in commands(os.path.abspath(sim)):
        with open(os.path.join(OUT, "logs", name + ".log"), "w") as log:
            code = subprocess.run(argv, cwd=ROOT, env=env, stdout=log,
                                  stderr=subprocess.STDOUT).returncode
        print(f"{name}: exit {code}")
        if code not in ok:
            raise SystemExit(f"{name} exited {code}; expected {ok}")


# ---------------------------------------------------------------- reading

def read_csv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(line for line in fh if not line.startswith("#")))


def read_steps(episode_dir):
    with open(os.path.join(episode_dir, "steps.jsonl")) as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    return lines[0]["contract"], lines[1:]


def eval_episode(eval_dir, policy, seed):
    manifest = json.load(open(os.path.join(eval_dir, "eval_manifest.json")))
    for episode in manifest["policies"][policy]["episodes"]:
        if episode["seed"] == seed:
            return episode["episode_dir"] if os.path.isabs(episode["episode_dir"]) else \
                os.path.join(ROOT, episode["episode_dir"])
    raise KeyError((policy, seed))


def path_of(episode_dir, node_index=1):
    seed_dir = glob.glob(os.path.join(episode_dir, "seed-*"))[0]
    rows = [r for r in read_csv(os.path.join(seed_dir, "positions.csv"))
            if int(r["node_id"]) == node_index]
    links = {round(float(r["time_s"]), 3): r["condition"] == "LOS"
             for r in read_csv(os.path.join(seed_dir, "links.csv"))}
    return ([float(r["x"]) for r in rows], [float(r["y"]) for r in rows],
            [links[round(float(r["time_s"]), 3)] for r in rows])


def t95(n):
    from scripts.stats import t_critical_95
    return t_critical_95(n)


# ---------------------------------------------------------------- styling

def style(ax, title, ylabel=None, xlabel=None):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK, pad=8)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10, color=MUTED)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(EDGE)
    ax.tick_params(colors=MUTED, labelsize=9)


def style_map(ax, title):
    style(ax, title, "y (m)", "x (m)")
    ax.set_aspect("equal")
    ax.set_xlim(-12, 262)
    ax.set_ylim(-112, 112)


def draw_scene(ax, shadow=True):
    """Bounds, building and the building's radio shadow as seen from node-a."""
    ax.add_patch(Rectangle((0, -100), 250, 200, fill=False, ec=MUTED, lw=1.1, ls=(0, (4, 3))))
    if shadow:
        edge = 20.0 * 250.0 / 90.0
        ax.add_patch(Polygon([(90, 20), (250, edge), (250, -edge), (90, -20)], closed=True,
                             fc=NEUTRAL, ec="none", zorder=0))
        for sign in (1, -1):
            ax.plot([0, 250], [0, sign * edge], color=EDGE, lw=0.9, zorder=1)
    ax.add_patch(Rectangle((90, -20), 20, 40, fc="#9aa5b1", ec=INK, lw=0.8, zorder=3))


def node(ax, x, y, label, marker="s", color=INK, offset=(0, 10), ha="center"):
    ax.scatter([x], [y], s=90, marker=marker, color=color, edgecolor="white", lw=1.4, zorder=6)
    ax.annotate(label, (x, y), xytext=offset, textcoords="offset points", ha=ha, fontsize=9.5,
                color=INK, fontweight="bold", zorder=7,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))


def save(fig, name):
    path = os.path.join(HERE, name)
    fig.savefig(path, format="svg", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {os.path.relpath(path, ROOT)}")


def box(ax, x, y, w, h, title, lines=(), fc="white", ec=EDGE, title_color=INK, size=10):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=fc, ec=ec, lw=1.2, zorder=2))
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=size,
            fontweight="bold", color=title_color, zorder=3)
    for k, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 0.62 - 0.36 * k, line, ha="center", va="top", fontsize=8.6,
                color=MUTED, zorder=3)


def arrow(ax, a, b, color=INK, style="-|>", lw=1.2, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=12, color=color, lw=lw,
                                 linestyle=ls, connectionstyle=f"arc3,rad={rad}", zorder=4))


# ---------------------------------------------------------------- schematic figures

def figure_architecture():
    fig, ax = plt.subplots(figsize=(14, 5.4))
    ax.set_xlim(0, 28)
    ax.set_ylim(0, 10.8)
    ax.axis("off")
    # the two processes
    for x0, w, fc, label in ((0.2, 8.6, PALE_BLUE, "Simulator process: one per episode"),
                             (13.8, 14.0, NEUTRAL, "Python process: train, evaluate or your own loop")):
        ax.add_patch(FancyBboxPatch((x0, 0.3), w, 9.5, boxstyle="round,pad=0,rounding_size=0.25",
                                    fc=fc, ec="none", zorder=0))
        ax.text(x0 + 0.45, 9.35, label, fontsize=13, fontweight="bold", color=INK, va="top")

    def card(x, w, title, where, lines, ec, bullets=True):
        ax.add_patch(FancyBboxPatch((x, 1.0), w, 7.2, boxstyle="round,pad=0.02,rounding_size=0.2",
                                    fc="white", ec=ec, lw=1.8, zorder=2))
        ax.text(x + w / 2, 7.45, title, ha="center", va="center", fontsize=15.5, fontweight="bold",
                color=INK, zorder=3)
        ax.text(x + w / 2, 6.55, where, ha="center", va="center", fontsize=11.5, color=MUTED,
                family="monospace", zorder=3)
        for k, line in enumerate(lines):
            y = 5.3 - 1.15 * k if bullets else 4.9 - 0.75 * k
            ax.text(x + 0.45 if bullets else x + w / 2, y, ("\u2022  " if bullets else "") + line,
                    ha="left" if bullets else "center", va="center", fontsize=12.5, color=INK, zorder=3)

    card(0.6, 7.8, "Simulator (C++)", "sim.cc, src/rl/",
         ["Moves the nodes each tick", "Evaluates every link", "Checks which moves are allowed",
          "Sums the reward per decision"], BLUE)
    card(14.3, 6.5, "Environment", "scripts/rl/env/",
         ["Validates each message", "Builds the observation", "Computes the step reward",
          "Saves the episode files"], MUTED)
    card(23.4, 4.0, "Policy", "MaskablePPO",
         ["Picks one allowed", "move for each", "controlled node,", "every decision"], MUTED, bullets=False)

    def link(x0, x1, y_top, top, y_bottom, bottom, size=13):
        arrow(ax, (x0, y_top), (x1, y_top), lw=2)
        arrow(ax, (x1, y_bottom), (x0, y_bottom), lw=2)
        mid = (x0 + x1) / 2
        ax.text(mid, y_top + 0.3, top, ha="center", va="bottom", fontsize=size, color=INK, linespacing=1.3)
        ax.text(mid, y_bottom - 0.3, bottom, ha="center", va="top", fontsize=size, color=INK, linespacing=1.3)

    link(8.4, 14.3, 5.6, "step message\nfacts, mask, reward", 3.2, "action\none move per node")
    ax.text(11.35, 9.35, "JSON lines over\nstdout and stdin", ha="center", va="top", fontsize=12,
            color=MUTED, style="italic", linespacing=1.3)
    link(20.8, 23.4, 5.6, "obs, mask,\nreward", 3.2, "action", size=12)
    save(fig, "rl-architecture.svg")


def figure_sequence():
    steps = [
        ("msg", "agent", "env", "reset()", None, False),
        ("msg", "env", "sim", "start a new process", "--rl-mode --seed=S --output-dir=episode-NNNN", False),
        ("msg", "sim", "env", "init line (once)", "contract, slots, obs_dim, mask_dim, bounds, speeds", True),
        ("note", "sim", "tick 0: evaluate links, route,\nadd tick 0 to the window"),
        ("msg", "sim", "env", "step line, decision 0", "obs, mask, facts; its reward is not a learning step", True),
        ("note", "env", "validate; build the preset's\nobservation from facts"),
        ("msg", "env", "agent", "obs, info", None, True),
        ("msg", "agent", "env", "action_masks()", "bool array, 5 entries per slot", False),
        ("msg", "agent", "env", "step(action)", "one integer 0-4 per slot", False),
        ("msg", "env", "sim", "{\"action\":[a]} on stdin", None, False),
        ("note", "sim", "revalidate: a masked or padded move\nbecomes hold; set velocity"),
        ("note", "sim", "ticks 1..k: clamp at walls, move,\nevaluate links, route, add reward"),
        ("msg", "sim", "env", "step line, decision 1", "window mean reward, mask, facts, done=false", True),
        ("note", "env", "observation; reward = the C++ mean\nor the weighted components"),
        ("msg", "env", "agent", "obs, reward, terminated, truncated, info", None, True),
        ("gap", "... repeat for every decision ..."),
        ("msg", "sim", "env", "last step line", "done=true; the simulator reads no action", True),
        ("note", "env", "stop the process;\nepisode status completed"),
        ("msg", "env", "agent", "terminated=True", None, True),
    ]
    height = {"msg": 1.45, "note": 1.45, "gap": 1.0}
    total = sum(height[s[0]] for s in steps)
    top = total + 1.6
    fig, ax = plt.subplots(figsize=(11.5, 0.42 * (top + 3.2)))
    ax.set_xlim(0, 24)
    ax.set_ylim(-0.6, top + 2.6)
    ax.axis("off")
    lanes = {"agent": 3.5, "env": 11.5, "sim": 19.8}
    heads = {"agent": "Your algorithm", "env": "MeshRlEnv", "sim": "Simulator process"}
    subs = {"agent": "MaskablePPO, a Q-table, ...", "env": "scripts/rl/env/mesh_env.py",
            "sim": "sim.cc + src/rl/rl-bridge.cc"}
    for key, x in lanes.items():
        box(ax, x - 3.1, top + 0.4, 6.2, 2.0, heads[key], [subs[key]],
            fc={"agent": "white", "env": NEUTRAL, "sim": PALE_BLUE}[key],
            ec={"agent": EDGE, "env": MUTED, "sim": BLUE}[key])
        ax.plot([x, x], [0.8, top + 0.4], color=EDGE, lw=1.2, ls=(0, (4, 3)), zorder=1)
    y = top - 0.3
    for s in steps:
        kind = s[0]
        y -= height[kind]
        if kind == "msg":
            _, src, dst, text, sub, dashed = s
            x0, x1 = lanes[src], lanes[dst]
            arrow(ax, (x0, y + 0.55), (x1, y + 0.55), ls="--" if dashed else "-")
            mid = (x0 + x1) / 2
            ax.text(mid, y + 0.72, text, ha="center", va="bottom", fontsize=9, color=INK,
                    fontweight="bold")
            if sub:
                ax.text(mid, y + 0.38, sub, ha="center", va="top", fontsize=8.3, color=MUTED)
        elif kind == "note":
            _, lane, text = s
            w = 6.8
            ax.add_patch(FancyBboxPatch((lanes[lane] - w / 2, y + 0.05), w, 1.1,
                                        boxstyle="round,pad=0.02,rounding_size=0.1",
                                        fc="white", ec=EDGE, lw=1.0, zorder=5))
            lines = text.split("\n")
            for k, line in enumerate(lines):
                ax.text(lanes[lane], y + 0.6 + (len(lines) - 1) * 0.2 - k * 0.4, line,
                        ha="center", va="center", fontsize=8.3, color=INK, zorder=6)
        else:
            ax.text(lanes["env"], y + 0.45, s[1], ha="center", fontsize=9, color=MUTED,
                    style="italic")
    ax.text(0.2, -0.2, "Solid arrows are calls or writes; dashed arrows are replies or reads. "
            "truncated is always False: an episode ends only when the simulator says done.",
            fontsize=9, color=MUTED)
    save(fig, "rl-sequence.svg")


def figure_code_flow():
    fig, ax = plt.subplots(figsize=(11.5, 7.8))
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 16.4)
    ax.axis("off")
    w, h = 5.2, 1.5
    tops = {"train": 1.2, "eval": 7.4, "compare": 13.6}
    for key, x in tops.items():
        box(ax, x, 14.4, w, h, {"train": "train.py", "eval": "evaluate.py",
                                "compare": "compare.py"}[key], ["scripts/rl/"], ec=INK)
    # train: train.py -> training.py -> (mask_ppo.py -> env) and (training_artifacts.py)
    box(ax, 1.2, 12.2, w, h, "policy/training.py", ["train_mppo: builds envs, callbacks"], size=9.5)
    box(ax, 1.2, 9.6, w, h, "agents/mask_ppo.py", ["MaskablePPO.learn()"], size=9.5)
    box(ax, 1.2, 7.0, 4.6, h, "policy/training_artifacts.py", ["writes train_manifest.json"], size=9.5)
    arrow(ax, (3.8, 14.4), (3.8, 13.7))
    arrow(ax, (3.8, 12.2), (3.8, 11.1))
    arrow(ax, (1.2, 12.7), (1.2, 7.9), rad=0.35)
    ax.text(0.1, 10.3, "then", fontsize=8.5, color=MUTED, ha="left", va="center")
    # evaluate
    box(ax, 7.4, 12.2, w, h, "policy/bundle.py", ["manifest, digest, seed roles"], size=9.5)
    box(ax, 7.4, 9.6, w, h, "policy/compat.py", ["four ordered checks"], size=9.5)
    box(ax, 7.4, 7.0, w, h, "policy/evaluate.py", ["run_episode for each seed"], size=9.5)
    for y0, y1 in ((14.4, 13.7), (12.2, 11.1), (9.6, 8.5)):
        arrow(ax, (10.0, y0), (10.0, y1))
    # compare
    box(ax, 13.6, 12.2, w, h, "policy/compare_inputs.py", ["loads eval_manifest.json"], size=9.5)
    box(ax, 13.6, 9.6, w, h, "policy/compare.py", ["paired t intervals"], size=9.5)
    for y0, y1 in ((14.4, 13.7), (12.2, 11.1)):
        arrow(ax, (16.2, y0), (16.2, y1))
    ax.text(16.2, 8.9, "reads files only;\nstarts no simulator", ha="center", va="top",
            fontsize=8.5, color=MUTED)
    # shared env and simulator
    box(ax, 3.2, 2.4, 7.4, 2.2, "env/mesh_env.py + env/episode.py",
        ["MeshRlEnv: reset, step, action_masks;", "one simulator process per episode"],
        fc=NEUTRAL, ec=MUTED, size=9.5)
    box(ax, 15.4, 2.4, 8.2, 2.2, "sim.cc + src/rl/rl-bridge.cc",
        ["tick loop; init and step lines;", "masks, walls, reward window"], fc=PALE_BLUE, ec=BLUE,
        size=9.5)
    arrow(ax, (6.2, 9.6), (6.2, 4.6))
    ax.text(6.05, 5.4, "step()", ha="right", fontsize=8.5, color=INK)
    arrow(ax, (8.9, 7.0), (8.9, 4.6))
    ax.text(9.05, 5.4, "step()", ha="left", fontsize=8.5, color=INK)
    arrow(ax, (10.6, 3.9), (15.4, 3.9))
    arrow(ax, (15.4, 3.1), (10.6, 3.1), ls="--")
    ax.text(13.0, 4.1, "{\"action\":[...]} on stdin", ha="center", fontsize=8.5, color=INK)
    ax.text(13.0, 2.6, "init, step on stdout", ha="center", fontsize=8.5, color=INK)
    ax.text(0.4, 0.8, "Paths are under scripts/rl/ unless they start with sim.cc or src/. "
            "Solid arrows: calls or writes; dashed: replies.", fontsize=9, color=MUTED)
    save(fig, "rl-code-flow.svg")


# ---------------------------------------------------------------- measured figures

def figure_map():
    contract, records = read_steps(eval_episode(os.path.join(OUT, "eval"), "model", 11))
    bounds = contract["bounds"]
    a, b = records[0]["facts"]["nodes"][0], records[0]["facts"]["nodes"][1]
    fig, ax = plt.subplots(figsize=(9.2, 6.6))
    style_map(ax, "building-bypass-smoke from above (both nodes at z = 10 m)")
    draw_scene(ax)
    node(ax, a[0], a[1], "node-a (fixed)", "s", INK, (8, 10), "left")
    node(ax, b[0], b[1], "node-b (controlled)", "o", BLUE, (0, 12))
    for (dx, dy, label) in ((0, 20, "north"), (0, -20, "south"), (-20, 0, "west"), (20, 0, "east")):
        ax.annotate("", xy=(b[0] + dx, b[1] + dy), xytext=(b[0], b[1]),
                    arrowprops=dict(arrowstyle="-|>", color=BLUE, lw=1.3), zorder=5)
    ax.text(b[0], b[1] - 32, "one decision = 20 m", ha="center", fontsize=9, color=BLUE)
    ax.text(100, 0, "building\n30 m tall", ha="center", va="center", fontsize=8.5, color="white",
            zorder=4, rotation=90)
    ax.text(140, 16, "NLOS from node-a\n(the building's shadow)", ha="center", fontsize=9,
            color=MUTED)
    ax.annotate("LOS once |y| > 44.4 m at x = 200", (200, 44.4), xytext=(150, 75),
                fontsize=9, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.scatter([200, 200], [44.4, -44.4], s=18, color=INK, zorder=6)
    ax.text(3, 103, f"[rl] bounds: x {bounds['x_min']:g} to {bounds['x_max']:g}, "
            f"y {bounds['y_min']:g} to {bounds['y_max']:g}", fontsize=9, color=MUTED)
    save(fig, "rl-example-map.svg")


def timing_row(ax, records, k, title, max_tick):
    style(ax, title, None, "tick")
    ax.set_ylim(-1.6, 1.9)
    ax.set_yticks([])
    ax.set_xlim(-0.8, max_tick + 0.8)
    ax.grid(False)
    for record in records:
        tick, n, scored = int(record["tick"]), int(record["ticks_in_step"]), int(record["scored_ticks"])
        if tick > max_tick:
            break
        ticks = list(range(tick - n + 1, tick + 1))
        for t in ticks:
            is_scored = t > tick - scored
            first = record["decision"] == 0
            ax.add_patch(Rectangle((t - 0.38, -0.38), 0.76, 0.76,
                                   fc=(NEUTRAL if first else BLUE if is_scored else "white"),
                                   ec=(MUTED if first or not is_scored else BLUE), lw=1.0,
                                   hatch=("////" if first else None), zorder=3))
        ax.plot([tick + 0.5, tick + 0.5], [-1.0, 1.2], color=INK, lw=1.0, zorder=2)
        if record["decision"] == 0:
            ax.text(tick + 0.55, 1.3, "reset", fontsize=8.5, color=INK, ha="center")
        else:
            ax.annotate("", xy=(ticks[0] - 0.4, 0.75), xytext=(tick + 0.4, 0.75),
                        arrowprops=dict(arrowstyle="|-|", color=MUTED, lw=0.8,
                                        shrinkA=0, shrinkB=0, mutation_scale=3))
            ax.text((ticks[0] + tick) / 2, 0.95,
                    f"decision {record['decision']}: {scored} of {n} scored", ha="center",
                    fontsize=8.5, color=INK)
        ax.text(tick + 0.5, -1.35, f"t = {record['time_s']:g} s", ha="center", fontsize=8,
                color=MUTED)


def figure_timing():
    _, bypass = read_steps(eval_episode(os.path.join(OUT, "eval"), "model", 11))
    contract, scored = read_steps(eval_episode(os.path.join(OUT, "placement", "zero-cost", "eval"),
                                               "model", 801))
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 5.8))
    timing_row(axes[0], bypass, 10, "building-bypass-smoke: tick 0.1 s, decision every 10 ticks, "
               "no warmup", 30)
    timing_row(axes[1], scored, 5, "channel-scored-example: tick 0.1 s, decision every 5 ticks, "
               f"warmup {contract['warmup_s']:g} s", 30)
    handles = [Rectangle((0, 0), 1, 1, fc=BLUE, ec=BLUE),
               Rectangle((0, 0), 1, 1, fc="white", ec=MUTED),
               Rectangle((0, 0), 1, 1, fc=NEUTRAL, ec=MUTED, hatch="////")]
    fig.legend(handles, ["scored tick (counts toward reward and metrics)",
                         "warmup tick (simulated, moves happen, never scored)",
                         "tick 0: only in the reset message"], loc="lower left", ncol=3,
               frameon=False, fontsize=9, bbox_to_anchor=(0.02, -0.04))
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save(fig, "rl-timing.svg")


def figure_observation():
    from scripts.rl.env.observations import get_preset
    manifest = json.load(open(os.path.join(OUT, "eval", "eval_manifest.json")))
    params = manifest["selection"]["observation_parameters"]
    preset = get_preset("local_links_v1", params)
    contract, records = read_steps(eval_episode(os.path.join(OUT, "eval"), "model", 11))
    names = preset.feature_names(contract)
    los = next(r for r in records if r["decision"] > 0 and r["facts"]["links"][0][2] == 1)
    picks = [records[0], los]
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    style(ax, "local_links_v1 for one slot and one peer: 8 numbers", "value")
    xs = list(range(len(names)))
    width = 0.36
    for j, (record, color, hatch) in enumerate(zip(picks, (MUTED, BLUE), (None, None))):
        obs = preset.build(record["facts"], contract)
        node_b = record["facts"]["nodes"][1]
        label = (f"decision {record['decision']}: node-b at ({node_b[0]:g}, {node_b[1]:g}), "
                 f"{'LOS' if record['facts']['links'][0][2] else 'NLOS'}, "
                 f"SINR {record['facts']['links'][0][0]:.1f} dB")
        bars = ax.bar([x + (j - 0.5) * width for x in xs], obs, width, color=color, label=label,
                      edgecolor="white")
        for bar, value in zip(bars, obs):
            y = value + (0.04 if value >= 0 else -0.04)
            ax.text(bar.get_x() + bar.get_width() / 2, y, f"{value:.2f}", ha="center",
                    va="bottom" if value >= 0 else "top", fontsize=7.8, color=INK)
    ax.set_xticks(xs)
    ax.set_xticklabels([n.replace("slot0.", "").replace("peer_index0.", "peer.") for n in names],
                       fontsize=9, color=INK)
    ax.axhline(0, color=EDGE, lw=1)
    ax.set_ylim(-1.15, 1.25)
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK,
              bbox_to_anchor=(0, -0.12), ncol=1)
    save(fig, "rl-observation.svg")


def figure_trace():
    episode = eval_episode(os.path.join(OUT, "eval"), "model", 11)
    _, records = read_steps(episode)
    seed_dir = glob.glob(os.path.join(episode, "seed-*"))[0]
    links = read_csv(os.path.join(seed_dir, "links.csv"))
    pos = [r for r in read_csv(os.path.join(seed_dir, "positions.csv")) if r["node_id"] == "1"]
    t = [float(r["time_s"]) for r in links]
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 8.2), sharex=True,
                             gridspec_kw={"height_ratios": [1.1, 1, 1]})
    ax = axes[0]
    style(ax, "Link SINR every tick", "SINR (dB)")
    los = [r["condition"] == "LOS" for r in links]
    sinr = [float(r["sinr_db"]) for r in links]
    ax.plot(t, sinr, color=MUTED, lw=1.0, zorder=2)
    ax.scatter([x for x, l in zip(t, los) if l], [s for s, l in zip(sinr, los) if l], s=10,
               color=BLUE, zorder=3, label="LOS tick")
    ax.scatter([x for x, l in zip(t, los) if not l], [s for s, l in zip(sinr, los) if not l],
               s=12, facecolor="white", edgecolor=RED, lw=0.9, zorder=3, label="NLOS tick")
    ax.legend(loc="lower right", frameon=False, fontsize=9, ncol=2)
    ax = axes[1]
    style(ax, "Reward: per tick (all_links_los) and per decision (window mean)", "reward")
    ax.scatter(t[1:], [1 if l else -1 for l in los[1:]], s=8, color=MUTED, zorder=2,
               label="per-tick reward")
    records = [r for r in records if r["decision"] > 0]   # decision 0 is the reset
    ends = [r["time_s"] for r in records]
    for r, end in zip(records, ends):
        start = end - r["ticks_in_step"] * 0.1
        ax.plot([start + 0.05, end + 0.05], [r["reward"]["total"]] * 2, color=BLUE, lw=2.2,
                solid_capstyle="butt", zorder=3)
    ax.plot([], [], color=BLUE, lw=2.2, label="step reward the learner sees")
    third = records[2]
    ax.annotate(f"decision {third['decision']}: {third['reward']['total']:+.1f}",
                (third["time_s"] - 0.5, third["reward"]["total"]), xytext=(18, -26),
                textcoords="offset points", fontsize=9, color=INK,
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.set_ylim(-1.4, 1.5)
    ax.legend(loc="lower right", frameon=False, fontsize=9, ncol=2)
    ax = axes[2]
    style(ax, "node-b position", "position (m)", "time (s)")
    pt = [float(r["time_s"]) for r in pos]
    ax.plot(pt, [float(r["x"]) for r in pos], color=INK, lw=1.6)
    ax.plot(pt, [float(r["y"]) for r in pos], color=BLUE, lw=1.6, ls=(0, (5, 2)))
    ax.text(pt[-1] + 0.2, float(pos[-1]["x"]), "x", color=INK, fontsize=10, va="center")
    ax.text(pt[-1] + 0.2, float(pos[-1]["y"]), "y", color=BLUE, fontsize=10, va="center")
    for ax in axes:
        for end in ends:
            ax.axvline(end + 0.05, color=GRID, lw=1.0, zorder=0)
    axes[2].set_xlim(0, 20.6)
    fig.tight_layout()
    save(fig, "rl-trace.svg")


def training_returns(run_dir):
    timesteps, returns, total = [], [], 0
    for path in sorted(glob.glob(os.path.join(run_dir, "episode-*", "rl_episode.json"))):
        episode = json.load(open(path))
        if episode["status"] != "completed":
            continue
        total += int(episode["steps"])
        timesteps.append(total)
        returns.append(float(episode["cumulative_reward"]))
    return timesteps, returns


def figure_learning_curve():
    import numpy as np
    run = os.path.join(OUT, "train")
    steps, returns = training_returns(run)
    evals = np.load(os.path.join(run, "evaluations.npz"))
    progress = read_csv(os.path.join(run, "ppo", "progress.csv"))
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 7.6), sharex=True,
                             gridspec_kw={"height_ratios": [1.6, 1]})
    ax = axes[0]
    style(ax, "Episode return", "return (sum of 20 step rewards)")
    ax.scatter(steps, returns, s=7, color="#b8c2cc", zorder=2, label="training episode (explores)")
    window = 20
    rolling = [sum(returns[max(0, i - window + 1):i + 1]) / len(returns[max(0, i - window + 1):i + 1])
               for i in range(len(returns))]
    ax.plot(steps, rolling, color=BLUE, lw=2, zorder=3, label=f"mean of last {window} training episodes")
    ax.plot(evals["timesteps"], evals["results"].mean(axis=1), color=INK, lw=1.2, marker="D",
            ms=4, zorder=4, label="model selection: deterministic, seed 2")
    ax.axhline(-20, color=MUTED, lw=1, ls=(0, (2, 2)))
    ax.text(steps[-1], -19.2, "hold scores −20 on every seed", ha="right", fontsize=9,
            color=MUTED)
    ax.set_ylim(-22, 19)
    ax.legend(loc="center right", frameon=False, fontsize=9, labelcolor=INK)
    ax = axes[1]
    style(ax, "Policy entropy (falls as the policy commits)", "entropy (nats)", "timesteps (decisions)")
    rows = [r for r in progress if r.get("train/entropy_loss")]
    ax.plot([int(r["time/total_timesteps"]) for r in rows],
            [-float(r["train/entropy_loss"]) for r in rows], color=BLUE, lw=1.8)
    ax.axhline(math.log(5), color=MUTED, lw=1, ls=(0, (2, 2)))
    ax.text(rows[-1] and int(rows[-1]["time/total_timesteps"]), math.log(5) - 0.04,
            "uniform over 5 moves: ln 5 = 1.61", ha="right", va="top", fontsize=9, color=MUTED)
    fig.tight_layout()
    save(fig, "rl-learning-curve.svg")


def draw_path(ax, episode, key, label, every=1, offset=(6, 6), ha="left"):
    color, marker, ls, _ = POLICY[key]
    xs, ys, los = path_of(episode)
    ax.plot(xs, ys, color=color, lw=1.6, ls=ls, zorder=4)
    ax.scatter(xs[::every], ys[::every], s=14, marker=marker,
               facecolor=[color if l else "white" for l in los[::every]], edgecolor=color,
               lw=0.9, zorder=5)
    ax.annotate(label, (xs[-1], ys[-1]), xytext=offset, textcoords="offset points", ha=ha,
                fontsize=9,
                color=color, fontweight="bold", zorder=7,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.85))


def figure_trajectories():
    eval_dir = os.path.join(OUT, "eval")
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.6))
    ax = axes[0]
    style_map(ax, "Held-out seed 11, every tick")
    draw_scene(ax)
    node(ax, 0, 0, "node-a", "s", INK, (8, 8), "left")
    for key in ("random_valid", "model", "hold"):
        manifest = json.load(open(os.path.join(eval_dir, "eval_manifest.json")))
        episode = eval_episode(eval_dir, key, 11)
        ret = next(e["return"] for e in manifest["policies"][key]["episodes"] if e["seed"] == 11)
        offset, ha = ((-8, -14), "right") if key == "random_valid" else ((6, 6), "left")
        draw_path(ax, episode, key, f"{POLICY[key][3]} ({ret:+.1f})", every=2, offset=offset,
                  ha=ha)
    ax = axes[1]
    style_map(ax, "Training on seed 1: first and last 3 episodes")
    draw_scene(ax)
    node(ax, 0, 0, "node-a", "s", INK, (8, 8), "left")
    done = [os.path.dirname(p) for p in sorted(glob.glob(os.path.join(OUT, "train", "episode-*",
                                                                       "rl_episode.json")))
            if json.load(open(p))["status"] == "completed"]
    for k, episode in enumerate(done[:3]):
        xs, ys, _ = path_of(episode)
        ax.plot(xs, ys, color=AMBER, lw=1.1, ls=(0, (5, 3)), zorder=3,
                label="first 3 (random network)" if k == 0 else None)
    for k, episode in enumerate(done[-3:]):
        xs, ys, _ = path_of(episode)
        ax.plot(xs, ys, color=BLUE, lw=1.6, zorder=4, label="last 3" if k == 0 else None)
    ax.legend(loc="upper left", frameon=False, fontsize=9, bbox_to_anchor=(0, -0.12), ncol=2)
    handles = [plt.Line2D([], [], marker="o", ls="", color=INK, mfc=INK, ms=5),
               plt.Line2D([], [], marker="o", ls="", color=INK, mfc="white", ms=5)]
    axes[0].legend(handles, ["filled marker: link LOS", "hollow marker: link NLOS"],
                   loc="upper left", frameon=False, fontsize=9, bbox_to_anchor=(0, -0.12), ncol=2)
    fig.tight_layout()
    save(fig, "rl-trajectories.svg")


def per_policy(eval_dir, metric):
    manifest = json.load(open(os.path.join(eval_dir, "eval_manifest.json")))
    out = {}
    for policy, block in manifest["policies"].items():
        values = [(e["seed"], e["return"] if metric == "return" else e["metrics"][metric])
                  for e in block["episodes"]]
        out[policy] = values
    return out


def mean_ci(values):
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    return mean, t95(n) * sd / math.sqrt(n)


def figure_eval_metrics():
    eval_dir = os.path.join(OUT, "eval")
    metrics = (("return", "return"), ("los_fraction", "fraction of scored ticks"),
               ("travel_m_total", "m"))
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    order = ("model", "random_valid", "hold")
    for ax, (metric, unit) in zip(axes, metrics):
        data = per_policy(eval_dir, metric)
        style(ax, metric, unit)
        for k, policy in enumerate(order):
            color, marker, _, label = POLICY[policy]
            values = [v for _, v in data[policy]]
            mean, half = mean_ci(values)
            ax.scatter([k + (j - 2) * 0.06 for j in range(len(values))], values, s=14,
                       marker=marker, facecolor="white", edgecolor=color, lw=0.9, zorder=3)
            ax.errorbar([k + 0.28], [mean], yerr=[[half], [half]], fmt=marker, color=color,
                        ms=7, capsize=4, lw=1.4, zorder=4)
            ax.text(k + 0.4, mean, f"{mean:.3g}", fontsize=8.5, color=color, va="center")
        ax.set_xticks(range(len(order)))
        ax.set_xticklabels([POLICY[p][3] for p in order], fontsize=9, color=INK)
        ax.set_xlim(-0.5, len(order) - 0.1)
    fig.text(0.01, -0.04, "Hollow markers: the 5 held-out seeds (11-15). Filled marker and bar: "
             "mean and 95% t interval across those seeds, one fixed model.", fontsize=9,
             color=MUTED)
    fig.tight_layout()
    save(fig, "rl-eval-metrics.svg")


def figure_paired():
    comparison = json.load(open(os.path.join(OUT, "compare", "comparison.json")))
    comps = comparison["evaluations"][0]["comparisons"]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.2), gridspec_kw={"width_ratios": [1.2, 1]})
    for row, (metric, unit) in enumerate((("return", "return"),
                                          ("los_fraction", "fraction of scored ticks"))):
        ax = axes[row][0]
        style(ax, f"{metric}: each seed's pair", unit)
        for baseline, shift in (("hold", 0.0), ("random_valid", -0.08)):
            comp = next(c for c in comps if c["baseline"] == baseline and c["metric"] == metric)
            color, marker, ls, label = POLICY[baseline]
            for pair in comp["pairs"]:
                ax.plot([shift, 1], [pair["baseline"], pair["model"]], color=color, lw=1.0, ls=ls,
                        marker=marker, ms=4.5, mfc="white", zorder=3)
            if baseline == "hold":
                ax.annotate("hold (all 5 seeds)", (shift, comp["pairs"][0]["baseline"]),
                            xytext=(8, -12), textcoords="offset points", fontsize=8.5,
                            color=color)
            else:
                ax.text(shift - 0.06, max(p["baseline"] for p in comp["pairs"]), label,
                        ha="right", va="center", fontsize=8.5, color=color)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["baseline", "trained model"], fontsize=9, color=INK)
        ax.set_xlim(-0.75, 1.2)
        ax = axes[row][1]
        style(ax, f"{metric}: model − baseline", f"difference ({unit})")
        for k, baseline in enumerate(("hold", "random_valid")):
            comp = next(c for c in comps if c["baseline"] == baseline and c["metric"] == metric)
            color, marker, _, label = POLICY[baseline]
            mean = comp["mean_difference"]
            iv = comp.get("interval") or {"low": mean, "high": mean}
            ax.errorbar([k], [mean], yerr=[[mean - iv["low"]], [iv["high"] - mean]], fmt=marker,
                        color=color, capsize=5, ms=7, lw=1.5)
            txt = (f"{mean:+.3g}  zero variance" if comp.get("zero_variance") else
                   f"{mean:+.3g}  [{iv['low']:+.3g}, {iv['high']:+.3g}]")
            ax.text(k + 0.1, mean, txt, fontsize=8.5, color=INK, va="center")
        ax.axhline(0, color=EDGE, lw=1)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["vs hold", "vs random_valid"], fontsize=9, color=INK)
        ax.set_xlim(-0.4, 1.9)
        low = min(0, min((c.get("interval") or {"low": c["mean_difference"]})["low"]
                         for c in comps if c["metric"] == metric and c["baseline"] in ("hold", "random_valid")))
        ax.set_ylim(bottom=low - 0.05 * abs(low or 1))
    fig.text(0.01, -0.02, "Held-out seeds 11-15, one fixed model. Intervals are paired t intervals "
             "(t = 2.776, 4 degrees of freedom) from comparison.json.", fontsize=9, color=MUTED)
    fig.tight_layout()
    save(fig, "rl-paired.svg")


def figure_custom():
    data = json.load(open(os.path.join(OUT, "custom-algorithm", "qtable.json")))
    returns = data["returns"]
    manifest = json.load(open(os.path.join(OUT, "custom-algorithm", "eval", "eval_manifest.json")))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2), gridspec_kw={"width_ratios": [1.6, 1]})
    ax = axes[0]
    style(ax, "Masked Q-learning: training episodes on seed 1", "return", "episode (20 decisions each)")
    xs = list(range(1, len(returns) + 1))
    ax.plot(xs, returns, color=GREEN, lw=1.4, marker="D", ms=4)
    ax.axhline(-20, color=MUTED, lw=1, ls=(0, (2, 2)))
    ax.text(len(xs), -19.2, "hold: −20", ha="right", fontsize=9, color=MUTED)
    ax.set_ylim(-22, 19)
    ax = axes[1]
    style(ax, "Held-out seeds 11-15", "return")
    order = ("qtable", "random_valid", "hold")
    for k, policy in enumerate(order):
        color, marker, _, label = POLICY[policy]
        values = [e["return"] for e in manifest["policies"][policy]["episodes"]]
        mean, half = mean_ci(values)
        ax.scatter([k - 0.15] * len(values), values, s=14, marker=marker, facecolor="white",
                   edgecolor=color, lw=0.9)
        ax.errorbar([k + 0.1], [mean], yerr=[[half], [half]], fmt=marker, color=color, capsize=4,
                    ms=7)
        ax.text(k + 0.22, mean, f"{mean:.3g}", fontsize=8.5, color=color, va="center")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([POLICY[p][3] for p in order], fontsize=9, color=INK)
    ax.set_xlim(-0.5, len(order) - 0.1)
    ax.set_ylim(-22, 19)
    fig.tight_layout()
    save(fig, "rl-custom.svg")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sim-binary", help="delete and redo every run with this built binary")
    args = parser.parse_args()
    if args.sim_binary:
        capture(args.sim_binary)
    figure_architecture()
    figure_sequence()
    figure_code_flow()
    figure_map()
    figure_timing()
    figure_observation()
    figure_trace()
    figure_learning_curve()
    figure_trajectories()
    figure_eval_metrics()
    figure_paired()
    figure_custom()


if __name__ == "__main__":
    main()
