# run.log {#files_run_log}

[TOC]

`run.log` is the plain-text record of one simulator invocation: when it ran,
which seeds, every command-line flag, and the settings the simulator resolved
from `run.ini`, the node, building and jammer files and the command line. It
sits at the run root, `<output-dir>/run.log`, beside `inputs/` and the
`seed-N/` folders, and its `Resolved config` block is the source of truth for
what a run used. It is for you to read: no tool parses it, and the regression
snapshot refuses it because it holds timestamps and paths.

\htmlonly
<div class="ms-find" data-noun="line"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search lines, e.g. band_source, seeds, rl.contract" aria-label="Search lines"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

The whole file from `outputs/getting-started/01-static-los-baseline/run.log`,
block by block, plus a `Jammers:` block from another run:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>mesh-sim run log
================</b>
timestamp:           2026-10-27T15:38:58Z
scenario:            01-static-los-baseline
run_config:          scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini
seeds:               [1]
seed_source:         --seeds CLI argument</pre>
<div class="ms-ini-note"><strong>Header</strong>When the run started and which scenario it ran. One seed, <code>1</code>, chosen on the command line.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code"><b>CLI overrides:</b>
  --run-config         = scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini
  --seeds              = 1
  --seed               = (not set)
  --run-id             = (not set)
  --positions-override = (not set)
  --output-dir         = scratch/mesh-sim/outputs/getting-started/01-static-los-baseline
  --debug-links        = false
  --rl-mode            = false
  --band               = (not set)</pre>
<div class="ms-ini-note"><strong>Command-line flags</strong>Three flags were given: <code>&#45;&#45;run-config</code>, <code>&#45;&#45;seeds</code> and <code>&#45;&#45;output-dir</code>. The rest are <code>(not set)</code> or <code>false</code>.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code"><b>Resolved config:</b>
  duration_s          = 5
  tick_s              = 0.1
  warmup_s            = 0
  run_id              = 1
  nodes               = 2
  buildings           = 0
  channel_model       = 3gpp
  scenario            = RMa
  frequency_ghz       = 28
  bandwidth_mhz       = 400
  tx_power_dbm        = 30
  traffic.model       = constant
  traffic.topology    = all_pairs
  traffic.demand_mbps = 10
  routing.algorithm   = shortest_path
  routing.max_hops    = 5
  band                = mmwave
  band_source         = default
  rl.reward_type      = throughput
  rl.reward_alias     = none
  output.viz_enabled = true
  rl.building_clearance_m = 0
  rl.mask_building_moves = 1
  rl.unsafe_separation_m = 1
  rl.avoid_node_collisions = false
  rl.control_mode     = disabled
  rl.reward_warmup    = exclude
  rl.contract         = none
  rl.controlled_nodes = (none)
  rl.max_controlled_nodes = 0
  rl.control_start_s = 0
  rl.decision_interval_s  = 0.1
  rl.decision_interval_ticks = 1
  jammers.configured  = 0
  jammers.enabled     = 0
  jammer_path_enabled = false</pre>
<div class="ms-ini-note"><strong>The settings the run used</strong>Two nodes, no buildings, 3GPP <code>RMa</code> at 28 GHz and 400 MHz, one 10 Mbps flow, no RL and no jammers. <code>band_source = default</code>: neither <code>&#45;&#45;band</code> nor <code>run.ini</code> set the band.</div>
</div>
<div class="ms-ini-row ms-c-amber">
<pre class="ms-ini-code"><b>Jammers:</b>
  seeded-arrive-and-stay: enabled=true type=constant target_freq_mhz=[5800] tx_power_dbm=18 tx_array_gain_dbi=3 duty_cycle=1 max_range_m=140 beamwidth_deg=360 azimuth_deg=0 zenith_deg=90 motion=waypoints</pre>
<div class="ms-ini-note"><strong>Jammers</strong>From an RL training episode: one enabled 18 dBm jammer on 5800 MHz, omnidirectional, 140 m range, following waypoints. The 01 run has no jammers, so its file ends after <code>Resolved config</code>.</div>
</div>
</div>
\endhtmlonly

**Format.** UTF-8 text in up to four blocks, always in this order and
separated by blank lines: the header (`key: value` lines), `CLI overrides:`,
`Resolved config:` (`  key = value` lines) and, when `jammers.json` lists any
jammer, `Jammers:`. Numbers use C++ default formatting: up to 6 significant
digits, trailing zeros dropped (`5`, `0.1`, `28`).

