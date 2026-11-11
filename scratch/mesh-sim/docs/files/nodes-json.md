# nodes.json {#files_nodes_json}

[TOC]

`nodes.json` lists the mesh nodes: what each is called, how it moves, its
antenna gains and an optional dropout time. `[scenario] nodes_file` in
`run.ini` names it, relative to `run.ini`, and every run keeps a copy in
`<output>/inputs/nodes.json`.

\htmlonly
<div class="ms-find" data-noun="field"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search fields, e.g. waypoints, node_type, gain" aria-label="Search fields"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

One entry from a three-peer urban recovery scenario, part by part:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code">{
  "id": "drone-1",
  "role": "peer",
  "node_type": "drone",</pre>
<div class="ms-ini-note"><strong>Identity</strong>The name other settings use for this node, and its platform. It is the second entry in the list, so it is node <code>1</code> in every CSV.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code">  "mobility": "constant_velocity",
  "position": {"x": 200, "y": 200, "z": 20},</pre>
<div class="ms-ini-note"><strong>Mobility and start position</strong>A straight-line mover that starts 20 m up at (200, 200).</div>
</div>
<div class="ms-ini-row ms-c-pink">
<pre class="ms-ini-code">  "velocity": {"vx": 0, "vy": 0, "vz": 0},</pre>
<div class="ms-ini-note"><strong>Mobility parameters</strong>Zero velocity: the node holds still unless an RL agent moves it.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code">  "tx_array_gain_dbi": 12,
  "rx_array_gain_dbi": 12,</pre>
<div class="ms-ini-note"><strong>Per-node antenna gains</strong>12 dBi each way, the <code>[channel]</code> default. The two ground peers in the same file use 3 dBi.</div>
</div>
<div class="ms-ini-row ms-c-amber">
<pre class="ms-ini-code">  "failure_at_s": 10.0
}</pre>
<div class="ms-ini-note"><strong>Dropout</strong>The node fails permanently at t = 10 s and carries no traffic after that.</div>
</div>
</div>
\endhtmlonly

The file is a JSON array of these objects, at least two. Keys the loader
does not know are ignored.

