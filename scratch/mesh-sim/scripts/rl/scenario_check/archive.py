"""Read and rebase INI files when archiving scenario inputs."""

import configparser
import json
from pathlib import Path
import shutil

from scripts.artifact_io import sha256_file, write_json
from scripts.sim_support import parse_ini


def read_ini(path):
    ini = configparser.ConfigParser(interpolation=None)
    with Path(path).open() as handle:
        ini.read_file(handle)
    return ini


def write_ini(path, ini):
    with Path(path).open("w") as handle:
        ini.write(handle)


def rebase_ini(source, target, archived_ini):
    """Load a copied INI and point its scenario files at the archived equivalents."""
    source, target = source.resolve(), target.resolve()
    source_ini = source / archived_ini.resolve().relative_to(target)
    ini = read_ini(archived_ini)
    scenario = parse_ini(source_ini).get("scenario", {})
    for key in ("nodes_file", "buildings_file", "jammers_file"):
        value = scenario.get(key)
        if value:
            original = (source_ini.parent / value).resolve()
            ini["scenario"][key] = str(target / original.relative_to(source))
    return ini


def input_hashes(directory, *, omit_name=None):
    return {
        str(path.relative_to(directory)): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != omit_name
    }


def snapshot(source, target):
    shutil.copytree(source, target)
    for archived_ini in target.rglob("*.ini"):
        write_ini(archived_ini, rebase_ini(source, target, archived_ini))
    hashes = input_hashes(target, omit_name="scenario-check.json")
    saved = json.loads((target / "scenario-check.json").read_text())
    saved["input_hashes"] = hashes
    saved["source_campaign_sha256"] = sha256_file(source / "scenario-check.json")
    write_json(target / "scenario-check.json", saved)
    return {
        **hashes,
        "scenario-check.json": sha256_file(target / "scenario-check.json"),
    }