**When it is written.** Once per invocation, after the configuration loads and
validates and before the first seed starts; one file covers every seed. A
rerun into the same `--output-dir` overwrites it. A run that stops with
`Error loading config:` or `Config error:` writes neither `run.log` nor
`inputs/`, and a `--channel-query` run never writes it.

## 2\. Header

When and what the invocation ran.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`mesh-sim run log`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Fixed title, underlined by `================`.</div>
<div class="ms-key-vals">fixed</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`timestamp:`<span class="ms-key-def">UTC text</span></div>
<div class="ms-key-what">Wall-clock time the file was written.<div class="ms-key-note">UTC, while the default `HH-MM-SS` output folder name is local time, so the two can differ by hours.</div></div>
<div class="ms-key-vals">`YYYY-MM-DDTHH:MM:SSZ`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`scenario:`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">`[scenario] name` from `run.ini`.<div class="ms-key-note">The `scenario` line under `Resolved config` is the channel environment.</div></div>
<div class="ms-key-vals">any text</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`run_config:`<span class="ms-key-def">path</span></div>
<div class="ms-key-what">The `--run-config` path exactly as typed.</div>
<div class="ms-key-vals">a path; a relative one is relative to the directory you launched from</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`seeds:`<span class="ms-key-def">list</span></div>
<div class="ms-key-what">The seeds this invocation runs, in order. Each gets its own `seed-N/` folder.</div>
<div class="ms-key-vals">for example `[1, 2, 3]`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`seed_source:`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Where the seed list came from.<div class="ms-key-note">`--seeds` wins over `--seed`. `config default` means `[scenario] seed`, because neither flag was given; pass `--seeds=1,2,3` to choose.</div></div>
<div class="ms-key-vals">`--seeds CLI argument`, `--seed CLI override`, `config default`</div>
</div>
</div>

## 3\. CLI overrides

One line per flag, `(not set)` when absent; booleans print `true` or `false`.
`--no-viz` and `--jammer-onset-s` are not listed; `output.viz_enabled` in
section 4 shows the effect of `--no-viz`.

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`--run-config`<span class="ms-key-def">path</span></div>
<div class="ms-key-what">The `run.ini` path.</div>
<div class="ms-key-vals">a path</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--seeds`<span class="ms-key-def">list</span></div>
<div class="ms-key-what">The comma-separated seed list as typed.</div>
<div class="ms-key-vals">for example `1,2,3`, or `(not set)`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--seed`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">Single-seed override.</div>
<div class="ms-key-vals">a seed, or `(not set)`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--run-id`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">Overrides `[scenario] run_id`.</div>
<div class="ms-key-vals">&ge; 0, or `(not set)`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--positions-override`<span class="ms-key-def">path</span></div>
<div class="ms-key-what">JSON file of `{"<node id>": [x, y, z]}` entries that replace those nodes' start positions.<div class="ms-key-note">Only the path is logged.</div></div>
<div class="ms-key-vals">a path, or `(not set)`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--output-dir`<span class="ms-key-def">path</span></div>
<div class="ms-key-what">Output root.<div class="ms-key-note">When `(not set)`, the run went to `[output] dir` or the timestamped default `outputs/YYYY-MM/DD/HH-MM-SS/`.</div></div>
<div class="ms-key-vals">a path, or `(not set)`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--debug-links`<span class="ms-key-def">boolean</span></div>
<div class="ms-key-what">Per-link debug logging to the console.</div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--rl-mode`<span class="ms-key-def">boolean</span></div>
<div class="ms-key-what">RL bridge on stdin/stdout.</div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`--band`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Band override.</div>
<div class="ms-key-vals">`mmwave`, `sub-6`, or `(not set)`</div>
</div>
</div>

## 4\. Resolved config

The values after `run.ini`, the scenario files and the command line are merged
and validated. Every value here should match the scenario's `run.ini`, except
where a CLI line says otherwise.

Some lines appear only when their inputs exist. From an RL training episode
with explicit traffic pairs, a coverage mission and one jammer:

```text
  traffic.topology    = explicit_pairs
  traffic.pair = ground-1,drone-1,1.5
  traffic.pair = ground-1,vehicle-1,1.5
  ...
  rl.avoid_node_collisions = true
  mission.kind = coverage
  mission.team_investigation = 0
  mission.team_radius_m = 50
  mission.team_delivery_target = 0.8
  mission.investigator_id = 
  mission.goal_xy = 345,300
  mission.coverage_domain = outdoor_probe_cells
  rl.control_mode     = centralized
  ...
  jammer_path_enabled = true
