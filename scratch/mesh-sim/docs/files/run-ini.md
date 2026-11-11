# run.ini {#files_run_ini}

[TOC]

`run.ini` is a scenario's settings file: how long it runs, the radio, the
traffic, the routing, and which node, building and jammer files to load. It
sits in the scenario folder, `--run-config` points at it, and every run keeps a
copy in `<output>/inputs/run.ini`.

\htmlonly
<div class="ms-find" data-noun="key"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search keys, e.g. tick, jammer, seed" aria-label="Search keys"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

The file from \ref mesh_sim_first_run "Your first run",
`inputs/baselines/01-static-los-baseline/run.ini`, section by section:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-sec-scenario">
<pre class="ms-ini-code"><b>[scenario]</b>
name           = 01-static-los-baseline
seed           = 1
run_id         = 1
duration_s     = 5.0
warmup_s       = 0.0
tick_s         = 0.1
nodes_file     = nodes.json
buildings_file =</pre>
<div class="ms-ini-note"><strong>Time and input files</strong>A 5 s run in 0.1 s ticks (51 ticks), seed 1, with the two nodes from <code>nodes.json</code> and no buildings.</div>
</div>
<div class="ms-ini-row ms-sec-channel">
<pre class="ms-ini-code"><b>[channel]</b>
frequency_ghz    = 28.0
tx_power_dbm     = 30.0
scenario         = RMa
channel_model    = 3gpp
blockage_enabled = false
bandwidth_mhz    = 400.0
noise_figure_db  = 5.0</pre>
<div class="ms-ini-note"><strong>Radio and propagation</strong>A 28 GHz, 400 MHz link with the 3GPP rural-macro model. Keys left out take their defaults: random LOS/NLOS, Shannon capacity, 12 dBi antennas, <code>mmwave</code> band.</div>
</div>
<div class="ms-ini-row ms-sec-traffic">
<pre class="ms-ini-code"><b>[traffic]</b>
model          = constant
demand_mbps    = 10.0
flow_topology  = all_pairs</pre>
<div class="ms-ini-note"><strong>Who sends what</strong>One flow, <code>node-a</code> to <code>node-b</code>, asking for 10 Mbps for the whole run.</div>
</div>
<div class="ms-ini-row ms-sec-routing">
<pre class="ms-ini-code"><b>[routing]</b>
algorithm = shortest_path
max_hops  = 5</pre>
<div class="ms-ini-note"><strong>How flows find a path</strong>The highest-capacity route, at most 5 hops. With two nodes it is the direct link.</div>
</div>
<div class="ms-ini-row ms-sec-output">
<pre class="ms-ini-code"><b>[output]</b>
viz_tick_ms = 100</pre>
<div class="ms-ini-note"><strong>Where results go</strong>A CSV row every 100 ms. No <code>dir</code>, so results go to a timestamped folder unless you pass <code>&#45;&#45;output-dir</code>.</div>
</div>
</div>
\endhtmlonly

Two more sections appear in other scenarios: `[nyu_channel]` for the NYU
channel model, and the RL and placement sections (section 9).

**Format.** One `[section]` header per group, one `key = value` per line.
Every key is optional; a key you leave out takes its default. After a run,
`run.log` lists the values the simulator actually used
(\ref files_run_log "run.log").

<details class="ms-more"><summary>All format rules <span class="ms-more-count">(9)</span></summary>

| Rule | What it means |
|---|---|
| `#` or `;` starts a comment, anywhere on a line | Inline comments work. A value cannot contain `#` or `;`. |
| Spaces around keys and values are ignored | `seed=1` and `seed   =   1` are the same. |
| A key repeated in one section | The last one wins. |
| Values are case-sensitive | `scenario = UMi` works; `Umi` is rejected. |
| Booleans | `true`, `1` or `yes` (any case) mean true. Anything else, such as `on` or the typo `ture`, means false, with no error. |
| Numbers | A blank or non-numeric value stops the load with `stod: no conversion`. |
| Unknown keys and sections | Ignored, except in `[channel_query]`. A misspelled key keeps its default. |
| File paths | Relative to the folder that holds `run.ini`. |
| One line per key | The `pairs` JSON must fit on one line. |