## 2\. Identity and order

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`id`<span class="ms-key-def">required</span></div>
<div class="ms-key-what">The node's name. Settings that point at a node use it: `gateway_node_id`, `pairs`, `controlled_nodes`, `investigator_id`, `--positions-override`.<div class="ms-key-note">Always a string: write `"1"`, not `1`. Keep ids unique; with duplicates the first match wins.</div></div>
<div class="ms-key-vals">any string</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`role`<span class="ms-key-def">default `peer`</span></div>
<div class="ms-key-what">A label the simulator never reads. The RL mission tools want `peer`.</div>
<div class="ms-key-vals">any string</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_type`<span class="ms-key-def">default `drone`</span></div>
<div class="ms-key-what">The platform. It sets the node's top speed under RL and nothing else.<div class="ms-key-note">20 m/s for `drone`, 15 m/s for `vehicle`, 1.5 m/s for `pedestrian`. Also written to `positions.csv`.</div></div>
<div class="ms-key-vals">`drone`, `vehicle`, `pedestrian`</div>
</div>
</div>

**Order in the file is the node number.** The CSVs name nodes by number, 0
first; `summary.json` uses the ids. Reordering the file renumbers every node.
From `p0-jammer-smoke`:

\htmlonly
<div class="ms-order"><div class="ms-order-item"><span class="ms-order-pos">1st in the file</span><code>node-a</code><span class="ms-order-idx">0</span></div><div class="ms-order-item"><span class="ms-order-pos">2nd in the file</span><code>node-b</code><span class="ms-order-idx">1</span></div><div class="ms-order-item"><span class="ms-order-pos">3rd in the file</span><code>relay</code><span class="ms-order-idx">2</span></div></div>
\endhtmlonly

So the `links.csv` row `0.000000,0,2,...` is the `node-a`–`relay` link. To put
ids back on a CSV:

```python
import json, pandas as pd
run = "outputs/examples/p0-jammer-smoke"
ids = dict(enumerate(n["id"] for n in json.load(open(f"{run}/inputs/nodes.json"))))
links = pd.read_csv(f"{run}/seed-1/links.csv")
links["a"], links["b"] = links.node_a.map(ids), links.node_b.map(ids)
```

## 3\. How nodes move

`mobility` picks one of four kinds. This run has one node of each; the
drawing is 24 s of its \ref files_positions_csv "positions.csv", seen from
above:

\htmlonly
<div class="ms-flow-art ms-scene ms-c-blue"><svg viewBox="0 0 594 528" role="img" aria-label="24 seconds of positions.csv from one run with one node of each mobility kind, seen from above."><rect class="ms-bldg" x="198" y="220" width="220" height="132" stroke-dasharray="5 4"/><text x="204" y="344">random_walk bounds</text><g class="ms-c-grey"><circle class="ms-start" cx="66.0" cy="352.0" r="7"/></g><g class="ms-c-blue"><polyline class="ms-track" points="110.0,484.0 111.8,484.0 113.5,484.0 115.3,484.0 117.0,484.0 118.8,484.0 120.6,484.0 122.3,484.0 124.1,484.0 125.8,484.0 127.6,484.0 129.4,484.0 131.1,484.0 132.9,484.0 134.6,484.0 136.4,484.0 138.2,484.0 139.9,484.0 141.7,484.0 143.4,484.0 145.2,484.0 147.0,484.0 148.7,484.0 150.5,484.0 152.2,484.0 154.0,484.0 155.8,484.0 157.5,484.0 159.3,484.0 161.0,484.0 162.8,484.0 164.6,484.0 166.3,484.0 168.1,484.0 169.8,484.0 171.6,484.0 173.4,484.0 175.1,484.0 176.9,484.0 178.6,484.0 180.4,484.0 182.2,484.0 183.9,484.0 185.7,484.0 187.4,484.0 189.2,484.0 191.0,484.0 192.7,484.0 194.5,484.0 196.2,484.0 198.0,484.0 199.8,484.0 201.5,484.0 203.3,484.0 205.0,484.0 206.8,484.0 208.6,484.0 210.3,484.0 212.1,484.0 213.8,484.0 215.6,484.0 217.4,484.0 219.1,484.0 220.9,484.0 222.6,484.0 224.4,484.0 226.2,484.0 227.9,484.0 229.7,484.0 231.4,484.0 233.2,484.0 235.0,484.0 236.7,484.0 238.5,484.0 240.2,484.0 242.0,484.0 243.8,484.0 245.5,484.0 247.3,484.0 249.0,484.0 250.8,484.0 252.6,484.0 254.3,484.0 256.1,484.0 257.8,484.0 259.6,484.0 261.4,484.0 263.1,484.0 264.9,484.0 266.6,484.0 268.4,484.0 270.2,484.0 271.9,484.0 273.7,484.0 275.4,484.0 277.2,484.0 279.0,484.0 280.7,484.0 282.5,484.0 284.2,484.0 286.0,484.0 287.8,484.0 289.5,484.0 291.3,484.0 293.0,484.0 294.8,484.0 296.6,484.0 298.3,484.0 300.1,484.0 301.8,484.0 303.6,484.0 305.4,484.0 307.1,484.0 308.9,484.0 310.6,484.0 312.4,484.0 314.2,484.0 315.9,484.0 317.7,484.0 319.4,484.0 321.2,484.0 323.0,484.0 324.7,484.0 326.5,484.0 328.2,484.0 330.0,484.0 331.8,484.0 333.5,484.0 335.3,484.0 337.0,484.0 338.8,484.0 340.6,484.0 342.3,484.0 344.1,484.0 345.8,484.0 347.6,484.0 349.4,484.0 351.1,484.0 352.9,484.0 354.6,484.0 356.4,484.0 358.2,484.0 359.9,484.0 361.7,484.0 363.4,484.0 365.2,484.0 367.0,484.0 368.7,484.0 370.5,484.0 372.2,484.0 374.0,484.0 375.8,484.0 377.5,484.0 379.3,484.0 381.0,484.0 382.8,484.0 384.6,484.0 386.3,484.0 388.1,484.0 389.8,484.0 391.6,484.0 393.4,484.0 395.1,484.0 396.9,484.0 398.6,484.0 400.4,484.0 402.2,484.0 403.9,484.0 405.7,484.0 407.4,484.0 409.2,484.0 411.0,484.0 412.7,484.0 414.5,484.0 416.2,484.0 418.0,484.0 419.8,484.0 421.5,484.0 423.3,484.0 425.0,484.0 426.8,484.0 428.6,484.0 430.3,484.0 432.1,484.0 433.8,484.0 435.6,484.0 437.4,484.0 439.1,484.0 440.9,484.0 442.6,484.0 444.4,484.0 446.2,484.0 447.9,484.0 449.7,484.0 451.4,484.0 453.2,484.0 455.0,484.0 456.7,484.0 458.5,484.0 460.2,484.0 462.0,484.0 463.8,484.0 465.5,484.0 467.3,484.0 469.0,484.0 470.8,484.0 472.6,484.0 474.3,484.0 476.1,484.0 477.8,484.0 479.6,484.0 481.4,484.0 483.1,484.0 484.9,484.0 486.6,484.0 488.4,484.0 490.2,484.0 491.9,484.0 493.7,484.0 495.4,484.0 497.2,484.0 499.0,484.0 500.7,484.0 502.5,484.0 504.2,484.0 506.0,484.0 507.8,484.0 509.5,484.0 511.3,484.0 513.0,484.0 514.8,484.0 516.6,484.0 518.3,484.0 520.1,484.0 521.8,484.0 523.6,484.0 525.4,484.0 527.1,484.0 528.9,484.0 530.6,484.0 532.4,484.0"/><circle class="ms-start" cx="110.0" cy="484.0" r="7"/><circle class="ms-end" cx="532.4" cy="484.0" r="6"/></g><g class="ms-c-green"><polyline class="ms-track" points="308.0,286.0 308.5,284.3 308.9,282.6 309.4,280.9 309.8,279.2 310.3,277.5 310.8,275.8 311.2,274.1 311.7,272.4 312.1,270.7 312.6,269.0 312.9,270.7 313.3,272.5 313.6,274.2 313.9,275.9 314.3,277.7 314.6,279.4 314.9,281.1 315.3,282.8 315.6,284.6 315.9,286.3 317.5,287.1 319.1,287.8 320.7,288.6 322.3,289.4 323.8,290.2 325.4,290.9 327.0,291.7 328.6,292.5 330.2,293.3 331.7,294.0 332.2,295.7 332.6,297.5 333.0,299.2 333.4,300.9 333.9,302.6 334.3,304.3 334.7,306.0 335.1,307.7 335.5,309.4 336.0,311.1 337.7,311.0 339.5,310.9 341.2,310.9 343.0,310.8 344.8,310.7 346.5,310.6 348.3,310.5 350.0,310.4 351.8,310.3 353.5,310.2 355.3,310.4 357.1,310.5 358.8,310.6 360.6,310.8 362.3,310.9 364.1,311.0 365.8,311.1 367.6,311.3 369.3,311.4 371.1,311.5 369.7,312.7 368.4,313.8 367.1,314.9 365.7,316.1 364.4,317.2 363.0,318.3 361.7,319.5 360.3,320.6 359.0,321.7 357.6,322.9 358.4,324.4 359.2,326.0 359.9,327.6 360.7,329.2 361.5,330.8 362.2,332.4 363.0,333.9 363.8,335.5 364.6,337.1 365.3,338.7 366.1,340.3 366.8,341.9 367.6,343.4 368.4,345.0 369.1,346.6 369.9,348.2 370.7,349.8 371.4,351.4 372.2,351.0 372.9,349.5 374.7,349.8 376.4,350.1 378.1,350.4 379.9,350.7 381.6,351.0 383.3,351.3 385.1,351.6 386.8,351.9 388.5,351.8 390.3,351.5 390.0,350.8 389.7,349.1 389.4,347.3 389.1,345.6 388.8,343.9 388.5,342.1 388.2,340.4 388.0,338.7 387.7,336.9 387.4,335.2 386.3,336.5 385.2,337.9 384.1,339.3 382.9,340.7 381.8,342.0 380.7,343.4 379.6,344.8 378.5,346.1 377.4,347.5 376.3,348.9 378.0,349.1 379.8,349.4 381.5,349.6 383.3,349.8 385.0,350.1 386.8,350.3 388.5,350.6 390.2,350.8 392.0,351.1 393.7,351.3 395.3,350.6 396.9,349.9 398.5,349.1 400.1,348.4 401.7,347.6 403.3,346.9 404.9,346.2 406.5,345.4 408.1,344.7 409.7,344.0 411.4,344.3 413.1,344.7 414.9,345.1 416.6,345.5 417.7,345.8 416.0,346.2 414.3,346.6 412.5,347.0 410.8,347.3 409.1,347.7 408.5,346.0 407.9,344.4 407.3,342.7 406.7,341.1 406.1,339.4 405.5,337.8 405.0,336.1 404.4,334.4 403.8,332.8 403.2,331.1 401.8,330.0 400.4,328.9 399.1,327.8 397.7,326.7 396.3,325.6 395.0,324.5 393.6,323.4 392.2,322.3 390.9,321.2 389.5,320.1 389.0,318.4 388.4,316.7 387.9,315.0 387.3,313.4 386.8,311.7 386.3,310.0 385.7,308.3 385.2,306.7 384.6,305.0 384.1,303.3 382.6,304.2 381.1,305.1 379.6,306.0 378.1,306.9 376.6,307.9 375.1,308.8 373.6,309.7 372.1,310.6 370.5,311.5 369.0,312.4 368.5,310.7 368.0,309.0 367.5,307.4 366.9,305.7 366.4,304.0 365.9,302.3 365.4,300.6 364.8,299.0 364.3,297.3 363.8,295.6 364.7,294.1 365.6,292.6 366.5,291.0 367.4,289.5 368.3,288.0 369.2,286.5 370.1,285.0 370.9,283.5 371.8,281.9 372.7,280.4 371.2,279.5 369.7,278.6 368.2,277.7 366.7,276.8 365.2,275.9 363.7,275.0 362.2,274.1 360.7,273.2 359.2,272.2 357.7,271.3 358.5,272.9 359.3,274.5 360.1,276.0 360.9,277.6 361.7,279.1 362.5,280.7 363.3,282.3 364.2,283.8 365.0,285.4 365.8,287.0 364.8,288.4 363.9,289.9 362.9,291.4 361.9,292.8 361.0,294.3 360.0,295.8 359.0,297.3 358.1,298.7 357.1,300.2 356.2,301.7"/><circle class="ms-start" cx="308.0" cy="286.0" r="7"/><circle class="ms-end" cx="356.2" cy="301.7" r="6"/></g><g class="ms-c-purple"><polyline class="ms-track" points="66.0,132.0 68.2,130.9 70.4,129.8 72.6,128.7 74.8,127.6 77.0,126.5 79.2,125.4 81.4,124.3 83.6,123.2 85.8,122.1 88.0,121.0 90.2,119.9 92.4,118.8 94.6,117.7 96.8,116.6 99.0,115.5 101.2,114.4 103.4,113.3 105.6,112.2 107.8,111.1 110.0,110.0 112.2,108.9 114.4,107.8 116.6,106.7 118.8,105.6 121.0,104.5 123.2,103.4 125.4,102.3 127.6,101.2 129.8,100.1 132.0,99.0 134.2,97.9 136.4,96.8 138.6,95.7 140.8,94.6 143.0,93.5 145.2,92.4 147.4,91.3 149.6,90.2 151.8,89.1 154.0,88.0 156.2,86.9 158.4,85.8 160.6,84.7 162.8,83.6 165.0,82.5 167.2,81.4 169.4,80.3 171.6,79.2 173.8,78.1 176.0,77.0 178.2,75.9 180.4,74.8 182.6,73.7 184.8,72.6 187.0,71.5 189.2,70.4 191.4,69.3 193.6,68.2 195.8,67.1 198.0,66.0 200.2,64.9 202.4,63.8 204.6,62.7 206.8,61.6 209.0,60.5 211.2,59.4 213.4,58.3 215.6,57.2 217.8,56.1 220.0,55.0 222.2,53.9 224.4,52.8 226.6,51.7 228.8,50.6 231.0,49.5 233.2,48.4 235.4,47.3 237.6,46.2 239.8,45.1 242.0,44.0 246.4,44.7 250.8,45.5 255.2,46.2 259.6,46.9 264.0,47.7 268.4,48.4 272.8,49.1 277.2,49.9 281.6,50.6 286.0,51.3 290.4,52.1 294.8,52.8 299.2,53.5 303.6,54.3 308.0,55.0 312.4,55.7 316.8,56.5 321.2,57.2 325.6,57.9 330.0,58.7 334.4,59.4 338.8,60.1 343.2,60.9 347.6,61.6 352.0,62.3 356.4,63.1 360.8,63.8 365.2,64.5 369.6,65.3 374.0,66.0 378.4,66.7 382.8,67.5 387.2,68.2 391.6,68.9 396.0,69.7 400.4,70.4 404.8,71.1 409.2,71.9 413.6,72.6 418.0,73.3 422.4,74.1 426.8,74.8 431.2,75.5 435.6,76.3 440.0,77.0 444.4,77.7 448.8,78.5 453.2,79.2 457.6,79.9 462.0,80.7 466.4,81.4 470.8,82.1 475.2,82.9 479.6,83.6 484.0,84.3 488.4,85.1 492.8,85.8 497.2,86.5 501.6,87.3 506.0,88.0 506.0,91.7 506.0,95.3 506.0,99.0 506.0,102.7 506.0,106.3 506.0,110.0 506.0,113.7 506.0,117.3 506.0,121.0 506.0,124.7 506.0,128.3 506.0,132.0 506.0,135.7 506.0,139.3 506.0,143.0 506.0,146.7 506.0,150.3 506.0,154.0 506.0,157.7 506.0,161.3 506.0,165.0 506.0,168.7 506.0,172.3 506.0,176.0 506.0,179.7 506.0,183.3 506.0,187.0 506.0,190.7 506.0,194.3 506.0,198.0 506.0,201.7 506.0,205.3 506.0,209.0 506.0,212.7 506.0,216.3 506.0,220.0 506.0,223.7 506.0,227.3 506.0,231.0 506.0,234.7 506.0,238.3 506.0,242.0 506.0,245.7 506.0,249.3 506.0,253.0 506.0,256.7 506.0,260.3 506.0,264.0 506.0,267.7 506.0,271.3 506.0,275.0 506.0,278.7 506.0,282.3 506.0,286.0 506.0,289.7 506.0,293.3 506.0,297.0 506.0,300.7 506.0,304.3 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0 506.0,308.0"/><circle class="ms-start" cx="66.0" cy="132.0" r="7"/><circle class="ms-end" cx="506.0" cy="308.0" r="6"/></g><g class="ms-c-purple"><rect class="ms-wp" x="61.5" y="127.5" width="9" height="9"/></g><text x="66.0" y="120.0" text-anchor="middle">t = 0 s</text><g class="ms-c-purple"><rect class="ms-wp" x="237.5" y="39.5" width="9" height="9"/></g><text x="242.0" y="32.0" text-anchor="middle">t = 8 s</text><g class="ms-c-purple"><rect class="ms-wp" x="501.5" y="83.5" width="9" height="9"/></g><text x="506.0" y="76.0" text-anchor="middle">t = 14 s</text><g class="ms-c-purple"><rect class="ms-wp" x="501.5" y="303.5" width="9" height="9"/></g><text x="506.0" y="330.0" text-anchor="middle">t = 20 s</text><text x="60.0" y="338.0" text-anchor="start" class="ms-strong">mast · fixed</text><text x="104.0" y="502.0" text-anchor="start" class="ms-strong">truck · constant_velocity</text><text x="302.0" y="246.0" text-anchor="start" class="ms-strong">rover · random_walk</text><text x="60.0" y="162.0" text-anchor="start" class="ms-strong">drone · waypoint</text><line class="ms-ink" x1="451" y1="31" x2="561" y2="31"/><text x="506" y="23" text-anchor="middle">50 m</text></svg><div class="ms-legend"><span><i class="ms-key-dot ms-start"></i>start</span><span><i class="ms-key-dot ms-end"></i>after 24 s</span><span><i class="ms-key-dot ms-wp"></i>waypoint</span></div></div>
\endhtmlonly

```json
[
  {"id": "mast", "mobility": "fixed",
    "position": {"x": 0, "y": 0, "z": 10}},
  {"id": "truck", "node_type": "vehicle", "mobility": "constant_velocity",
    "position": {"x": 20, "y": -60, "z": 2},
    "velocity": {"vx": 8, "vy": 0, "vz": 0}},
  {"id": "rover", "node_type": "vehicle", "mobility": "random_walk",
    "position": {"x": 110, "y": 30, "z": 1.5},
    "random_walk": {"bounds": {"x_min": 60, "x_max": 160, "y_min": 0, "y_max": 60}, "speed_mps": 8}},
  {"id": "drone", "mobility": "waypoint",
    "waypoints": [{"t": 0, "x": 0, "y": 100, "z": 30}, {"t": 8, "x": 80, "y": 140, "z": 30},
                  {"t": 14, "x": 200, "y": 120, "z": 40}, {"t": 20, "x": 200, "y": 20, "z": 40}]}
]
```

- **mast** never moves.
- **truck** drives east at 8 m/s and keeps going: there is no edge.
- **rover** turns to a new random heading every second and bounces off its
  box (here at the bottom and right edges). Its height never changes, and the
  path differs per `seed`.
- **drone** flies straight from waypoint to waypoint, then holds the last one
  from t = 20 s.

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`mobility`<span class="ms-key-def">default `fixed`</span></div>
<div class="ms-key-what">Which of the four kinds.<div class="ms-key-note">RL-controlled nodes ignore it: they start at `position` (or the first waypoint) and move only by RL action.</div></div>
<div class="ms-key-vals">`fixed`, `constant_velocity`, `random_walk`, `waypoint`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`position`<span class="ms-key-def">default `{0, 0, 0}` m</span></div>
<div class="ms-key-what">Where the node starts. Not used by `waypoint`.</div>
<div class="ms-key-vals">`{x, y, z}` in m<span class="ms-key-cli">or <code>&#45;&#45;positions-override</code> on the command line</span></div>
</div>
<div class="ms-key">
<div class="ms-key-name">`velocity`<span class="ms-key-def">`constant_velocity`</span></div>
<div class="ms-key-what">Speed and direction, kept for the whole run. `vz` climbs or descends.</div>
<div class="ms-key-vals">`{vx, vy, vz}` in m/s</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`random_walk.bounds`<span class="ms-key-def">`random_walk`</span></div>
<div class="ms-key-what">The box the walk bounces off. `position` must be inside it.<div class="ms-key-note">Default x and y from −100 to 100 m.</div></div>
<div class="ms-key-vals">`{x_min, x_max, y_min, y_max}` in m</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`random_walk.speed_mps`<span class="ms-key-def">`random_walk`</span></div>
<div class="ms-key-what">The walking speed.<div class="ms-key-note">Default 1.5 m/s.</div></div>
<div class="ms-key-vals">m/s</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`waypoints`<span class="ms-key-def">`waypoint`</span></div>
<div class="ms-key-what">The timed path. Before the first `t` the node waits at the first point; after the last it holds the last.</div>
<div class="ms-key-vals">`[{t, x, y, z}, ...]`, at least 2, `t` increasing from &ge; 0</div>
</div>
</div>

To try other start positions without editing the file, pass
`--positions-override=<file.json>` with `{"<id>": [x, y, z], ...}`. It moves
only the ids it names, and not `waypoint` nodes.

## 4\. Coordinates {#nodes_json_coordinates}

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-grey"><div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><defs><marker id="ax" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs><line class="ms-ink" x1="40" y1="70" x2="112" y2="70" marker-end="url(#ax)"/><line class="ms-ink" x1="40" y1="70" x2="80" y2="34" marker-end="url(#ax)"/><line class="ms-ink" x1="40" y1="70" x2="40" y2="10" marker-end="url(#ax)"/><text x="118" y="74">x east</text><text x="84" y="32">y north</text><text x="46" y="14">z up</text></svg></div><div class="ms-flow-body"><p>One frame for the whole scenario, in meters. The origin is anywhere you like; only distances between things matter. <code>z</code> is antenna height above the ground at z = 0.</p></div></div>
\endhtmlonly

- `buildings.json`, `jammers.json` and the `[rl]` and `[mission]` areas use
  the same frame. Jammer `azimuth_deg = 0` points north.
- Height matters to the channel: the 3GPP models treat the higher node of a
  pair as the base station (\ref files_channel_models "Channel models").
- Keep every node at z ≥ 1 m with `scenario = RMa`: z = 0 stops the run.
- Nodes closer than 1 m are treated as 1 m apart.
- A node inside a building box is indoors (\ref files_buildings_json "buildings.json").

## 5\. Per-node antenna gains

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`tx_array_gain_dbi`<span class="ms-key-def">default from `[channel]`, `12`</span></div>
<div class="ms-key-what">This node's transmit gain, replacing the `[channel]` value.</div>
<div class="ms-key-vals">&ge; 0 dBi</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rx_array_gain_dbi`<span class="ms-key-def">default from `[channel]`, `12`</span></div>
<div class="ms-key-what">This node's receive gain, replacing the `[channel]` value.</div>
<div class="ms-key-vals">&ge; 0 dBi</div>
</div>
</div>

