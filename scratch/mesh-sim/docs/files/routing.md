# Routing {#files_routing}

[TOC]

Every tick, once the links are evaluated, the router gives each flow a path
over the links that can carry traffic. `[routing] algorithm` in
\ref files_run_ini "run.ini" picks the rule. This page sends one request
through the same five nodes under each rule.

## 1\. The example

`src` asks for 1,000 Mbps to `dst`. A building sits between them. Relays wait
on both sides: `n1` to the north, `s1` and `s2` to the south. The labels are
link capacities in Mbps.

\htmlonly
<div class="ms-flow-art ms-scene ms-c-blue"><svg viewBox="0 0 520 440" role="img" aria-label="Five nodes around a building. Strong LOS links go around it to the north through n1 and to the south through s1 and s2; the direct src to dst link crosses the building."><rect class="ms-bldg" x="200" y="186" width="120" height="120" rx="2"/><text x="260" y="294" text-anchor="middle">building</text><line class="ms-bad" x1="80" y1="246" x2="440" y2="246"/><text x="260" y="236" text-anchor="middle" class="ms-strong">206</text><line class="ms-ink ms-thin" x1="80" y1="246" x2="260" y2="66"/><text x="136" y="148" text-anchor="middle" class="ms-strong">3,862</text><line class="ms-ink ms-thin" x1="80" y1="246" x2="152" y2="366"/><text x="82" y="312" text-anchor="middle" class="ms-strong">4,552</text><line class="ms-faint" x1="80" y1="246" x2="368" y2="366"/><line class="ms-ink ms-thin" x1="260" y1="66" x2="440" y2="246"/><text x="384" y="148" text-anchor="middle" class="ms-strong">3,862</text><line class="ms-faint" x1="152" y1="366" x2="440" y2="246"/><line class="ms-ink ms-thin" x1="368" y1="366" x2="440" y2="246"/><text x="440" y="312" text-anchor="middle" class="ms-strong">4,552</text><line class="ms-faint" x1="260" y1="66" x2="152" y2="366"/><line class="ms-faint" x1="260" y1="66" x2="368" y2="366"/><line class="ms-ink ms-thin" x1="152" y1="366" x2="368" y2="366"/><text x="260" y="386" text-anchor="middle" class="ms-strong">4,051</text><circle class="ms-dot" cx="80" cy="246" r="7"/><text x="56" y="232" text-anchor="middle" class="ms-strong">src</text><circle class="ms-dot" cx="440" cy="246" r="7"/><text x="464" y="232" text-anchor="middle" class="ms-strong">dst</text><circle class="ms-dot" cx="260" cy="66" r="7"/><text x="260" y="52" text-anchor="middle" class="ms-strong">n1</text><circle class="ms-dot" cx="152" cy="366" r="7"/><text x="152" y="392" text-anchor="middle" class="ms-strong">s1</text><circle class="ms-dot" cx="368" cy="366" r="7"/><text x="368" y="392" text-anchor="middle" class="ms-strong">s2</text></svg></div>
\endhtmlonly

```ini
[scenario]
buildings_file    = buildings.json   ; one 100 × 100 × 20 m block
[channel]
scenario          = UMi
channel_model     = nyu
[nyu_channel]
shadowing_enabled = false
[traffic]
flow_topology     = explicit_pairs
pairs             = [{"src":"src","dst":"dst","demand_mbps":1000}]
[routing]
algorithm         = shortest_path   ; then max_throughput, then min_hop
max_hops          = 5
```

All five nodes are fixed at 10 m. With NYU shadowing off and the building
deciding LOS, every number on this page is the same on every tick and seed.
The three algorithms pick three different paths.