</details>

## 2\. [scenario]: time and input files {#files_run_ini_scenario}

How long the run lasts, how it is sliced into ticks, its random seed, and the
other input files.

<div class="ms-keys ms-sec-scenario">
<div class="ms-key ms-key-head"><div>Key</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`name`<span class="ms-key-def">default `unnamed`</span></div>
<div class="ms-key-what">A label for the run. It appears in `run.log`, `summary.json` and the `positions.csv` header.</div>
<div class="ms-key-vals">any text</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`seed`<span class="ms-key-def">default `42`</span></div>
<div class="ms-key-what">The random seed. Each seed is an independent repeat of the run and writes its own `seed-<N>/` folder.<div class="ms-key-note">Shadowing and the random LOS/NLOS draws change with the seed. `0` aborts the run with `invalid Seed 0`. Sets ns-3's `RngSeedManager::SetSeed`.</div></div>
<div class="ms-key-vals">an integer from 1 to 4294944442<span class="ms-key-cli">or <code>&#45;&#45;seeds</code>, <code>&#45;&#45;seed</code> on the command line</span></div>
</div>
<div class="ms-key">
<div class="ms-key-name">`run_id`<span class="ms-key-def">default `1`</span></div>
<div class="ms-key-what">A second random-stream number: the same seed with a different `run_id` gives another independent run.<div class="ms-key-note">Sets ns-3's `RngSeedManager::SetRun`.</div></div>
<div class="ms-key-vals">an integer &ge; 0<span class="ms-key-cli">or <code>&#45;&#45;run-id</code> on the command line</span></div>
</div>
<div class="ms-key">
<div class="ms-key-name">`duration_s`<span class="ms-key-def">default `10.0` s</span></div>
<div class="ms-key-what">How long the run lasts, in simulated seconds.<div class="ms-key-note">The run has `floor(duration_s / tick_s) + 1` ticks, starting at t = 0. The division is in floating point, so `duration_s = 0.3` with `tick_s = 0.1` ends at 0.2 s. Pick values with an exact ratio, such as 5.0 and 0.1.</div></div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`warmup_s`<span class="ms-key-def">default `0.0` s</span></div>
<div class="ms-key-what">Leaves the first seconds out of the `summary.json` averages.<div class="ms-key-note">The CSVs still have every tick, and RL rewards still count the warm-up.</div></div>
<div class="ms-key-vals">&ge; 0 and less than `duration_s`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`tick_s`<span class="ms-key-def">default `0.1` s</span></div>
<div class="ms-key-what">The time step. Every tick the simulator re-evaluates every link, updates the traffic and reroutes.<div class="ms-key-note">ns-3 mobility moves the nodes continuously; the simulator looks at them once per tick.</div></div>
<div class="ms-key-vals">&gt; 0 and no more than `duration_s`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`nodes_file`<span class="ms-key-def">default `nodes.json`</span></div>
<div class="ms-key-what">The node file: \ref files_nodes_json "nodes.json".</div>
<div class="ms-key-vals">a path to a JSON file with at least 2 nodes</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`buildings_file`<span class="ms-key-def">default blank</span></div>
<div class="ms-key-what">The building file: \ref files_buildings_json "buildings.json". Blank means no buildings.<div class="ms-key-note">With any building in the file, every link's LOS/NLOS comes from geometry instead of a random draw, and `condition_reason` in `links.csv` reads `building`.</div></div>
<div class="ms-key-vals">blank, or a path to a JSON file</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`jammers_file`<span class="ms-key-def">default blank</span></div>
<div class="ms-key-what">The jammer file: \ref files_jammers_json "jammers.json". Blank means no jammers.<div class="ms-key-note">Jammer power counts only when `[channel] band = sub-6`.</div></div>
<div class="ms-key-vals">blank, or a path to a JSON file</div>
</div>
</div>