Each link is computed once, from the node listed first to the node listed
later, and the result serves both directions. So a link uses the first
node's transmit gain and the later node's receive gain:

\htmlonly
<div class="ms-flow-art ms-scene ms-gain ms-c-green"><svg viewBox="0 0 560 120" aria-hidden="true"><line class="ms-ink" x1="110" y1="60" x2="450" y2="60"/><circle class="ms-dot" cx="90" cy="60" r="12"/><circle class="ms-dot" cx="470" cy="60" r="12"/><text x="90" y="30" text-anchor="middle" class="ms-strong">node 0 (listed first)</text><text x="470" y="30" text-anchor="middle" class="ms-strong">node 1 (listed later)</text><text x="90" y="98" text-anchor="middle">its tx_array_gain_dbi</text><text x="470" y="98" text-anchor="middle">its rx_array_gain_dbi</text><text x="280" y="50" text-anchor="middle">evaluated once, used both ways</text></svg></div>
\endhtmlonly

From `01-static-los-baseline` (`node-a` listed before `node-b`, SINR at
t = 0.1 s):

| Change | SINR |
|---|---|
| none | 34.64 dB |
| `node-a` transmit gain 0 | 22.64 dB |
| `node-a` receive gain 0 | 34.64 dB (never used) |
| `node-a` receive gain 0, and `node-a` moved after `node-b` | 22.64 dB |