## 2\. Which links can carry traffic

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-grey">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><line class="ms-ink ms-thin" x1="20" y1="70" x2="70" y2="20"/><line class="ms-ink ms-thin" x1="70" y1="20" x2="120" y2="70"/><line class="ms-bad" x1="20" y1="70" x2="120" y2="70"/><circle class="ms-dot" cx="20" cy="70" r="6"/><circle class="ms-dot" cx="70" cy="20" r="6"/><circle class="ms-dot" cx="120" cy="70" r="6"/><text x="70" y="88" text-anchor="middle">weak, still usable</text></svg></div>
<div class="ms-flow-body"><p>The router sees each link&rsquo;s capacity from this tick&rsquo;s channel calculation (<a href="files_channel_models.html">Channel models</a>). Any link with capacity above 0, meaning SINR &ge; &minus;6.7 dB, can carry traffic. A link&rsquo;s two directions share one capacity.</p></div>
</div>
\endhtmlonly

| Link | Distance | | SINR | Capacity |
|---|---|---|---|---|
| src–s1 | 117 m | LOS | 34.3 dB | 4,552 Mbps |
| s2–dst | 117 m | LOS | 34.3 dB | 4,552 Mbps |
| s1–s2 | 180 m | LOS | 30.5 dB | 4,051 Mbps |
| src–n1 | 212 m | LOS | 29.1 dB | 3,862 Mbps |
| n1–dst | 212 m | LOS | 29.1 dB | 3,862 Mbps |
| src–s2 | 260 m | NLOS | −1.7 dB | 299 Mbps |
| s1–dst | 260 m | NLOS | −1.7 dB | 299 Mbps |
| n1–s1 | 266 m | NLOS | −2.0 dB | 283 Mbps |
| n1–s2 | 266 m | NLOS | −2.0 dB | 283 Mbps |
| src–dst | 300 m | NLOS | −3.7 dB | 206 Mbps |

The direct `src`–`dst` link crosses the building: NLOS, −3.7 dB, 206 Mbps.
Weak, but above the cut-off, so every algorithm may use it. The four other
NLOS links are just as weak and never help here.

## 3\. shortest_path: least total 1/C

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-blue">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><line class="ms-ink" x1="16" y1="60" x2="62" y2="24"/><line class="ms-ink" x1="62" y1="24" x2="124" y2="60"/><circle class="ms-dot" cx="16" cy="60" r="5"/><circle class="ms-dot" cx="62" cy="24" r="5"/><circle class="ms-dot" cx="124" cy="60" r="5"/><text x="30" y="36" text-anchor="middle">1/C</text><text x="104" y="36" text-anchor="middle">1/C</text><text x="70" y="84" text-anchor="middle">add them up</text></svg></div>
<div class="ms-flow-body"><p>The default. Each link costs 1 divided by its capacity, and the router (Dijkstra) takes the path with the smallest total. A weak link is expensive, a strong extra hop is cheap.</p></div>
</div>
\endhtmlonly

\f[ \text{cost}(p) = \sum_{\ell \in p} \frac{1}{C_\ell} \f]

| Path | Hops | Cost (1/Gbps) |
|---|---|---|
| src → dst | 1 | 4.852 |
| src → n1 → dst | 2 | 0.259 + 0.259 = **0.518** |
| src → s1 → s2 → dst | 3 | 0.220 + 0.247 + 0.220 = 0.686 |

The north route wins. Its two hops cost about a ninth of the one weak hop, and
less than the south route's three, even though each south link is stronger.

## 4\. max_throughput: the widest bottleneck

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-purple">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><rect class="ms-soft" x="14" y="30" width="34" height="30"/><rect class="ms-soft" x="53" y="38" width="34" height="14"/><rect class="ms-soft" x="92" y="26" width="34" height="38"/><line class="ms-bad" x1="10" y1="45" x2="130" y2="45"/><text x="70" y="84" text-anchor="middle">narrowest link sets it</text></svg></div>
<div class="ms-flow-body"><p>A path is only as fast as its weakest link. <code>max_throughput</code> takes the path whose weakest link is strongest, whatever the number of hops.</p></div>
</div>
\endhtmlonly