## 3\. [channel]: radio and propagation {#files_run_ini_channel}

The radio and the propagation model. How these keys turn into path loss, SINR
and capacity is on \ref files_channel_models "Channel models".

<div class="ms-keys ms-sec-channel">
<div class="ms-key ms-key-head"><div>Key</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`band`<span class="ms-key-def">default `mmwave`</span></div>
<div class="ms-key-what">The simulator mode. Jammers count only in `sub-6`.<div class="ms-key-note">It is never inferred from `frequency_ghz`. The order is `--band`, then this key, then `mmwave`; `run.log` shows the result as `band` and `band_source`.</div></div>
<div class="ms-key-vals">`mmwave`, `sub-6`<span class="ms-key-cli">or <code>&#45;&#45;band</code> on the command line</span></div>
</div>
<div class="ms-key">
<div class="ms-key-name">`frequency_ghz`<span class="ms-key-def">default `28.0` GHz</span></div>
<div class="ms-key-what">The carrier frequency.<div class="ms-key-note">Above 30 GHz, 3GPP `RMa` stops a debug build with `NS_ASSERT failed, cond="m_frequency <= 30.0e9"`. The frequency also sets the free-space loss floor.</div></div>
<div class="ms-key-vals">&gt; 0. The models are defined for 0.5&ndash;100 GHz (3GPP), 0.5&ndash;30 GHz (3GPP `RMa`) and 0.5&ndash;150 GHz (NYU).</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`tx_power_dbm`<span class="ms-key-def">default `30.0` dBm</span></div>
<div class="ms-key-what">Transmit power of every mesh node.</div>
<div class="ms-key-vals">any number</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`scenario`<span class="ms-key-def">default `UMi`</span></div>
<div class="ms-key-what">The environment: urban street (`UMi`), urban macro (`UMa`), rural (`RMa`), indoor office (`InH`) or indoor factory (`InF`).<div class="ms-key-note">`InF` works only with `channel_model = nyu`; with `3gpp` the run stops with `Unknown 3GPP scenario 'InF'`. What each environment assumes: \ref files_channel_models "Channel models".</div></div>
<div class="ms-key-vals">`UMi`, `UMa`, `RMa`, `InH`, `InF`, exact case</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`channel_model`<span class="ms-key-def">default `3gpp`</span></div>
<div class="ms-key-what">The propagation-model family: 3GPP TR 38.901 or NYU.<div class="ms-key-note">`nyu` also reads the `[nyu_channel]` section (section 4).</div></div>
<div class="ms-key-vals">`3gpp`, `nyu`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`condition_model`<span class="ms-key-def">default `auto`</span></div>
<div class="ms-key-what">How each link is made LOS or NLOS. `auto` draws it at random from the scenario's LOS probability; `static_los` makes every link LOS.<div class="ms-key-note">Buildings override both. `auto` draws once per node pair per seed and keeps that result for the whole run, even when nodes move.</div></div>
<div class="ms-key-vals">`auto`, `static_los`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`amc_model`<span class="ms-key-def">default `shannon`</span></div>
<div class="ms-key-what">How SINR becomes capacity. `shannon` uses the Shannon formula; `table` the 3GPP CQI table; `silvus` the Silvus radio's MCS table.<div class="ms-key-note">`table` tops out at 6.23 bit/s/Hz (2,492 Mbps at 400 MHz); `silvus` has MCS 0&ndash;6. This key is not checked at load: another value stops the run at the first usable link with `Unknown amc_model`.</div></div>
<div class="ms-key-vals">`shannon`, `table`, `silvus`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`bandwidth_mhz`<span class="ms-key-def">default `400.0` MHz</span></div>
<div class="ms-key-what">The channel bandwidth. It sets the noise floor and scales capacity.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`noise_figure_db`<span class="ms-key-def">default `5.0` dB</span></div>
<div class="ms-key-what">The receiver noise figure, added to the noise floor.<div class="ms-key-note">Noise floor = &minus;174 + 10 log10(bandwidth in Hz) + noise figure: &minus;83.0 dBm for 400 MHz and 5 dB.</div></div>
<div class="ms-key-vals">any number</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`tx_array_gain_dbi`<span class="ms-key-def">default `12.0` dBi</span></div>
<div class="ms-key-what">Transmit antenna gain of every node that does not set its own in `nodes.json`.<div class="ms-key-note">Each node pair is evaluated once, with the node listed first in `nodes.json` as transmitter: the link uses that node's transmit gain and the other node's receive gain.</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rx_array_gain_dbi`<span class="ms-key-def">default `12.0` dBi</span></div>
<div class="ms-key-what">Receive antenna gain, with the same per-node override.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
</div>

`blockage_enabled` (default `true`) and `beamforming_model` (default `svd`) are
read but have no effect. Use `buildings_file` for blockage.

## 4\. [nyu_channel]: NYU model extras {#files_run_ini_nyu}

Read only when `channel_model = nyu`. A debug build stops at the start of each
seed when a value is outside its range. Measured effects of each key:
\ref files_channel_models_nyu "NYU settings".

<div class="ms-keys ms-sec-nyu">
<div class="ms-key ms-key-head"><div>Key</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`shadowing_enabled`<span class="ms-key-def">default `true`</span></div>
<div class="ms-key-what">Random log-normal shadow fading on every link.</div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`atmospheric_loss_enabled`<span class="ms-key-def">default `false`</span></div>
<div class="ms-key-what">Turns on the weather model. The rain, humidity, temperature and pressure keys do nothing while it is `false`.</div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rain_rate_mm_hr`<span class="ms-key-def">default `0.0` mm/h</span></div>
<div class="ms-key-what">Rain attenuation.</div>
<div class="ms-key-vals">0&ndash;150</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`humidity_pct`<span class="ms-key-def">default `50.0` %</span></div>
<div class="ms-key-what">Water-vapor absorption. Above 99.5 % it also adds fog.</div>
<div class="ms-key-vals">0&ndash;100</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`temperature_c`<span class="ms-key-def">default `20.0` &deg;C</span></div>
<div class="ms-key-what">Air temperature. At 0 &deg;C or below the model switches to ice.</div>
<div class="ms-key-vals">&minus;100 to 50</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`pressure_mbar`<span class="ms-key-def">default `1013.25` mbar</span></div>
<div class="ms-key-what">Air pressure. The default is also the maximum.</div>
<div class="ms-key-vals">1e-5 to 1013.25</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`foliage_loss_enabled`<span class="ms-key-def">default `false`</span></div>
<div class="ms-key-what">Adds loss through vegetation.<div class="ms-key-note">The vegetation depth is redrawn at random every tick, up to the full link length. At the default 0.4 dB/m over 500 m, the median SINR change is &minus;97 dB.</div></div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`foliage_loss_db_m`<span class="ms-key-def">default `0.4` dB/m</span></div>
<div class="ms-key-what">Loss per meter of vegetation.</div>
<div class="ms-key-vals">0&ndash;10</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`o2i_loss_type`<span class="ms-key-def">default `Low Loss`</span></div>
<div class="ms-key-what">Outdoor-to-indoor loss class, for a link with one node inside a building.</div>
<div class="ms-key-vals">`Low Loss`, `High Loss`, with the space</div>
</div>
</div>

