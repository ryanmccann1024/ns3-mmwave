"""Record and fingerprint the binary, scenario inputs, and models in a plan."""

import os
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.cli_common import MANIFEST_NAME
from scripts.rl.experiments.config import (
    config_for,
)
from scripts.sim_support import find_mesh_root, parse_ini


def binary_identity(raw: str) -> dict:
    """An existing executable file, hashed and never launched."""
    path = Path(raw).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"simulator binary is not an executable file: {path}")
    return {"path": str(path), "reference": raw, "sha256": sha256_file(path)}


def check_binary_fresh(path: str) -> None:
    """Refuse a binary older than mesh-sim sources (existing preflight rule)."""
    mesh = find_mesh_root()
    built = Path(path).stat().st_mtime
    sources = [
        mesh / "sim.cc",
        *(mesh / "src").rglob("*.cc"),
        *(mesh / "src").rglob("*.h"),
    ]
    stale = [p for p in sources if p.is_file() and p.stat().st_mtime > built]
    if stale:
        raise ValueError(
            f"simulator binary {path} is older than {len(stale)} mesh-sim source "
            f"file(s), e.g. {stale[0]}; the human rebuilds it from ns3-mmwave with "
            "./ns3 build scratch/mesh-sim/sim"
        )


def _asset(ini_path: Path, ini: dict, key: str, default: str = "") -> Path | None:
    raw = ini.get("scenario", {}).get(key, "") or default
    if not raw:
        return None
    path = Path(raw) if Path(raw).is_absolute() else ini_path.parent / raw
    if not path.is_file():
        raise ValueError(f"{ini_path}: scenario.{key} not found: {path}")
    return path.resolve()


class _Inputs:
    """Hash each input file once; the plan records path, hash and original reference."""

    def __init__(self):
        self.files: dict[str, dict] = {}

    def add(self, path, kind: str, reference: str | None = None) -> dict:
        path = str(Path(path).resolve())
        if path not in self.files:
            self.files[path] = {
                "kind": kind,
                "sha256": sha256_file(path),
                "reference": reference,
            }
        return {
            "path": path,
            "sha256": self.files[path]["sha256"],
            "reference": reference,
        }

    def ini(self, entry: dict) -> dict:
        """An INI plus the node/building/jammer assets its native loader resolves."""
        ini_path = Path(entry["path"])
        ini = parse_ini(ini_path)
        record = {
            **self.add(ini_path, "run_config", entry.get("reference")),
            "fallback": entry.get("fallback", False),
            "lookup": entry.get("lookup"),
            "config_source": entry.get("config_source"),
        }
        for name, key, default in (
            ("nodes", "nodes_file", "nodes.json"),
            ("buildings", "buildings_file", ""),
            ("jammers", "jammers_file", ""),
        ):
            asset = _asset(ini_path, ini, key, default)
            record[name] = None if asset is None else self.add(asset, name)
        return record


def _scenario_records(matrix: dict, inputs: _Inputs) -> dict:
    records = {}
    for slug, scenario in matrix["scenarios"].items():
        reference = scenario["reference"]
        baselines = scenario["baselines"]
        records[slug] = {
            "band": scenario["band"],
            "case": scenario["case"],
            "run_config": inputs.ini(
                {**scenario["run_config"], "fallback": False, "lookup": None}
            ),
            "configs": {
                role: {
                    seed: inputs.ini(
                        {
                            **entry,
                            "fallback": False,
                            "lookup": {"role": role, "key": seed},
                        }
                    )
                    for seed, entry in entries.items()
                }
                for role, entries in scenario["configs"].items()
            },
            "reference": None
            if reference is None
            else {
                "kind": reference["kind"],
                "version": reference["version"],
                **inputs.add(reference["path"], "reference", reference["reference"]),
            },
            "baselines": None
            if baselines is None
            else {
                **baselines,
                "import_from": None
                if baselines["import_from"] is None
                else inputs.add(
                    baselines["import_from"]["path"],
                    "import",
                    baselines["import_from"]["reference"],
                ),
            },
            "history_sources": scenario["history_sources"],
        }
    return records


def _row_record(row: dict, inputs: _Inputs) -> dict:
    record = {
        key: row.get(key)
        for key in (
            "name",
            "scenario",
            "profile",
            "selection",
            "training",
            "training_seeds",
            "training_config_key",
            "decisions_per_episode",
            "retained_checkpoints",
            "operations",
            "labels",
        )
    }
    for key in ("continue_from", "model_source"):
        source = row[key]
        if source is not None:
            inputs.add(source["model_path"], "model")
            inputs.add(Path(source["run_dir"]) / MANIFEST_NAME, "train_manifest")
            record[key] = {
                k: source[k]
                for k in (
                    "run_dir",
                    "reference",
                    "model",
                    "model_path",
                    "model_sha256",
                    "manifest_sha256",
                    "num_timesteps",
                    "n_updates",
                    "seed",
                    "digest",
                )
            }
        else:
            record[key] = None
    record["configs"] = {
        role: {
            seed: {
                **inputs.add(entry["path"], "run_config", entry["reference"]),
                "config_source": "row",
            }
            for seed, entry in entries.items()
        }
        for role, entries in row["configs"].items()
    }
    record["curriculum"] = (
        None
        if row["curriculum"] is None
        else inputs.add(
            row["curriculum"]["path"], "curriculum", row["curriculum"]["reference"]
        )
    )
    return record


def _seed_config(
    matrix: dict,
    inputs: "_Inputs",
    scenario: str,
    role: str,
    seed,
    row: dict | None = None,
) -> dict:
    """Hashed INI for one seed: row override > scenario configs > run_config (marked)."""
    return inputs.ini(config_for(matrix["scenarios"][scenario], role, seed, row))
