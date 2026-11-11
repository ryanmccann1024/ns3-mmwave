"""Per-seed environment setup and cancellation."""

import pytest
from scripts.rl.env.seeded_env import SeededEnv


def _stub_seeded(monkeypatch):
    from scripts.rl.env import mesh_env, selection

    created = []

    class StubEnv:
        def __init__(self, binary, config, **kwargs):
            self.config, self.kwargs, self.closed = config, kwargs, False
            created.append(self)

        def close(self):
            self.closed = True

        def reset(self, **kwargs):
            return self.config, kwargs

    monkeypatch.setattr(mesh_env, "MeshRlEnv", StubEnv)
    monkeypatch.setattr(
        selection, "resolve_selection", lambda config, **k: ("selection", config, k)
    )
    return created


def test_seeded_env_selects_per_seed_config_and_passes_seed_source(
    monkeypatch, tmp_path
):
    created = _stub_seeded(monkeypatch)
    case = dict(
        seeds={"101": dict(gate_s=5), "201": dict(gate_s=160), "202": dict(gate_s=180)}
    )
    env = SeededEnv(
        "bin",
        {"101": "a.ini", "201": "one.ini", "202": "two.ini"},
        tmp_path,
        case,
        initial_seed=101,
    )
    try:
        assert (
            created[0].config == "a.ini"
            and env.gate_s == 5
            and created[0].kwargs["seed"] == 101
        )
        config, kwargs = env.reset(seed=202, options={"seed_source": "eval"})
        assert config == "two.ini" and env.gate_s == 180
        assert kwargs == {"seed": 202, "options": {"seed_source": "eval"}}
        assert created[0].closed and env.inner is created[1]
        assert created[1].kwargs["selection"] == (
            "selection",
            "two.ini",
            {"telemetry": "steps"},
        )
        assert all(e.kwargs["output_dir"] == str(tmp_path) for e in created)
        assert all(
            e.kwargs["band"] is None and e.kwargs["decision_records"] is None
            for e in created
        )
        assert env.config == "two.ini"  # attribute delegation to the live env
    finally:
        env.close()
    with pytest.raises(TypeError):
        SeededEnv("bin", {"201": "one.ini"}, tmp_path, case)


def test_seeded_env_band_resolution_from_ini_or_explicit(monkeypatch, tmp_path):
    created = _stub_seeded(monkeypatch)
    (tmp_path / "sub6.ini").write_text("[channel]\nband = sub-6   # inline comment\n")
    (tmp_path / "plain.ini").write_text("[scenario]\nname = plain\n")
    configs = {"201": str(tmp_path / "sub6.ini"), "202": str(tmp_path / "plain.ini")}
    case = dict(seeds={"201": dict(gate_s=0), "202": dict(gate_s=0)})
    env = SeededEnv("bin", configs, tmp_path / "out", case, initial_seed=201)
    try:
        assert (env.band, env.band_source) == ("sub-6", "run.ini") and created[
            -1
        ].kwargs["band"] is None
        env.reset(seed=202)
        assert (env.band, env.band_source) == ("mmwave", "default") and created[
            -1
        ].kwargs["band"] is None
    finally:
        env.close()
    env = SeededEnv(
        "bin", configs, tmp_path / "out", case, initial_seed=202, band="sub-6"
    )
    try:
        assert (env.band, env.band_source) == ("sub-6", "cli") and created[-1].kwargs[
            "band"
        ] == "sub-6"
        env.reset(seed=201)
        assert (env.band, env.band_source) == ("sub-6", "cli") and created[-1].kwargs[
            "band"
        ] == "sub-6"
    finally:
        env.close()


def test_seeded_env_forwards_decision_records_to_every_seed(monkeypatch, tmp_path):
    from scripts.rl.env.recording.decisions import DecisionRecording

    created = _stub_seeded(monkeypatch)
    records = object.__new__(DecisionRecording)
    case = dict(seeds={"201": dict(gate_s=0), "202": dict(gate_s=0)})
    env = SeededEnv(
        "bin",
        {"201": "one.ini", "202": "two.ini"},
        tmp_path,
        case,
        initial_seed=201,
        decision_records=records,
    )
    try:
        env.reset(seed=202)
        env.reset(seed=201)
        assert len(created) == 3 and all(
            e.kwargs["decision_records"] is records for e in created
        )
    finally:
        env.close()


def test_scenario_check_seeded_env_keeps_initial_seed_and_scopes_cancellation(
    monkeypatch, tmp_path
):
    created = _stub_seeded(monkeypatch)
    from scripts.rl.scenario_check import execution

    configs = {"201": "one.ini", "202": "two.ini"}
    case = dict(seeds={"201": dict(gate_s=160), "202": dict(gate_s=180)})
    first, second = execution.ActiveEnvironments(), execution.ActiveEnvironments()
    env = execution.SeededEnv("bin", configs, tmp_path / "first", case, first)
    other = execution.SeededEnv("bin", configs, tmp_path / "second", case, second)
    try:
        assert created[0].config == "one.ini" and first.active == {env}
        assert second.active == {other}
        assert created[0].kwargs["band"] == "sub-6" and env.band == "sub-6"
        assert created[0].kwargs["decision_records"] is None
        first.cancelled.set()
        with pytest.raises(RuntimeError, match="interrupted"):
            env.reset(seed=202)
        other.reset(seed=202)
        assert other.gate_s == 180
    finally:
        env.close()
        other.close()
    assert not first.active and not second.active