`rf_bandwidth_mhz` (default `800.0`) is read but has no effect.

## 5\. [traffic]: who sends what {#files_run_ini_traffic}

Traffic is flow-level: a flow is a source, a destination and a requested rate
in Mbps, with no packets. `model` decides how flows behave over time;
`flow_topology` decides which flows exist. \ref files_traffic "Traffic" runs
each setting on a small network.

<div class="ms-keys ms-sec-traffic">
<div class="ms-key ms-key-head"><div>Key</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`model`<span class="ms-key-def">default `constant`</span></div>
<div class="ms-key-what">How flows behave over time. `constant`: they start at t = 0 and stay on. `poisson`: the same, plus random new flows. `on_off`: they switch between sending and silent.</div>
<div class="ms-key-vals">`constant`, `poisson`, `on_off`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`demand_mbps`<span class="ms-key-def">default `10.0` Mbps</span></div>
<div class="ms-key-what">The rate each active flow asks for (the rate while ON for `on_off`).<div class="ms-key-note">It is checked even when `explicit_pairs` gives every flow its own rate.</div></div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`flow_topology`<span class="ms-key-def">default `all_pairs`</span></div>
<div class="ms-key-what">Which flows exist at t = 0 (table below).</div>
<div class="ms-key-vals">`all_pairs`, `random_pairs`, `gateway`, `explicit_pairs`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`random_pair_count`<span class="ms-key-def">default `3`</span></div>
<div class="ms-key-what">For `random_pairs`: how many flows.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`gateway_node_id`<span class="ms-key-def">default blank</span></div>
<div class="ms-key-what">For `gateway`: the node every flow goes to. Required for `gateway`.</div>
<div class="ms-key-vals">an `id` from `nodes.json`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`pairs`<span class="ms-key-def">default `[]`</span></div>
<div class="ms-key-what">For `explicit_pairs`: the flows, as a JSON array on one line.<div class="ms-key-note">`src` and `dst` are node ids and must differ; `demand_mbps` is finite and &gt; 0; each direction of a pair appears at most once. Example: `pairs = [{"src":"node-a","dst":"node-b","demand_mbps":6}]`. Full rules: \ref src_config_traffic_pairs "Explicit traffic pairs".</div></div>
<div class="ms-key-vals">`[{"src": "<id>", "dst": "<id>", "demand_mbps": <Mbps>}, ...]`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`arrival_rate_hz`<span class="ms-key-def">default `1.0` flows/s</span></div>
<div class="ms-key-what">For `poisson`: how many new flows start per second, on average.<div class="ms-key-note">Each tick adds a Poisson(`arrival_rate_hz` &times; `tick_s`) number of flows between two random nodes, whatever `flow_topology` says.</div></div>
<div class="ms-key-vals">any number; 0 or less means none</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`on_time_s`, `off_time_s`<span class="ms-key-def">default `1.0` s each</span></div>
<div class="ms-key-what">For `on_off`: the average length of the ON and OFF periods. Every flow starts ON and asks for nothing while OFF.<div class="ms-key-note">Each period length is drawn from an exponential distribution with this mean.</div></div>
<div class="ms-key-vals">&ge; 0, not both 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`holding_time_s`<span class="ms-key-def">default `0.0` s</span></div>
<div class="ms-key-what">How long each flow lasts. 0 or less means flows never end.<div class="ms-key-note">Flows from t = 0 end exactly this long after they start; `poisson` arrivals last a random time with this mean. Ended flows are removed.</div></div>
<div class="ms-key-vals">any number</div>
</div>
</div>