\f[ \text{width}(p) = \min_{\ell \in p} C_\ell \qquad \text{pick the path with the largest width} \f]

| Path | Hops | Weakest link |
|---|---|---|
| src → dst | 1 | 206 Mbps |
| src → n1 → dst | 2 | 3,862 Mbps |
| src → s1 → s2 → dst | 3 | **4,051 Mbps** |

The south route wins by 189 Mbps at the cost of a third hop.

## 5\. min_hop: fewest links

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-amber">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><line class="ms-ink" x1="16" y1="46" x2="124" y2="46"/><circle class="ms-dot" cx="16" cy="46" r="6"/><circle class="ms-dot" cx="124" cy="46" r="6"/><text x="70" y="36" text-anchor="middle">1 hop</text><text x="70" y="84" text-anchor="middle">count links only</text></svg></div>
<div class="ms-flow-body"><p>Every usable link counts the same, whatever its capacity. The router (breadth-first search) takes the path with the fewest links.</p></div>
</div>
\endhtmlonly

The direct link is usable, so `min_hop` takes it: one hop at 206 Mbps. When
two paths tie on hops, the one through the node listed first in `nodes.json`
wins.

## 6\. The three results

\htmlonly
<div class="ms-flow-split ms-routes ms-routes-3">
<div class="ms-flow-art ms-c-blue"><svg viewBox="0 0 520 440" aria-hidden="true"><rect class="ms-bldg" x="200" y="186" width="120" height="120" rx="2"/><line class="ms-bad" x1="80" y1="246" x2="440" y2="246"/><line class="ms-ink ms-thick" x1="80" y1="246" x2="260" y2="66"/><line class="ms-ink ms-thin" x1="80" y1="246" x2="152" y2="366"/><line class="ms-faint" x1="80" y1="246" x2="368" y2="366"/><line class="ms-ink ms-thick" x1="260" y1="66" x2="440" y2="246"/><line class="ms-faint" x1="152" y1="366" x2="440" y2="246"/><line class="ms-ink ms-thin" x1="368" y1="366" x2="440" y2="246"/><line class="ms-faint" x1="260" y1="66" x2="152" y2="366"/><line class="ms-faint" x1="260" y1="66" x2="368" y2="366"/><line class="ms-ink ms-thin" x1="152" y1="366" x2="368" y2="366"/><circle class="ms-dot" cx="80" cy="246" r="7"/><text x="56" y="232" text-anchor="middle" class="ms-strong">src</text><circle class="ms-dot" cx="440" cy="246" r="7"/><text x="464" y="232" text-anchor="middle" class="ms-strong">dst</text><circle class="ms-dot" cx="260" cy="66" r="7"/><text x="260" y="52" text-anchor="middle" class="ms-strong">n1</text><circle class="ms-dot" cx="152" cy="366" r="7"/><text x="152" y="392" text-anchor="middle" class="ms-strong">s1</text><circle class="ms-dot" cx="368" cy="366" r="7"/><text x="368" y="392" text-anchor="middle" class="ms-strong">s2</text><text x="260" y="432" text-anchor="middle" class="ms-strong ms-big">shortest_path</text></svg></div>
<div class="ms-flow-art ms-c-purple"><svg viewBox="0 0 520 440" aria-hidden="true"><rect class="ms-bldg" x="200" y="186" width="120" height="120" rx="2"/><line class="ms-bad" x1="80" y1="246" x2="440" y2="246"/><line class="ms-ink ms-thin" x1="80" y1="246" x2="260" y2="66"/><line class="ms-ink ms-thick" x1="80" y1="246" x2="152" y2="366"/><line class="ms-faint" x1="80" y1="246" x2="368" y2="366"/><line class="ms-ink ms-thin" x1="260" y1="66" x2="440" y2="246"/><line class="ms-faint" x1="152" y1="366" x2="440" y2="246"/><line class="ms-ink ms-thick" x1="368" y1="366" x2="440" y2="246"/><line class="ms-faint" x1="260" y1="66" x2="152" y2="366"/><line class="ms-faint" x1="260" y1="66" x2="368" y2="366"/><line class="ms-ink ms-thick" x1="152" y1="366" x2="368" y2="366"/><circle class="ms-dot" cx="80" cy="246" r="7"/><text x="56" y="232" text-anchor="middle" class="ms-strong">src</text><circle class="ms-dot" cx="440" cy="246" r="7"/><text x="464" y="232" text-anchor="middle" class="ms-strong">dst</text><circle class="ms-dot" cx="260" cy="66" r="7"/><text x="260" y="52" text-anchor="middle" class="ms-strong">n1</text><circle class="ms-dot" cx="152" cy="366" r="7"/><text x="152" y="392" text-anchor="middle" class="ms-strong">s1</text><circle class="ms-dot" cx="368" cy="366" r="7"/><text x="368" y="392" text-anchor="middle" class="ms-strong">s2</text><text x="260" y="432" text-anchor="middle" class="ms-strong ms-big">max_throughput</text></svg></div>
<div class="ms-flow-art ms-c-amber"><svg viewBox="0 0 520 440" aria-hidden="true"><rect class="ms-bldg" x="200" y="186" width="120" height="120" rx="2"/><line class="ms-ink ms-thick" x1="80" y1="246" x2="440" y2="246"/><line class="ms-ink ms-thin" x1="80" y1="246" x2="260" y2="66"/><line class="ms-ink ms-thin" x1="80" y1="246" x2="152" y2="366"/><line class="ms-faint" x1="80" y1="246" x2="368" y2="366"/><line class="ms-ink ms-thin" x1="260" y1="66" x2="440" y2="246"/><line class="ms-faint" x1="152" y1="366" x2="440" y2="246"/><line class="ms-ink ms-thin" x1="368" y1="366" x2="440" y2="246"/><line class="ms-faint" x1="260" y1="66" x2="152" y2="366"/><line class="ms-faint" x1="260" y1="66" x2="368" y2="366"/><line class="ms-ink ms-thin" x1="152" y1="366" x2="368" y2="366"/><circle class="ms-dot" cx="80" cy="246" r="7"/><text x="56" y="232" text-anchor="middle" class="ms-strong">src</text><circle class="ms-dot" cx="440" cy="246" r="7"/><text x="464" y="232" text-anchor="middle" class="ms-strong">dst</text><circle class="ms-dot" cx="260" cy="66" r="7"/><text x="260" y="52" text-anchor="middle" class="ms-strong">n1</text><circle class="ms-dot" cx="152" cy="366" r="7"/><text x="152" y="392" text-anchor="middle" class="ms-strong">s1</text><circle class="ms-dot" cx="368" cy="366" r="7"/><text x="368" y="392" text-anchor="middle" class="ms-strong">s2</text><text x="260" y="432" text-anchor="middle" class="ms-strong ms-big">min_hop</text></svg></div>
</div>
\endhtmlonly

