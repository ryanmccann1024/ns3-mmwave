"""Pin and verify the inputs, code, dependencies and simulator for a batch."""

import json
from pathlib import Path

from scripts.artifact_io import canonical_sha256, now_iso, sha256_file, write_json
from scripts.rl.cli_common import package_versions
from scripts.rl.experiments.plan import PLAN_NAME
from scripts.sim_support import find_mesh_root

RUNTIME_IDENTITY_VERSION = 1


RUNTIME_IDENTITY_NAME = "runtime_identity.json"


_MAX_LISTED = 20


class IdentityChanged(ValueError):
    """A pinned code, input, binary, dependency or registry identity changed."""


def _source_root() -> Path:
    return find_mesh_root()


def python_sources(mesh: Path | None = None) -> dict:
    """SHA-256 of every non-test `scripts/**/*.py`, keyed by mesh-relative path."""
    mesh = Path(mesh or _source_root())
    return {
        str(p.relative_to(mesh)): sha256_file(p)
        for p in sorted((mesh / "scripts").rglob("*.py"))
        if "tests" not in p.parts and "__pycache__" not in p.parts
    }


def registry_identity() -> dict:
    """Contract-independent descriptor digest of every registered reward and preset, in order."""
    from scripts.rl.env import observations, rewards

    reward_items = []
    for name in rewards.COMPONENTS:
        c = rewards.get_component(name)
        reward_items.append(
            {
                "id": name,
                "sha256": canonical_sha256(
                    {
                        "range": list(c.range),
                        "required_facts": list(c.required_facts),
                        "contract_fields": list(c.contract_fields),
                        "tunable": {k: list(v) for k, v in c.tunable.items()},
                        "default_parameters": c.resolve({}),
                        "formula": c.formula,
                        "zero_demand_rule": c.zero_demand_rule,
                        "context_fields": list(c.context_fields),
                        "fact_extensions": list(c.fact_extensions),
                        "has_context_builder": c.context_builder is not None,
                    }
                ),
            }
        )
    preset_items = []
    for name in observations.PRESETS:
        p = observations.get_preset(name)
        preset_items.append(
            {
                "id": name,
                "sha256": canonical_sha256(
                    {
                        "dtype": p.dtype,
                        "normalization_fields": list(p.normalization_fields),
                        "default_parameters": dict(p.parameters),
                        "required_facts": list(p.required_facts),
                        "compatibility_fields": list(p.compatibility_fields),
                        "fact_extensions": list(p.fact_extensions),
                    }
                ),
            }
        )
    return {
        "reward_components": reward_items,
        "observation_presets": preset_items,
        "default_preset": observations.DEFAULT_PRESET,
    }


def _file_sha(path) -> str | None:
    try:
        return sha256_file(path)
    except OSError:
        return None


def runtime_identity(root, plan: dict) -> dict:
    """The identity pinned at first run; plan inputs must still match their plan hashes."""
    root = Path(root)
    changed = [
        path
        for path, entry in plan["inputs"].items()
        if _file_sha(path) != entry["sha256"]
    ]
    if changed:
        raise IdentityChanged(
            _bounded("inputs changed since the plan was written", changed)
            + "; use a new --output-root"
        )
    binary = plan["sim_binary"]
    if binary is None or _file_sha(binary["path"]) != binary["sha256"]:
        raise IdentityChanged(
            "simulator binary differs from the plan; use a new --output-root"
        )
    return {
        "runtime_identity_version": RUNTIME_IDENTITY_VERSION,
        "created_at": now_iso(),
        "plan": {
            "path": str(root / PLAN_NAME),
            "sha256": sha256_file(root / PLAN_NAME),
        },
        "matrix": {k: plan["matrix"][k] for k in ("path", "reference", "sha256")},
        "inputs": plan["inputs"],
        "parent_models": {
            p: e["sha256"]
            for p, e in plan["inputs"].items()
            if e["kind"] in ("model", "train_manifest")
        },
        "sim_binary": dict(binary),
        "python_sources": python_sources(),
        "package_versions": package_versions(),
        "registry": registry_identity(),
    }


def identity_path(root) -> Path:
    return Path(root) / RUNTIME_IDENTITY_NAME


def ensure_identity(root, plan: dict, sim_binary: str | None = None) -> dict:
    """Write the identity once at first run; afterwards only compare against it."""
    path = identity_path(root)
    if not path.exists():
        identity = runtime_identity(root, plan)
        write_json(path, identity)
        return identity
    return check_identity(root, sim_binary)


def _bounded(title: str, items: list[str]) -> str:
    shown = items[:_MAX_LISTED]
    more = f" ... and {len(items) - len(shown)} more" if len(items) > len(shown) else ""
    return f"{title}: " + ", ".join(shown) + more


def check_identity(root, sim_binary: str | None = None) -> dict:
    """Refuse any change from the pinned identity; returns the recorded identity.

    `sim_binary` is the same binary at another path (resume); its SHA-256 must
    equal the recorded one. Nothing is replaced and there is no warning mode.
    """
    root = Path(root)
    try:
        before = json.loads(identity_path(root).read_text())
    except (OSError, ValueError) as exc:
        raise IdentityChanged(
            f"{identity_path(root)} is missing or unreadable: {exc}"
        ) from exc
    if (
        not isinstance(before, dict)
        or before.get("runtime_identity_version") != RUNTIME_IDENTITY_VERSION
    ):
        raise IdentityChanged(
            f"{identity_path(root)} is not runtime identity version "
            f"{RUNTIME_IDENTITY_VERSION}"
        )
    changes = []
    if _file_sha(root / PLAN_NAME) != before["plan"]["sha256"]:
        changes.append(f"plan {PLAN_NAME}")
    for path, entry in before["inputs"].items():
        if _file_sha(path) != entry["sha256"]:
            changes.append(f"input {path}")
    binary_path = sim_binary or before["sim_binary"]["path"]
    if _file_sha(binary_path) != before["sim_binary"]["sha256"]:
        changes.append(f"simulator binary {binary_path}")
    now = python_sources()
    old = before["python_sources"]
    for path in sorted(set(now) | set(old)):
        if path not in old:
            changes.append(f"source added {path}")
        elif path not in now:
            changes.append(f"source removed {path}")
        elif now[path] != old[path]:
            changes.append(f"source changed {path}")
    versions = package_versions()
    for name in sorted(set(versions) | set(before["package_versions"])):
        if versions.get(name) != before["package_versions"].get(name):
            changes.append(
                f"dependency {name} {before['package_versions'].get(name)} -> "
                f"{versions.get(name)}"
            )
    if registry_identity() != before["registry"]:
        changes.append("reward/observation registry")
    if changes:
        raise IdentityChanged(
            _bounded("batch identity changed", changes)
            + ". Restore the pinned code/inputs/binary/dependencies, or start "
            "a new --output-root for a deliberate change"
        )
    return before