| `flow_topology` | Flows at t = 0 |
|---|---|
| `all_pairs` | One per node pair, N(N&minus;1)/2 in total, from the node listed first in `nodes.json` to the later one. |
| `random_pairs` | `random_pair_count` flows between random nodes. Repeats are possible. |
| `gateway` | One from every other node to `gateway_node_id`, N&minus;1 in total. |
| `explicit_pairs` | Exactly the flows in `pairs`, each at its own rate. Needs `model = constant`. |

## 6\. [routing]: how flows find a path {#files_run_ini_routing}

Every tick, each flow gets a path over the links that can carry traffic
(SINR &ge; &minus;6.7 dB). \ref files_routing "Routing" sends one request
through each algorithm.

<div class="ms-keys ms-sec-routing">
<div class="ms-key ms-key-head"><div>Key</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`algorithm`<span class="ms-key-def">default `shortest_path`</span></div>
<div class="ms-key-what">The rule for choosing a path (table below).</div>
<div class="ms-key-vals">`shortest_path`, `max_throughput`, `min_hop`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`max_hops`<span class="ms-key-def">default `5`</span></div>
<div class="ms-key-what">The longest path allowed. A flow whose path is longer gets no route for that tick.<div class="ms-key-note">The limit is checked after the path is chosen: `shortest_path` and `max_throughput` do not look for a shorter path that fits.</div></div>
<div class="ms-key-vals">an integer &ge; 0; `0` means no limit</div>
</div>
</div>

