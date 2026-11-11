"""Generate the system overview figure, system-overview.svg, beside this script.

Twin copies (keep both files and both SVGs identical):
    ns3-mmwave/scratch/mesh-sim/docs/diagrams/system-overview.py
    ns3-mmwave-viz/docs/diagrams/system-overview.py

The SVG is embedded with \image html by docs/system-overview.md (both sites) and
the simulator's docs/index.md. Edit this script, not the SVG, then from docs/:

    python3 diagrams/system-overview.py

Layout: a legend, then four numbered bands read top to bottom (scenario,
simulator, run outputs, visualizer), with the Python tools beside the scenario.
The simulator band shows the once-per-run steps and the per-tick loop.

Colour is by category and is used the same way everywhere (panel, card accent,
module tag): amber = files on disk, blue = simulator C++ (src/), purple =
Python tools (scripts/), green = visualizer. Solid arrows are data flow; dashed
arrows are a Python tool driving the simulator. Colours are flat on a white
card so the figure reads on light and dark pages. Labels follow README.md,
CLAUDE.md and the module pages; keep them in step when those change.
"""
import os
from html import escape

W = 900
PAD = 20
SANS = "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "SFMono-Regular, Menlo, Consolas, monospace"

# Approximate advance widths (px per character) used to size chips and tags.
MONO_W = 0.6
SANS_W = 0.48

C = {
    "ink": "#1f2d3a", "muted": "#5b6b7b", "line": "#7f8c99",
    "file_fill": "#fdf7e8", "file_stroke": "#ecd9a6", "file_head": "#86620f", "file_accent": "#c99a1e",
    "file_tag": "#f8ecc9",
    "sim_fill": "#f2f7fc", "sim_stroke": "#c9dcef", "sim_head": "#1f6391", "sim_accent": "#2980b9",
    "sim_tag": "#dcebf8",
    "tool_fill": "#f7f4fc", "tool_stroke": "#dcd0ef", "tool_head": "#5b3f8c", "tool_accent": "#8e6cc7",
    "tool_tag": "#ebe3f7",
    "viz_fill": "#f0f9f3", "viz_stroke": "#c8e6d2", "viz_head": "#1e7a45", "viz_accent": "#27ae60",
    "viz_tag": "#d8f0e1",
}

out = []


def add(s):
    out.append(s)


def text(x, y, s, size=13, weight=400, color=None, family=SANS, anchor="start"):
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{color or C["ink"]}" text-anchor="{anchor}">{escape(s)}</text>')


def panel(x, y, w, h, kind, number, title, subtitle=None):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{C[kind + "_fill"]}" '
        f'stroke="{C[kind + "_stroke"]}" stroke-width="1.2"/>')
    hx = x + 18
    if number:
        add(f'<circle cx="{hx + 11}" cy="{y + 25}" r="11" fill="{C[kind + "_accent"]}"/>')
        text(hx + 11, y + 29.5, number, size=12.5, weight=700, color="#ffffff", anchor="middle")
        hx += 30
    sub = ""
    if subtitle:
        # dx (not a leading space) keeps the gap: SVG collapses leading whitespace.
        sub = (f'<tspan dx="10" font-weight="400" font-size="13" fill="{C["muted"]}">'
               f'{escape(subtitle)}</tspan>')
    add(f'<text x="{hx}" y="{y + 30}" font-family="{SANS}" font-size="15" font-weight="700" '
        f'fill="{C[kind + "_head"]}">{escape(title)}{sub}</text>')


def tag(x, y, label, kind):
    """A small module-path tag, coloured by category. Returns the right edge."""
    w = len(label) * 11.5 * MONO_W + 14
    add(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="20" rx="4" fill="{C[kind + "_tag"]}"/>')
    text(x + 7, y + 14, label, size=11.5, color=C[kind + "_head"], family=MONO)
    return x + w


def card(x, y, w, h, kind, title, lines=(), tags=(), dashed=False):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#ffffff" '
        f'stroke="{C[kind + "_stroke"] if not dashed else C[kind + "_accent"]}" stroke-width="1.2"{dash}/>')
    add(f'<rect x="{x}" y="{y + 12}" width="3" height="{h - 24}" rx="1.5" fill="{C[kind + "_accent"]}"/>')
    ty = y + 24
    text(x + 16, ty, title, size=14, weight=700)
    ty += 19
    for line in lines:
        text(x + 16, ty, line, size=12.5, color=C["muted"])
        ty += 17
    tx = x + 16
    for t in tags:
        tx = tag(tx, y + h - 30, t, kind) + 6