| `algorithm` | Path | Hops | Bottleneck | Delivered | Latency |
|---|---|---|---|---|---|
| `shortest_path` | src → n1 → dst | 2 | 3,862 Mbps | 1,000 of 1,000 Mbps | 1.001 ms |
| `max_throughput` | src → s1 → s2 → dst | 3 | 4,051 Mbps | 1,000 of 1,000 Mbps | 1.501 ms |
| `min_hop` | src → dst | 1 | 206 Mbps | 206.1 of 1,000 Mbps | 0.501 ms |

Latency is 0.5 ms of processing per hop plus the time light takes to cover
each link:

\f[ L = \sum_{\text{hops}} \left( 0.5 + \frac{d}{c} \cdot 1000 \right) \text{ ms} \f]

The 0.5 ms per hop dominates: the 424 m north route adds only 0.0014 ms of
propagation. `min_hop` delivers only 206 Mbps because its one link is
overloaded (section 7).

## 7\. When a link is overloaded

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-green">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><rect class="ms-soft" x="20" y="16" width="100" height="22"/><rect class="ms-soft" x="20" y="16" width="22" height="22" style="fill-opacity:.45"/><line class="ms-bad" x1="98" y1="8" x2="98" y2="64"/><rect class="ms-soft" x="20" y="48" width="78" height="14"/><text x="98" y="78" text-anchor="middle">capacity</text><text x="70" y="90" text-anchor="middle">every flow scaled</text></svg></div>
<div class="ms-flow-body"><p>After every flow has a path, the router adds up the demand on each link. Where the total is more than the link&rsquo;s capacity, every flow on that link is scaled down by the same factor.</p></div>
</div>
\endhtmlonly

