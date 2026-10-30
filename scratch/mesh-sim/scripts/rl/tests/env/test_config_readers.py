"""INI edge cases that previously selected a different scenario in Python."""
import pytest
from scripts.rl.env import config
from scripts.rl.env.protocol import CentralizedProtocol


def test_ini_uses_case_sensitive_last_wins_and_no_default_inheritance(tmp_path):
    path = tmp_path / "run.ini"
    path.write_text("[DEFAULT]\nseed=91\n[scenario] # comment ]\nseed=7\n"
                    "seed=9 ; last wins\n[rl]\ntelemetry=steps\nTelemetry=off\n"
                    "manifest_every_decisions=3 # cadence\ncompact_training=yes\n")
    assert config.read_scenario_seed(str(path)) == 9
    assert config.read_rl_selection(str(path)) == {"telemetry": "steps"}
    assert config.read_manifest_every_decisions(str(path)) == 3
    assert config.read_episode_output(str(path)) == {"compact_training": True}
    path.write_text("[DEFAULT]\nseed=91\n[scenario]\n")
    assert config.read_scenario_seed(str(path)) is None


def test_explicit_bounds_remain_explicit_after_parser_change(tmp_path):
    path = tmp_path / "run.ini"
    path.write_text("[rl]\nx_min= -3 ; floor\n")
    assert config.read_explicit_rl_bounds(str(path)) == {"x_min": -3}
    path.write_text("[rl]\nx_min=1_000\n")
    with pytest.raises(ValueError, match="plain number"):
        config.read_explicit_rl_bounds(str(path))


def test_onset_reader_uses_new_parser_without_losing_target_fields(tmp_path):
    path = tmp_path / "run.ini"
    path.write_text("[scenario]\nduration_s=10\njammers_file=jammers.json\n"
                    "[rl]\ntraining_jammer_onsets_s=1,2 # train\n"
                    "evaluation_jammer_onsets_s=4\n")
    assert config.read_jammer_onsets(str(path)) == ((1., 2.), (4.,))


@pytest.mark.parametrize("value", [None, float("inf"), float("nan")])
def test_invalid_joint_actions_raise_value_error(sim_binary, multi_run_config, tmp_path, value):
    from scripts.rl.env.mesh_env import MeshRlEnv
    env = MeshRlEnv(sim_binary=sim_binary, run_config=multi_run_config,
                    output_dir=str(tmp_path / "episode"))
    try:
        env.reset()
        with pytest.raises(ValueError, match="must be an integer"):
            env.step([value, 4, 4])
    finally:
        env.close()