```

### Time and inputs

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`duration_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Simulated time.<div class="ms-key-note">A direct run evaluates ticks `0, tick_s, …` up to `floor(duration_s / tick_s) × tick_s`; an RL run uses the tick count resolved for the RL episode.</div></div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`tick_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Step between ticks.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`warmup_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Ticks with `time_s < warmup_s` are left out of `summary.json`. The CSVs still contain them.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`run_id`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">ns-3 RNG run number. Together with the seed it fixes every random draw.<div class="ms-key-note">`--run-id` overrides it.</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`nodes`<span class="ms-key-def">count</span></div>
<div class="ms-key-what">Nodes loaded from `nodes.json`.</div>
<div class="ms-key-vals">&ge; 2</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`buildings`<span class="ms-key-def">count</span></div>
<div class="ms-key-what">Buildings loaded from `buildings.json`; `0` when there is no file.<div class="ms-key-note">Any value above `0` switches LOS/NLOS to the buildings model.</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
</div>

### Radio

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`channel_model`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Propagation model family.</div>
<div class="ms-key-vals">`3gpp`, `nyu`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`scenario`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">The channel environment from `[channel] scenario`.<div class="ms-key-note">The header `scenario:` line is the scenario name.</div></div>
<div class="ms-key-vals">`UMi`, `UMa`, `RMa`, `InH`, `InF`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`frequency_ghz`<span class="ms-key-def">GHz</span></div>
<div class="ms-key-what">Carrier frequency.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`bandwidth_mhz`<span class="ms-key-def">MHz</span></div>
<div class="ms-key-what">Channel bandwidth. It sets the noise floor and capacity.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`tx_power_dbm`<span class="ms-key-def">dBm</span></div>
<div class="ms-key-what">Transmit power of every node.</div>
<div class="ms-key-vals">any number</div>
</div>
</div>

### Traffic and routing

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`traffic.model`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Flow demand over time.</div>
<div class="ms-key-vals">`constant`, `on_off`, `poisson`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`traffic.topology`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Which node pairs get flows.</div>
<div class="ms-key-vals">`all_pairs`, `random_pairs`, `gateway`, `explicit_pairs`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`traffic.pair = src,dst,demand`<span class="ms-key-def">ids, Mbps</span></div>
<div class="ms-key-what">One line per `explicit_pairs` entry, in file order.<div class="ms-key-note">Only with `explicit_pairs`.</div></div>
<div class="ms-key-vals">two node ids and a demand in Mbps</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`traffic.demand_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">Per-flow demand. Explicit pairs use their own demand instead.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`routing.algorithm`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Path search.</div>
<div class="ms-key-vals">`shortest_path`, `max_throughput`, `min_hop`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`routing.max_hops`<span class="ms-key-def">count</span></div>
<div class="ms-key-what">Longest path allowed.</div>
<div class="ms-key-vals">&ge; 0; `0` means no limit</div>
</div>
</div>

### Band

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`band`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Radio mode. Jammers act only in `sub-6`.</div>
<div class="ms-key-vals">`mmwave`, `sub-6`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`band_source`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Where `band` came from: `--band`, `[channel] band`, or neither.<div class="ms-key-note">`default` though you set the band means the key is not under `[channel]`. Put `band = sub-6` there, or pass `--band`.</div></div>
<div class="ms-key-vals">`cli`, `run.ini`, `default`</div>
</div>
</div>

### RL safety and output

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`rl.reward_type`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Reward after legacy names are normalized.</div>
<div class="ms-key-vals">a reward name</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.reward_alias`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">The legacy name you wrote, when it was normalized (`mean_sinr` becomes `all_links_los`).</div>
<div class="ms-key-vals">a reward name, or `none`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`output.viz_enabled`<span class="ms-key-def">boolean</span></div>
<div class="ms-key-what">`false` when `--no-viz` was passed: no CSVs in `seed-N/`.</div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.building_clearance_m`<span class="ms-key-def">m</span></div>
<div class="ms-key-what">Clearance kept around walls and roofs for RL moves.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.mask_building_moves`<span class="ms-key-def">flag</span></div>
<div class="ms-key-what">`1` masks RL moves into buildings.</div>
<div class="ms-key-vals">`1`, `0`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.unsafe_separation_m`<span class="ms-key-def">m</span></div>
<div class="ms-key-what">Node separation counted as unsafe.</div>
<div class="ms-key-vals">a distance</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.avoid_node_collisions`<span class="ms-key-def">boolean</span></div>
<div class="ms-key-what">Reject joint RL moves closer than `rl.unsafe_separation_m`.</div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
</div>