| `algorithm` | Path chosen |
|---|---|
| `shortest_path` | The path with the least total 1 / capacity. A relay over two strong links can beat a weak direct link. |
| `max_throughput` | The path whose weakest link is strongest. |
| `min_hop` | The fewest hops, whatever the capacity. |

- When the flows on a link ask for more than its capacity, each one is scaled
  by capacity / total demand. A link's two directions share one capacity.
- A flow's latency is 0.5 ms per hop plus distance / speed of light.

## 7\. [output]: where results go {#files_run_ini_output}

<div class="ms-keys ms-sec-output">
<div class="ms-key ms-key-head"><div>Key</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`dir`<span class="ms-key-def">default blank</span></div>
<div class="ms-key-what">The output folder. Blank means `scratch/mesh-sim/outputs/YYYY-MM/DD/HH-MM-SS/`, in local time.<div class="ms-key-note">A blank `dir` needs `run.ini` to be inside `scratch/mesh-sim/`, even when you pass `--output-dir`: the automatic path is worked out first.</div></div>
<div class="ms-key-vals">blank, or a path relative to `run.ini`<span class="ms-key-cli">or <code>&#45;&#45;output-dir</code> on the command line</span></div>
</div>
<div class="ms-key">
<div class="ms-key-name">`viz_tick_ms`<span class="ms-key-def">default `100` ms</span></div>
<div class="ms-key-what">How often a row is written to the six CSVs.<div class="ms-key-note">A value at or below `tick_s` writes every tick. `summary.json` always uses every tick.</div></div>
<div class="ms-key-vals">an integer &ge; 0</div>
</div>
</div>

## 8\. Common changes

Each change below is one edit to a copy of a scenario. The numbered scenarios in
\ref inputs_baselines "inputs/baselines" each make one of them.