def chip(x, y, label, kind, mono=True, note=None):
    """A file chip with an optional muted note. Returns the right edge."""
    lw = len(label) * 12 * (MONO_W if mono else SANS_W)
    nw = len(note) * 11.5 * SANS_W + 7 if note else 0
    w = lw + nw + 22
    add(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="26" rx="13" fill="#ffffff" '
        f'stroke="{C[kind + "_stroke"]}" stroke-width="1.1"/>')
    fam = MONO if mono else SANS
    note_span = ""
    if note:
        note_span = (f'<tspan dx="7" font-family="{SANS}" font-size="11.5" fill="{C["muted"]}">'
                     f'{escape(note)}</tspan>')
    add(f'<text x="{x + 11:.1f}" y="{y + 17.5}" font-family="{fam}" font-size="12" '
        f'fill="{C["ink"]}">{escape(label)}{note_span}</text>')
    return x + w


def label_pill(x, y, s, mono=False, bg="#ffffff"):
    """A label centred on (x, y) with a background, for labels that sit on a line."""
    w = len(s) * 12 * (MONO_W if mono else SANS_W) + 16
    add(f'<rect x="{x - w / 2:.1f}" y="{y - 10}" width="{w:.1f}" height="20" rx="10" fill="{bg}"/>')
    text(x, y + 4, s, size=12, color=C["muted"], anchor="middle", family=MONO if mono else SANS)


def path(points, dashed=False):
    """An orthogonal arrow through the given points, ending in an arrowhead."""
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in points)
    add(f'<path d="{d}" fill="none" stroke="{C["line"]}" stroke-width="1.5"{dash} '
        f'stroke-linejoin="round" marker-end="url(#arrow)"/>')


def arrow(x1, y1, x2, y2, dashed=False):
    path([(x1, y1), (x2, y2)], dashed=dashed)


def side_label(x, y, s, mono=False):
    text(x + 10, y + 4, s, size=12, color=C["muted"], family=MONO if mono else SANS)


# ---------------------------------------------------------------- legend
y = PAD
lx = PAD + 4
for kind, name in [("file", "Files on disk"), ("sim", "Simulator  (src/)"),
                   ("tool", "Python tools  (scripts/)"), ("viz", "Visualizer")]:
    add(f'<rect x="{lx}" y="{y + 2}" width="14" height="14" rx="3" fill="{C[kind + "_fill"]}" '
        f'stroke="{C[kind + "_accent"]}" stroke-width="1.5"/>')
    text(lx + 21, y + 14, name, size=12, color=C["ink"])
    lx += 21 + len(name) * 12 * SANS_W + 20
lx += 4
for dashed, name in [(False, "data flow"), (True, "a Python tool runs the simulator")]:
    arrow(lx, y + 9, lx + 30, y + 9, dashed=dashed)
    text(lx + 38, y + 14, name, size=12, color=C["ink"])
    lx += 38 + len(name) * 12 * SANS_W + 20
y += 18 + 20

# ---------------------------------------------------------------- band 1: scenario + tools
b1y = y
b1h = 152
left_w = 430
panel(PAD, b1y, left_w, b1h, "file", "1", "Scenario", "inputs/<scenario>/")
cy = b1y + 52
cx = chip(PAD + 18, cy, "run.ini", "file") + 8
chip(cx, cy, "nodes.json", "file")
cx = chip(PAD + 18, cy + 36, "buildings.json", "file", note="optional") + 8
chip(cx, cy + 36, "jammers.json", "file", note="optional")

tools_x = PAD + left_w + 90
tools_w = W - PAD - tools_x
panel(tools_x, b1y, tools_w, b1h, "tool", None, "Python tools", "scripts/")
for row, names in enumerate([("arpo_data/", "validation/", "sweep/"),
                             ("rl/", "baselines/", "plotting/")]):
    tx = tools_x + 18
    for n in names:
        tx = chip(tx, cy + row * 36, n, "tool") + 8
