# Mesh-Sim

<!-- Landing page: tagline, a visualizer screenshot, a short introduction, then
     navigation. "Start here" comes first; "Find your way" holds every other
     page as cards that follow the sidebar groups. The \subpage order in this
     file sets the order of this page's children in the sidebar, and
     header.html's captions name the first page of each group, so update both
     together. Section headings are HTML <h2> so they are not repeated as
     entries in the sidebar tree; card styles are in theme/mesh-sim.css. -->

<div class="ms-tagline">Lightweight time-stepped mmWave / sub-6 mesh simulator built on ns3-mmwave</div>

<!-- Screenshot identity: ns3-mmwave-viz 3D player, urban jamming scenario with
     9 peers, scripted mission reference, seed 201, at 267 s of 600 s. Run
     outputs/custom/10-23-6/baselines/urban-jamming-9-peers/scripted/episode-0000;
     simulator binary SHA-256 20830a92b56be19b4ad987ef0452898877fd471c2f8b865cd798f31235ce4fbc
     (the run records no source commit); visualizer commit 04f6725. -->
<div class="ms-hero">
\image html home-urban-jamming-9-peers.jpg "Example: a jamming scenario replayed in the 3D visualizer."
</div>

Mesh-Sim simulates a wireless mesh network: radio nodes that relay traffic for one another. It steps through a scenario in time, works out how well every pair of nodes can hear each other (SINR, capacity and MCS) from an ns-3 propagation model, routes traffic over the mesh and records the results. Optional jammers and an optional reinforcement-learning bridge build on the same loop, and the companion visualizer replays any run in 3D, as above.

<hr>

<h2>Start Here</h2>

<div class="ms-cards ms-cards-3">
<div class="ms-card ms-card-primary">
<div class="ms-card-title">New to Mesh-Sim</div>
<ol>
<li>\subpage mesh_sim_start_here "Start here"</li>
<li>\subpage mesh_sim_install_build "Install and build"</li>
<li>\subpage mesh_sim_first_run "Your first run"</li>
<li>\subpage mesh_sim_first_result "Understand the result"</li>
<li>\subpage mesh_sim_change_one_setting "Change one setting"</li>
</ol>
</div>
<div class="ms-card">
<div class="ms-card-title">Input and output files</div>
<ul>
<li>\subpage mesh_sim_files "Every file, end to end"</li>
</ul>
<div class="ms-label">Inputs</div>
<ul>
<li>\ref files_run_ini "run.ini" and \ref files_channel_models "channel models"</li>
<li>\ref files_nodes_json "nodes.json", \ref files_buildings_json "buildings.json", \ref files_jammers_json "jammers.json"</li>
</ul>
<div class="ms-label">Outputs</div>
<ul>
<li>\ref files_run_log "run.log" and \ref files_summary_json "summary.json"</li>
<li>\ref files_links_csv "links.csv", \ref files_flows_csv "flows.csv" and the other CSVs</li>
<li>\ref files_figures "Figures"</li>
</ul>
</div>
<div class="ms-card">
<div class="ms-card-title">Other starting points</div>
<ul>
<li>\subpage mesh_sim_quickstart "Quickstart"</li>
<li>\subpage mesh_sim_overview "User guide"</li>
<li>\subpage system_overview "System overview"</li>
<li>\subpage mesh_sim_repo_map "Repository map"</li>
</ul>
</div>
</div>

<hr>

<h2>Find Your Way</h2>

<div class="ms-cards">
<div class="ms-card">
<div class="ms-card-title">Guides</div>
<div class="ms-label">Run scenarios</div>
<ul>
<li>\ref readme_run_single "Run a single scenario"</li>
<li>\ref scripts_sweep "Run a parameter sweep"</li>
<li>\ref src_jammer "Add jammers"</li>
</ul>
<div class="ms-label">Look at the results</div>
<ul>
<li>\ref mesh_sim_first_result "Read, graph and replay a run"</li>
<li>\ref scripts_plotting "Plotting tool"</li>
</ul>
<div class="ms-label">Plan node placement</div>
<ul>
<li>\subpage mesh_sim_placement_start "Placement baselines"</li>
</ul>
<div class="ms-label">Check against field data</div>
<ul>
<li>\subpage mesh_sim_field_data_workflow "Compare the simulator with field data"</li>
</ul>
<div class="ms-label">Reinforcement learning</div>
<ul>
<li>\subpage mesh_sim_rl_start "RL in Mesh-Sim"</li>
</ul>
</div>
<div class="ms-card">
<div class="ms-card-title">API reference</div>
<ul>
<li><a href="topics.html">Code by module</a></li>
</ul>
<div class="ms-card-text">Every C++ module and Python package, one group per folder. Search finds any class or function.</div>
</div>
</div>

<!-- Reference, project and research pages: kept as link targets for the guides and READMEs,
     but left off this page and the sidebar (theme/mesh-sim.css hides their entries).
     Listing them here keeps Doxygen from placing them at the sidebar root. -->
<div class="ms-hidden">
<ul>
<li>\subpage src "Simulator modules"</li>
<li>\subpage mesh_sim_run_flow "How a run works"</li>
<li>\subpage mesh_sim_setting_trace "Follow a setting"</li>
<li>\subpage mesh_sim_add_capacity_model "Add a capacity model"</li>
<li>\subpage scripts "Python tools"</li>
<li>\subpage Inputs "Scenario inputs"</li>
<li>\subpage scripts_rl_ops_tests "Operations test map"</li>
<li>\subpage Contributing "Contributing"</li>
<li>\subpage documentation_standard "Documentation standard"</li>
<li>\subpage generating_the_docs "Generating the docs"</li>
<li>\subpage mesh_sim_research "Research records"</li>
</ul>
</div>

<hr>

<h2>Project Status</h2>

**Current version:** v1.0.0

<hr>

<h2>About</h2>

Mesh-Sim is being developed in Dr. Vinod Vokkarane's Advanced Communication Networks Laboratory (ACNL) at the University of Massachusetts Lowell, in collaboration with Sherpa 6.

<hr>

<h2>Getting Help</h2>

**Documentation**

- \ref mesh_sim_quickstart "Quickstart": every command from a checkout to a graphed, replayed run
- \ref mesh_sim_overview "User guide": setup, running, common tasks, tests and outputs
- \ref system_overview "System overview": the simulator, its output files and the visualizer
- \ref mesh_sim_repo_map "Repository map": every folder and file, and how they connect
- <a href="annotated.html">API reference</a>: generated C++ and Python documentation

**Contributing**

- \ref Contributing "Contributing": the update-together checklist, schema and version details
- \ref documentation_standard "Documentation standard": how documentation is written and verified
- \ref generating_the_docs "Generating the docs": tested tool versions, theme, build and open commands

**Companion project**

The visualizer **ns3-mmwave-viz** replays this simulator's run folders in 3D. Start it with `npm install` and `npm run dev` in its checkout. Build its documentation there with `cd docs && doxygen Doxyfile`; with both repositories checked out side by side, this link then opens it: [Visualizer documentation](../../../../../ns3-mmwave-viz/docs/html/index.html).