Give a node equal transmit and receive gains and its place in the file stops
mattering.

## 6\. Dropout

<div class="ms-keys ms-c-amber">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`failure_at_s`<span class="ms-key-def">default `-1`, never</span></div>
<div class="ms-key-what">The node fails for good at this time: its links carry nothing and `positions.csv` shows `active = 0`.<div class="ms-key-note">Only in a recovery mission (`[mission] kind = recovery`), with at least two peers left, and not on the mission investigator.</div></div>
<div class="ms-key-vals">a tick time inside the run</div>
</div>
</div>

## 7\. Common changes

| To | Set | What you'll see |
|---|---|---|
| Move a node | `position` | New `dist_m` in `links.csv`. |
| Fly a straight line | `constant_velocity` and `velocity` | `02-distance-sweep`: `dist_m` grows 2 m per tick and `sinr_db` falls. |
| Follow a set path | `waypoint` and `waypoints` | The node passes each point at its time. |
| Wander in an area | `random_walk` and its `random_walk` block | A different path each seed. |
| Weaken one node's antenna | `tx_array_gain_dbi` and `rx_array_gain_dbi` | Its links lose SINR dB for dB, where that gain applies (section 5). |
| Slow a node under RL | `"node_type": "pedestrian"` | Top speed 1.5 m/s. |

## 8\. Related

- \ref files_run_ini "run.ini": `nodes_file`, the default gains, `[rl]` and `[mission]`
- \ref files_positions_csv "positions.csv": where each node was, per tick
- \ref files_buildings_json "buildings.json" and \ref files_jammers_json "jammers.json": the same coordinate frame
- \ref src_setup "src/setup": how mobility is installed

Previous: \ref files_routing "Routing" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_buildings_json "buildings.json"