\f[ s_\ell = \frac{C_\ell}{\sum_{f \text{ on } \ell} D_f}, \qquad \text{delivered}_f = D_f \cdot \min_{\ell \in p_f} \min(1,\, s_\ell) \f]

A second request, `n1` → `dst` at 3,500 Mbps, joins the first under
`shortest_path`. Both cross the `n1`–`dst` link (3,862 Mbps):

\f[ s = \frac{3861.6}{1000 + 3500} = 0.858 \f]

| Request | Demand | Path | Delivered |
|---|---|---|---|
| src → dst | 1,000 Mbps | src → n1 → dst | 858.1 Mbps |
| n1 → dst | 3,500 Mbps | n1 → dst | 3,003.5 Mbps |

- The router does not move the overflow to another path. Both flows keep
  their route and lose 14%.
- Links do not share airtime: `n1` receives on `src`–`n1` and sends on
  `n1`–`dst` at full capacity on both.
- In \ref files_links_csv "links.csv" the `n1`–`dst` row shows
  `delivered_mbps` = 3,861.6, equal to its capacity.
- `min_hop` in section 6 is the same rule with one flow:
  \f$ s = 206.1 / 1000 \f$, so 206 Mbps gets through.

## 8\. max_hops

`max_hops` is checked after the path is chosen. With `max_throughput` and
`max_hops = 2`, the router picks the three-hop south route, the limit rejects
it, and the request gets no route: `routable` = 0, 0 Mbps delivered. The
two-hop north route is never tried. Use `max_hops = 0` (no limit), a higher
limit, or `min_hop`.

## 9\. Common changes

| To | Set | What you'll see |
|---|---|---|
| Prefer strong paths, few hops | `algorithm = shortest_path` (default) | Here: the 2-hop north route, 1,000 Mbps delivered. |
| Get the most bandwidth per path | `algorithm = max_throughput` | Here: the 3-hop south route; +0.5 ms latency. Example: `08-max-throughput-routing`. |
| Use the fewest hops | `algorithm = min_hop` | Here: the direct 206 Mbps link; 794 Mbps lost to scaling. |
| Limit path length | `max_hops = 2` | Longer paths get no route, even when a shorter one exists. Example: `14-max-hops-limit`. |
| Remove the limit | `max_hops = 0` | Every path the algorithm finds is used. |
| See congestion | Ask for more than a link carries | `delivered_mbps` < `demand_mbps` in `flows.csv`. Example: `09-congestion-bottleneck`. |

## 10\. Related

- \ref files_traffic "Traffic": which flows exist and when
- \ref files_run_ini "run.ini": the `[routing]` keys
- \ref files_flows_csv "flows.csv", \ref files_routes_csv "routes.csv", \ref files_links_csv "links.csv": where paths and delivered rates land
- \ref files_channel_models "Channel models": where the link capacities come from
- \ref src_routing "src/routing": the router code

Previous: \ref files_traffic "Traffic" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_nodes_json "nodes.json"