text(tools_x + 18, b1y + b1h - 16, "launch an already-built binary; never build it",
     size=11.5, color=C["muted"])

# tools build scenarios
gap_mid = PAD + left_w + 45
arrow(tools_x - 2, b1y + 70, PAD + left_w + 4, b1y + 70)
text(gap_mid, b1y + 60, "build", size=12, color=C["muted"], anchor="middle")
text(gap_mid, b1y + 88, "scenarios", size=12, color=C["muted"], anchor="middle")

band1_bottom = b1y + b1h
y = band1_bottom + 56

# ---------------------------------------------------------------- band 2: simulator
b2y = y
inner_x = PAD + 18
inner_w = W - 2 * PAD - 36

# once per run
row1_label_y = b2y + 56
r1y = row1_label_y + 10
cw, ch, gap = (inner_w - 2 * 30) // 3, 100, 30

# every tick
loop_y = r1y + ch + 40
tg = 26
tw, th = (inner_w - 28 - 3 * tg) // 4, 100
ty = loop_y + 38
rl_w, rl_h = 300, 62
rl_y = ty + th + 26
loop_h = rl_y + rl_h + 18 - loop_y
b2h = loop_y + loop_h + 18 - b2y

panel(PAD, b2y, W - 2 * PAD, b2h, "sim", "2", "Simulator", "sim.cc + C++ modules in src/")

# arrows into the simulator
scen_x = PAD + 140
arrow(scen_x, band1_bottom + 2, scen_x, b2y - 4)
side_label(scen_x, (band1_bottom + b2y) / 2, "read at start")
tools_cx = tools_x + tools_w / 2
arrow(tools_cx, band1_bottom + 2, tools_cx, b2y - 4, dashed=True)
side_label(tools_cx, (band1_bottom + b2y) / 2, "--sim-binary <BIN>", mono=True)

text(inner_x, row1_label_y, "ONCE PER RUN", size=11, weight=700, color=C["sim_head"])
once = [
    ("Load and validate", ["run.ini + JSON into a SimConfig;", "CLI overrides applied"], ("config/", "cli/")),
    ("Record the run", ["archive the inputs, write run.log", "(“Resolved config” block)"], ("io/",)),
    ("Build the topology, per seed", ["ns-3 nodes, mobility, buildings,", "propagation models"], ("setup/",)),
]
for i, (t, lines, tags) in enumerate(once):
    card(inner_x + i * (cw + gap), r1y, cw, ch, "sim", t, lines, tags)
    if i:
        arrow(inner_x + i * (cw + gap) - gap + 2, r1y + ch / 2, inner_x + i * (cw + gap) - 4, r1y + ch / 2)

loop_x = inner_x
loop_w = inner_w
add(f'<rect x="{loop_x}" y="{loop_y}" width="{loop_w}" height="{loop_h}" rx="12" fill="#ffffff" '
    f'fill-opacity="0.55" stroke="{C["sim_stroke"]}" stroke-width="1.2" stroke-dasharray="4 4"/>')
add(f'<text x="{loop_x + 14}" y="{loop_y + 23}" font-family="{SANS}" font-size="11" font-weight="700" '
    f'fill="{C["sim_head"]}">EVERY TICK<tspan dx="10" font-size="12" font-weight="400" '
    f'fill="{C["muted"]}">advance the ns-3 clock, then:</tspan></text>')
setup_cx = inner_x + 2 * (cw + gap) + cw / 2
arrow(setup_cx, r1y + ch + 2, setup_cx, loop_y - 4)

tx0 = loop_x + 14
steps = [
    ("Evaluate links", ["SINR, capacity, MCS", "for every node pair"], ("eval/", "jammer/")),
    ("Generate traffic", ["flow-level demands", "(no packets)"], ("traffic/",)),
    ("Route flows", ["multi-hop paths over", "the link table"], ("routing/",)),
    ("Write outputs", ["per-tick CSVs and", "metrics"], ("io/",)),
]
for i, (t, lines, tags) in enumerate(steps):
    card(tx0 + i * (tw + tg), ty, tw, th, "sim", t, lines, tags)
    if i:
        arrow(tx0 + i * (tw + tg) - tg + 2, ty + th / 2, tx0 + i * (tw + tg) - 4, ty + th / 2)