### Mission

These lines appear only when `[mission] kind` is not `none`.

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`mission.kind`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">The mission task.</div>
<div class="ms-key-vals">`coverage`, `investigation`, `recovery`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mission.team_investigation`<span class="ms-key-def">flag</span></div>
<div class="ms-key-what">Require the team near the goal.</div>
<div class="ms-key-vals">`1`, `0`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mission.team_radius_m`<span class="ms-key-def">m</span></div>
<div class="ms-key-what">Team radius around the goal.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mission.team_delivery_target`<span class="ms-key-def">fraction</span></div>
<div class="ms-key-what">Team delivery target.</div>
<div class="ms-key-vals">0 to 1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mission.investigator_id`<span class="ms-key-def">node id</span></div>
<div class="ms-key-what">The investigating node.</div>
<div class="ms-key-vals">a node id; empty when unset</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mission.goal_xy`<span class="ms-key-def">m</span></div>
<div class="ms-key-what">Goal position.</div>
<div class="ms-key-vals">`x,y`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mission.coverage_domain`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Fixed text.</div>
<div class="ms-key-vals">`outdoor_probe_cells`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node.failure_at_s.<id>`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">One line per node with a scheduled dropout.<div class="ms-key-note">Only for nodes that set `failure_at_s`, inside the mission block.</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
</div>

### RL control

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`rl.control_mode`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Resolved RL control.</div>
<div class="ms-key-vals">`disabled`, `centralized`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.reward_warmup`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">RL rewards skip warmup ticks.</div>
<div class="ms-key-vals">`exclude`, always</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.contract`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Bridge protocol name.<div class="ms-key-note">`none` unless RL is enabled by `--rl-mode` or `[rl] enabled = true`. `mesh_move_2d_v2` in a plain run means `[rl] enabled = true` in `run.ini`; set it to `false` for a direct run.</div></div>
<div class="ms-key-vals">`mesh_move_2d_v2`, `none`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.controlled_nodes`<span class="ms-key-def">node ids</span></div>
<div class="ms-key-what">Comma-separated controlled nodes, in action-slot order.</div>
<div class="ms-key-vals">node ids, or `(none)`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.max_controlled_nodes`<span class="ms-key-def">count</span></div>
<div class="ms-key-what">Resolved number of action slots.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.control_start_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Controlled nodes hold still until this time.</div>
<div class="ms-key-vals">0 to below `duration_s`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.decision_interval_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">`rl.decision_interval_ticks × tick_s`.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rl.decision_interval_ticks`<span class="ms-key-def">ticks</span></div>
<div class="ms-key-what">Ticks between RL decisions.</div>
<div class="ms-key-vals">a whole number of ticks</div>
</div>
</div>

### Jammer summary

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`jammers.configured`<span class="ms-key-def">count</span></div>
<div class="ms-key-what">Jammers in `jammers.json`.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`jammers.enabled`<span class="ms-key-def">count</span></div>
<div class="ms-key-what">Of those, how many have `enabled: true`.</div>
<div class="ms-key-vals">0 to `jammers.configured`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`jammer_path_enabled`<span class="ms-key-def">boolean</span></div>
<div class="ms-key-what">Whether jammer power enters SINR.<div class="ms-key-note">`true` only when `band = sub-6` and `jammers.enabled > 0`. `false` with jammers configured means `band` is `mmwave` or no jammer has `enabled: true`.</div></div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
</div>

**Not in run.log.** The AMC model (`amc_model`), noise figure, array gains,
`condition_model`, `blockage_enabled`, `viz_tick_ms` and jammer active
intervals are not logged. Read them from the archived `inputs/run.ini`; a key
you left out of `run.ini` took the default of the code that ran. Full list:
\ref src_io_run_record "What a run records".

## 5\. Jammers

Present only when `jammers.json` lists a jammer. One line per jammer, enabled
or not, in this form:

```text
  <id>: enabled=<bool> type=<type> target_freq_mhz=[<f1>, ...] tx_power_dbm=<dBm> tx_array_gain_dbi=<dBi> duty_cycle=<0-1> max_range_m=<m> beamwidth_deg=<deg> azimuth_deg=<deg> zenith_deg=<deg> motion=<waypoints|velocity|static>
```

Each field repeats the jammer's value from \ref files_jammers_json "jammers.json",
which explains them. Two are derived:

<div class="ms-keys ms-c-amber">
<div class="ms-key ms-key-head"><div>Line</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`<id>`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">The jammer's `id`.</div>
<div class="ms-key-vals">any text; `(unnamed)` when the jammer has no id</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`motion`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">How the jammer moves.<div class="ms-key-note">`waypoints` when the jammer has waypoints, else `velocity` when any velocity component is non-zero, else `static`.</div></div>
<div class="ms-key-vals">`waypoints`, `velocity`, `static`</div>
</div>
</div>

## 6\. console.log

Runs launched by Python tools also keep the simulator's console output:

| Launcher | Location |
|---|---|
| `scripts.sweep` | `<sweep folder>/point-NNN/console.log` |
| `scripts.validation.run_batch` | `<batch>/<scenario>/console.log`, beside that scenario's `run.log` |
| `scripts.validation.regression_check`, `smoke_check` | `<out>/console.log`, `<out>/run-1/console.log`, `<out>/run-2/console.log` |
| RL episodes (`scripts/rl`) | `episode-NNNN/sim_stderr.log` (stderr only) |
| A direct run | Not saved; it prints to your terminal |

The first line is `Command: <the full command>`, then a blank line, then
everything the simulator printed to stdout and stderr, in order:

| Line | When |
|---|---|
| `Loading config: <path>` | Start. |
| `Scenario '<name>' seeds=<n> duration=<s>s tick=<s>s nodes=<n> buildings=<n>` | After validation. |
| `=== Seed <N> (<i>/<n>) ===` | Start of each seed. |
| `  t=0.100s  links=1  flows=3  routable=1  demand=30.0  delivered=10.0 Mbps` | Every tick, warmup included. `links` counts node pairs with SINR ≥ −6.7 dB; `demand` and `delivered` are sums over all flows (Mbps). |
| `[seed 1] 0.2s / 5.0s (4%)  wall=0.0s  ETA~0.0s` | About every 1/20 of the run, plus the final 100% line. |
| `[MetricsWriter] Summary written to <path>` | End of each seed. |
| `Seed <N> complete (wall=<s>s).` | End of each seed. |
| `All <n> seeds complete. Output: <dir>` | End, only with more than one seed. |
| `Error loading config: …`, `Config error: …`, `Error archiving inputs: …` | Failures before `run.log` is written. |

The `Loading config`, `Scenario`, `===`, `t=` and `complete` lines are ns-3
`NS_LOG` output; a build with ns-3 logging disabled (the `optimized` profile)
omits them. `--debug-links` adds per-link `LinkEvaluator` and `LinkTable`
lines.

## 7\. Reading it

Normal: `timestamp` matches when you ran it, `seeds` lists what you asked for,
and every `Resolved config` value matches the scenario's `run.ini` except where
a CLI line says otherwise.

A problem looks like:

- No `run.log` in the output folder: the run stopped at `Error loading config:`
  or `Config error:` (read the console or `console.log` and fix the reported
  key), or it was a `--channel-query` run.
- `run.log` present but `seed-N/` missing or without `summary.json`: the run
  failed inside a seed, after the log was written
  (\ref src_io_failures "Failure behavior").
- A value you set is missing: that key is not logged; check `inputs/run.ini`.

Show the resolved settings:

```bash
sed -n '/^Resolved config:/,$p' outputs/getting-started/01-static-los-baseline/run.log
```

What changed between two runs (here the "Change one setting" pair):

```bash
diff <(sed -n '/^Resolved config:/,$p' outputs/getting-started/01-static-los-baseline/run.log) \
     <(sed -n '/^Resolved config:/,$p' outputs/getting-started/01-demand-6000/run.log)
```

```text
15c15
<   traffic.demand_mbps = 10
---
>   traffic.demand_mbps = 6000
```

Line numbers count from `Resolved config:`. An empty diff means the two runs
used the same logged settings; compare `inputs/run.ini` for the unlogged ones.

## 8\. Related

- \ref files_run_ini "run.ini": every key that feeds the `Resolved config` block.
- \ref src_io_run_record "What a run records": what a run keeps and what it does not.
- \ref src_io_failures "Failure behavior": which failures leave a `run.log` behind.
- \ref src_io_output "Output files": `WriteRunLog` in `src/io/run-logger.h` writes this file, called once by `sim.cc`.
- \ref src_cli "src/cli": the flags in `CLI overrides`.
- \ref scripts_validation "scripts/validation": `regression_snapshot.py` leaves this file out.
- \ref mesh_sim_first_result "Understand the result": checking `run.log` first.

Previous: \ref files_jammers_json "jammers.json" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_summary_json "summary.json"
