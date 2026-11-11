"""Reading legacy and current episode review outputs."""

import json
from pathlib import Path
import pytest

pytest.importorskip("sb3_contrib")


def review_stub(monkeypatch):
    from scripts.rl.policy import episode_review

    monkeypatch.setattr(
        episode_review,
        "review_metrics",
        lambda directory: {"stub_dir": Path(directory).name},
    )
    return episode_review


def fake_episode(directory):
    directory.mkdir(parents=True)
    (directory / "steps.jsonl").write_text("{}\n")
    (directory / "rl_episode.json").write_text("{}")
    return directory


def test_scene_review_without_models_is_a_valid_empty_v1_payload(tmp_path, monkeypatch):
    review = review_stub(monkeypatch).scene_review(
        tmp_path, "urban-coverage-3-peers", []
    )
    assert review == {
        "mission_review_version": 1,
        "objective": "coverage",
        "ranking_basis": "Frozen deterministic validation; separate variants and training seeds; "
        "not held-out confirmation",
        "ranking": [],
        "episodes": {},
    }


def test_scene_review_reads_explicit_baselines_before_the_legacy_path(
    tmp_path, monkeypatch
):
    episode_review = review_stub(monkeypatch)
    legacy = tmp_path / "baselines/s-coverage/eval_manifest.json"
    fake_episode(tmp_path / "baselines/s-coverage/hold/episode-0000")
    legacy.write_text(
        json.dumps(
            {
                "policies": {
                    "hold": {
                        "episodes": [
                            {
                                "episode_dir": str(
                                    tmp_path / "baselines/s-coverage/hold/episode-0000"
                                )
                            }
                        ]
                    }
                }
            }
        )
    )
    leaf = tmp_path / "new/baselines/hold/attempt-1"
    fake_episode(leaf / "hold/episode-0000")
    (leaf / "eval_manifest.json").write_text(
        json.dumps(
            {"policies": {"hold": {"episodes": [{"episode_dir": "hold/episode-0000"}]}}}
        )
    )
    loaded = {
        "policies": {
            "scripted": {
                "episodes": [
                    {"episode_dir": str(fake_episode(tmp_path / "loaded/episode-0000"))}
                ]
            }
        }
    }
    explicit = episode_review.scene_review(
        tmp_path, "s-coverage", [], baselines=[leaf, loaded]
    )
    assert list(explicit["episodes"]) == [
        "new/baselines/hold/attempt-1/hold/episode-0000",
        "loaded/episode-0000",
    ]
    legacy_only = episode_review.scene_review(tmp_path, "s-coverage", [])
    assert list(legacy_only["episodes"]) == ["baselines/s-coverage/hold/episode-0000"]
    assert (
        episode_review.scene_review(tmp_path, "s-coverage", [], baselines=[])[
            "episodes"
        ]
        == {}
    )


def test_scene_review_resolves_v5_episode_dirs_against_their_manifest(
    tmp_path, monkeypatch
):
    episode_review = review_stub(monkeypatch)
    leaf = (
        tmp_path
        / "operations/s-coverage/row/train-seed-1/checkpoint-final/op-k/diagnostic/seed-11/attempt-1"
    )
    fake_episode(leaf / "episode-0000")
    (leaf / "online_manifest.json").write_text(
        json.dumps(
            {
                "online_experiment_version": 5,
                "episodes": [
                    {
                        "mode": "online_gated_v1",
                        "seed": 11,
                        "episode_dir": "episode-0000",
                        "metrics": {"recorded": 1},
                    }
                ],
            }
        )
    )
    fixed = tmp_path / "fixed"
    fixed.mkdir()
    (fixed / "eval_manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "policies": {
                    "model": {"episodes": [{"episode_dir": "../fixed-episode"}]}
                },
            }
        )
    )
    fake_episode(tmp_path / "fixed-episode")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    models = [
        {
            "scene": "s-coverage",
            "reward": "r",
            "profile": "p",
            "fixed": str(fixed),
            "operation": str(leaf),
        }
    ]
    review = episode_review.scene_review(tmp_path, "s-coverage", models, baselines=[])
    assert sorted(review["episodes"]) == [
        "fixed-episode",
        leaf.relative_to(tmp_path).as_posix() + "/episode-0000",
    ]
    assert len(review["ranking"]) == 1 and review["ranking"][0]["metrics"] == {}
