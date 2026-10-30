"""Behavior checks preserved from the experiment pilots; no native simulation."""

import json
from pathlib import Path
import sys

import pytest

from scripts.rl.scenario_check import preflight as preflight_campaign
from scripts.rl.env.config import read_manifest_every_decisions
from scripts.rl.env.mesh_env import MeshRlEnv


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true"])
def test_manifest_cadence_rejects_invalid_values(multi_run_config, value):
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text()+f"manifest_every_decisions = {value}\n")
    with pytest.raises(ValueError, match="positive integer"):
        read_manifest_every_decisions(str(ini))


def test_manifest_cadence_keeps_final_totals(sim_binary, multi_run_config, tmp_path):
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text()+"manifest_every_decisions = 50\n")
    env = MeshRlEnv(sim_binary, str(ini), output_dir=str(tmp_path/"episode"))
    try:
        env.reset()
        path = tmp_path/"episode/episode-0000/rl_episode.json"
        _, first, _, _, _ = env.step([4,4,4])
        assert json.loads(path.read_text())["steps"] == 0
        _, second, _, _, _ = env.step([4,4,4])
        saved = json.loads(path.read_text())
        assert saved["status"] == "completed" and saved["steps"] == 2
        assert saved["cumulative_reward"] == pytest.approx(first+second)
    finally:
        env.close()


def test_manifest_cadence_flushes_interrupted_totals(sim_binary, multi_run_config, tmp_path):
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text()+"manifest_every_decisions = 50\n")
    env = MeshRlEnv(sim_binary, str(ini), output_dir=str(tmp_path/"episode"))
    env.reset()
    env.step([4,4,4])
    env.close()
    saved = json.loads((tmp_path/"episode/episode-0000/rl_episode.json").read_text())
    assert saved["status"] == "interrupted" and saved["steps"] == 1


def _episodes(delivery, coverage=1):
    return [{"metrics": {"delivery_ratio": delivery, "coverage_fraction_mean": coverage}}]


def test_difficulty_gate_requires_healthy_hold_and_degraded_challenges():
    preflight_campaign.check_difficulty("small-hold", _episodes(1), .8)
    preflight_campaign.check_difficulty("large-jammer", _episodes(.4), .8)
    with pytest.raises(RuntimeError, match="not saturated"):
        preflight_campaign.check_difficulty("small-hold", _episodes(.99), .8)
    with pytest.raises(RuntimeError, match="exceeds"):
        preflight_campaign.check_difficulty("large-jammer", _episodes(1), .8)
    # Existing campaigns without a challenge criterion retain their behavior.
    preflight_campaign.check_difficulty("large-jammer", _episodes(1), None)


def test_preflight_signature_includes_difficulty_criteria(tmp_path):
    (tmp_path/"campaign.json").write_text(json.dumps({"scenarios":[], "preflight": {"seeds":[201,202],"challenge_delivery_max":.8}}))
    first = preflight_campaign.signature(tmp_path, Path(sys.executable))
    (tmp_path/"campaign.json").write_text(json.dumps({"scenarios":[], "preflight": {"seeds":[201,202],"challenge_delivery_max":.5}}))
    assert first != preflight_campaign.signature(tmp_path, Path(sys.executable))



def test_preflight_uses_policy_library_and_check_is_read_only(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts.artifact_io import write_json
    scene = tmp_path/'scene'
    scene.mkdir()
    (scene/'run.ini').write_text('[scenario]\nseed=201\nnodes_file=nodes.json\n')
    (scene/'nodes.json').write_text('[]')
    (tmp_path/'campaign.json').write_text(json.dumps({'scenarios': ['scene'], 'preflight': {'seeds': [201, 202]}}))
    binary = tmp_path/'unexecuted-binary'
    binary.write_bytes(b'not executable')
    closed = []
    class FeatureEnv:
        def __init__(self, *a, **k):
            self.contract = {'unsafe_separation_m': 1., 'coverage': {}, 'avoid_buildings': True}
            self._protocol = SimpleNamespace(facts={'coverage': {}})
        def reset(self): pass
        def close(self): closed.append(True)
    calls = []
    def evaluate(make_env, policies, seeds, out_dir, base):
        calls.append((policies[0].name, seeds))
        assert base['scenario_identity']['run_ini_sha256']
        return {'status': 'completed', 'policies': {'hold': {'episodes': _episodes(1.)*2}}}
    monkeypatch.setattr(preflight_campaign, 'MeshRlEnv', FeatureEnv)
    monkeypatch.setattr(preflight_campaign, 'resolve_selection', lambda _: object())
    monkeypatch.setattr(preflight_campaign, 'evaluate', evaluate)
    args = ['--inputs', str(tmp_path), '--sim-binary', str(binary), '--output-root', str(tmp_path/'out')]
    assert preflight_campaign.main(args) == 0
    assert closed == [True] and calls == [('hold', [201, 202])]
    assert json.loads((tmp_path/'out/preflight.json').read_text())['status'] == 'passed'
    monkeypatch.setattr(preflight_campaign, 'evaluate', lambda *a, **k: pytest.fail('check must not simulate'))
    assert preflight_campaign.main(args + ['--check']) == 0