| To | Set | What you'll see |
|---|---|---|
| Run longer, in coarser steps | `duration_s = 120.0`, `tick_s = 0.5`, and `[output] viz_tick_ms = 500` | 241 ticks, one CSV row every 0.5 s. Example: `02-distance-sweep`. |
| Keep start-up out of the averages | `warmup_s = 1.0` | `summary.json` averages start at 1 s; the CSVs are unchanged. |
| Repeat with other random draws | `--seeds=1,2,3` on the command line | `seed-1/`, `seed-2/`, `seed-3/`, with different LOS/NLOS and shadowing. Example: `15-umi-los-probability`. |
| Block links with buildings | `buildings_file = buildings.json` | LOS/NLOS follows the geometry. Example: `03-building-blockage`. |
| Make every link LOS | `condition_model = static_los` | No random NLOS draws. Example: `p0-jammer-smoke`. |
| Model a city street | `scenario = UMi` | LOS probability 0.23 at 100 m: seeds 1&ndash;10 gave 3 LOS links, and the NLOS ones lose 9&ndash;26 dB. Example: `15-umi-los-probability`. |
| Use the NYU model | `channel_model = nyu` | A LOS link at 500 m (RMa) gets 11.9 dB SINR; 3GPP gives 21.6 dB. Example: `04-nyu-vs-3gpp`. |
| Cap capacity at real MCS rates | `amc_model = table` | 2,492 Mbps at 400 MHz instead of 4,604. Example: `06-mcs-table-mode`. |
| Model a Silvus radio | `amc_model = silvus`, `bandwidth_mhz = 20.0` | Capacity steps from 6.5 to 58.5 Mbps; MCS 0&ndash;6. |
| Weaken every link | `tx_power_dbm = 10.0` | 20 dB less SINR; longer links fail and traffic relays. Example: `14-max-hops-limit`. |
| Add a jammer | `band = sub-6`, `frequency_ghz = 2.4`, and `[scenario] jammers_file = jammers.json` | SINR falls while the jammer is on. Example: `p0-jammer-smoke`. |
| Add rain | `atmospheric_loss_enabled = true`, `rain_rate_mm_hr = 25.0` | 2.1 dB less SINR over 500 m. Example: `05-nyu-atmosphere`. |
| Send all traffic to one sink | `flow_topology = gateway`, `gateway_node_id = gw` | N&minus;1 flows into `gw`. Example: `12-gateway-topology`. |
| Overload the network | `demand_mbps = 2000.0` | Flows on a full link are scaled down equally. Example: `09-congestion-bottleneck`. |
| Make traffic bursty | `model = on_off`, `on_time_s = 2.0`, `off_time_s = 2.0` | The delivered rate switches between 0 and the demand. Example: `10-on-off-traffic`. |
| Make flows come and go | `model = poisson`, `arrival_rate_hz = 2.0`, `holding_time_s = 3.0` | New flows appear and expire during the run. Example: `11-poisson-arrivals`. |
| Set exact flows and rates | `flow_topology = explicit_pairs`, `pairs = [...]` on one line | Only the listed flows, each at its own rate. |
| Route over the strongest path | `algorithm = max_throughput` | Strong two-hop paths win over weak direct links. Example: `08-max-throughput-routing`. |
| Limit relaying | `max_hops = 3` | Flows that need more hops get no route. Example: `14-max-hops-limit`. |
| Fix the output folder | `dir = results` | Results in `results/` next to `run.ini`. |

## 9\. RL and placement sections

These sections serve the RL and placement tools and do nothing in a plain run.
Every key: \ref src_config_run_ini_reference "run.ini reference".

| Section | Used for | Off when |
|---|---|---|
| `[rl]` | A Python agent moving nodes over the stdin/stdout bridge: controlled nodes, movement limits, decision interval, reward, safety rules, live coverage (\ref src_rl "src/rl"). | `enabled = false` and no `--rl-mode` |
| `[baseline]` | A placement planner, `geometric` or `optimization`, with its objective and costs. The simulator reads only `algorithm`; `scripts/baselines/` reads the rest (\ref scripts_baselines "scripts/baselines"). | `algorithm = none` |
| `[channel_query]` | Time and size limits for the `--channel-query` worker (\ref src_query "src/query"). Unknown keys here are errors. | no `--channel-query` |
| `[mission]` | Mission tasks for centralized RL: `coverage`, `investigation` or `recovery`, with a goal and success thresholds. | `kind = none` |

`[placement_objective]`, `[placement_optimizer]` and `[channel_query_client]`
are read only by the Python placement planners
(\ref scripts_baselines_planners "planners").

## 10\. Related

- \ref files_channel_models "Channel models: 3GPP and NYU": what the `[channel]` and `[nyu_channel]` keys do to a link
- \ref files_traffic "Traffic" and \ref files_routing "Routing": what the `[traffic]` and `[routing]` keys do, on a worked example
- \ref files_nodes_json "nodes.json", \ref files_buildings_json "buildings.json", \ref files_jammers_json "jammers.json": the files `run.ini` names
- \ref files_run_log "run.log": the values a run actually used
- \ref src_config_run_ini_reference "run.ini reference": every key, including `[rl]`, `[baseline]`, `[channel_query]` and `[mission]`
- \ref src_cli "src/cli": command-line flags that override `run.ini`
- \ref inputs_baselines "inputs/baselines": the example scenarios named above
- \ref mesh_sim_change_one_setting "Change one setting": a worked edit of this file

Previous: \ref mesh_sim_files "Input and output files" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_channel_models "Channel models: 3GPP and NYU"