# Optional RL step on the way back to the next tick.
first_cx = tx0 + tw / 2
write_x = tx0 + 3 * (tw + tg)
rl_x = (tx0 + tw + tg + write_x) / 2 - rl_w / 2
card(rl_x, rl_y, rl_w, rl_h, "sim", "RL step (optional)", ["JSON over stdin/stdout to the Python env"],
     dashed=True)
tag(rl_x + rl_w - 16 - (3 * 11.5 * MONO_W + 14), rl_y + 10, "rl/", "sim")
ret_y = rl_y + rl_h / 2
down_x = write_x + tw * 0.3
path([(down_x, ty + th + 2), (down_x, ret_y), (rl_x + rl_w + 4, ret_y)])
path([(rl_x - 2, ret_y), (first_cx, ret_y), (first_cx, ty + th + 4)])
label_pill((rl_x + first_cx) / 2, ret_y, "next tick")

band2_bottom = b2y + b2h
y = band2_bottom + 56

# ---------------------------------------------------------------- band 3: outputs
b3y = y
b3h = 132
panel(PAD, b3y, W - 2 * PAD, b3h, "file", "3", "Run outputs",
      "<output-dir>/  (default outputs/YYYY-MM/DD/HH-MM-SS/)")
writes_x = write_x + tw * 0.72
arrow(writes_x, ty + th + 2, writes_x, b3y - 4)
label_pill(writes_x, band2_bottom + 28, "writes")
cy = b3y + 52
cx = chip(PAD + 18, cy, "run.log", "file") + 8
cx = chip(cx, cy, "inputs/", "file", note="archived scenario") + 8
chip(cx, cy, "summary.json", "file", note="per seed")
cx = chip(PAD + 18, cy + 36, "seed-N/", "file", note="positions, links, rx-power, mcs, flows, routes CSVs") + 8
chip(cx, cy + 36, "RL artifacts", "file", mono=False, note="manifests, models (from scripts/rl)")

band3_bottom = b3y + b3h
y = band3_bottom + 56

# ---------------------------------------------------------------- band 4: visualizer
b4y = y
b4h = 160
panel(PAD, b4y, W - 2 * PAD, b4h, "viz", "4", "Visualizer", "ns3-mmwave-viz, read-only")
arrow(scen_x, band3_bottom + 2, scen_x, b4y - 4)
side_label(scen_x, (band3_bottom + b4y) / 2, "read-only")
vg = 38
vw, vh = (inner_w - 2 * vg) // 3, 92
vy = b4y + 52
viz = [
    ("Open Data Folder", ["run discovery"], ("lib/assembleRuns.ts",)),
    ("Parse and play back", ["CSV/JSON parsing, playback state"], ("lib/parseSimFiles.ts",)),
    ("3D canvas and RL pages", ["3D scene, RL experiment pages"], ("components/canvas/",)),
]
for i, (t, lines, tags) in enumerate(viz):
    card(inner_x + i * (vw + vg), vy, vw, vh, "viz", t, lines, tags)
    if i:
        arrow(inner_x + i * (vw + vg) - vg + 2, vy + vh / 2, inner_x + i * (vw + vg) - 4, vy + vh / 2)

H = b4y + b4h + PAD

svg = [
    '<!-- Generated by system-overview.py in this directory; edit the script and re-run it. -->',
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    f'role="img" aria-labelledby="t d">',
    '<title id="t">Mesh-Sim system overview</title>',
    '<desc id="d">Scenario files and Python tools feed the simulator; the simulator runs setup once, '
    'then evaluates links, generates traffic, routes flows, writes outputs and optionally takes an RL '
    'step every tick; the run outputs are read by the visualizer.</desc>',
    '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
    f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{C["line"]}"/></marker></defs>',
    f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="16" fill="#ffffff" stroke="#e1e4e5"/>',
]
svg += out
svg.append("</svg>")
target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system-overview.svg")
with open(target, "w") as f:
    f.write("\n".join(svg) + "\n")
print(f"wrote {target} ({W}x{H})")
