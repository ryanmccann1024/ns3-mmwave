"""Finite, named selection rules over declared candidate evidence.

Each rule is a pure function of evidence the select task gathered from its
declared source tasks. Missing data raises (the selection is blocked); held-out
evidence is refused. The receipt records sources, sample counts, ranking, the
tie rule and the selected candidates and branches.
"""

import json
import statistics

import numpy as np

from scripts.rl.experiments.config import SELECTION_RULES

SELECTION_RECEIPT_VERSION = 1
_ALLOWED_ROLES = ("model_selection", "diagnostic")

TIE_RULES = {
    "legacy-validation-profile-v1": "highest mean best validation reward per decision; lower mean "
    "last-three-checkpoint std (population); then candidate name",
    "legacy-mission-profile-v1": "highest mean mission score; lower sample SD; then candidate name; "
    "retained candidates are kept independently of the winner",
    "legacy-online-profile-v1": "highest mean online mission score; lower sample SD; then candidate name",
    "replay": "recorded winners pinned explicitly; no ranking",
}


def _sources(evidence: dict, seed_role: str) -> list[dict]:
    if seed_role not in _ALLOWED_ROLES:
        raise ValueError(f"selection never consumes {seed_role!r} evidence")
    sources = []
    for candidate, items in evidence.items():
        if not items:
            raise ValueError(
                f"selection blocked: candidate {candidate} has no evidence"
            )
        for item in items:
            if item.get("seed_role") != seed_role:
                raise ValueError(
                    f"selection blocked: {item.get('path')} has seed role "
                    f"{item.get('seed_role')!r}, expected {seed_role!r}"
                )
            if not item.get("path") or not item.get("sha256"):
                raise ValueError(
                    f"selection blocked: candidate {candidate} evidence lacks a "
                    "source path and hash"
                )
            sources.append(
                {
                    "candidate": candidate,
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "case": item.get("case"),
                    "samples": _samples(item),
                }
            )
    return sources


def _samples(item: dict) -> int | None:
    """Sample count the evidence item declares, else its score count; never invented."""
    declared = item.get("samples")
    if declared is not None:
        if isinstance(declared, bool) or not isinstance(declared, int) or declared < 1:
            raise ValueError(
                f"selection blocked: {item.get('path')} declares invalid samples "
                f"{declared!r}"
            )
        return declared
    values = item.get("values")
    return len(values) if values else None


def _values(candidate: str, items: list[dict]) -> list[float]:
    values = []
    for item in items:
        sample = item.get("values")
        if not sample or any(v is None for v in sample):
            raise ValueError(
                f"selection blocked: candidate {candidate} is missing scores in "
                f"{item.get('path')}"
            )
        values.extend(float(v) for v in sample)
    if len(values) < 2:
        raise ValueError(
            f"selection blocked: candidate {candidate} needs at least two scores "
            "for a sample SD"
        )
    return values


def validation_profile(
    evidence: dict, *, normalization_decisions: int, seed_role: str = "model_selection"
) -> dict:
    """Rank by mean best validation reward per decision across the declared cases.

    Reproduces scripts/rl/adaptive_campaign.py::select_profile: per case the
    value is best_mean_reward / N and the spread is the population std of the
    last three checkpoint evaluation means / N (numpy std); candidates sort by
    (-mean value, mean spread, name). Evidence items carry `best_mean_reward`
    and `checkpoint_means` for one case.
    """
    sources = _sources(evidence, seed_role)
    rankings = []
    for candidate, items in evidence.items():
        values, spreads, cases = [], [], []
        for item in items:
            best, means = item.get("best_mean_reward"), item.get("checkpoint_means")
            if best is None or not means or len(means) < 3:
                raise ValueError(
                    f"selection blocked: candidate {candidate} lacks validation "
                    f"results in {item.get('path')}"
                )
            value = float(best) / normalization_decisions
            spread = (
                float(np.std(np.asarray(means, dtype=float)[-3:]))
                / normalization_decisions
            )
            values.append(value)
            spreads.append(spread)
            cases.append(
                {
                    "case": item.get("case"),
                    "best_validation_mean_reward": value,
                    "last_three_checkpoint_std": spread,
                }
            )
        rankings.append(
            {
                "candidate": candidate,
                "validation_mean_reward": statistics.mean(values),
                "checkpoint_std_mean": statistics.mean(spreads),
                "cases": cases,
            }
        )
    rankings.sort(
        key=lambda r: (
            -r["validation_mean_reward"],
            r["checkpoint_std_mean"],
            r["candidate"],
        )
    )
    return _receipt(
        "legacy-validation-profile-v1",
        seed_role,
        sources,
        rankings,
        [rankings[0]["candidate"]],
        {"normalization_decisions": normalization_decisions},
    )


def _score_ranking(evidence: dict) -> list[dict]:
    rankings = []
    for candidate, items in evidence.items():
        values = _values(candidate, items)
        rankings.append(
            {
                "candidate": candidate,
                "mean_mission_score": statistics.mean(values),
                "std": statistics.stdev(values),
                "samples": len(values),
            }
        )
    rankings.sort(key=lambda r: (-r["mean_mission_score"], r["std"], r["candidate"]))
    return rankings


def mission_profile(evidence: dict, *, retain: list[str], seed_role: str) -> dict:
    """Best non-retained candidate by mean mission score; retained ones are kept too.

    Reproduces scripts/rl/mission_campaign.py::select_profiles (with
    retain=["standard"]): statistics.mean / statistics.stdev over all
    episode mission scores, sorted by (-mean, sample SD, name).
    """
    sources = _sources(evidence, seed_role)
    unknown = [name for name in retain if name not in evidence]
    if unknown:
        raise ValueError(f"retained candidates {unknown} have no evidence")
    rankings = _score_ranking(evidence)
    winner = next(
        (r["candidate"] for r in rankings if r["candidate"] not in retain), None
    )
    if winner is None:
        raise ValueError(
            "selection blocked: every candidate is retained; nothing competes"
        )
    return _receipt(
        "legacy-mission-profile-v1",
        seed_role,
        sources,
        rankings,
        [winner, *retain],
        {"retain": list(retain)},
    )


def online_profile(evidence: dict, *, seed_role: str) -> dict:
    """Mean online mission score across the declared environments.

    Reproduces scripts/rl/mission_campaign.py::select_online: online-mode
    episode mission scores, sorted by (-mean, sample SD, name).
    """
    sources = _sources(evidence, seed_role)
    rankings = _score_ranking(evidence)
    return _receipt(
        "legacy-online-profile-v1",
        seed_role,
        sources,
        rankings,
        [rankings[0]["candidate"]],
        {},
    )


def replay(candidates: list[str], *, winners: list[str], provenance: str) -> dict:
    """A replay-equivalent conversion pins recorded winners; it is not a new selection."""
    unknown = [w for w in winners if w not in candidates]
    if unknown or not winners:
        raise ValueError(
            f"replay winners {unknown or winners} are not declared candidates"
        )
    receipt = _receipt(
        "replay", None, [], [], list(winners), {"provenance": provenance}
    )
    receipt["replay"] = True
    return receipt


def _receipt(rule, seed_role, sources, rankings, selected, settings) -> dict:
    return {
        "selection_receipt_version": SELECTION_RECEIPT_VERSION,
        "rule": rule,
        "tie_rule": TIE_RULES[rule],
        "seed_role": seed_role,
        "held_out_seeds_used": False,
        "settings": settings,
        "sources": sources,
        "sample_counts": {
            r["candidate"]: r.get("samples", len(r.get("cases", []))) for r in rankings
        },
        "ranking": rankings,
        "selected": selected,
        "replay": False,
    }


def _entry_order(entry) -> str:
    return json.dumps(entry, sort_keys=True)


def select(selection: dict, evidence: dict) -> dict:
    """Apply a plan's stage selection to gathered evidence and name the selected branches.

    `selection` is the plan's stage selection; `evidence` maps every declared
    candidate to its evidence items. The returned receipt adds
    `selected_branches` (rows to run) and `skipped_branches`.
    """
    rule = selection["rule"]
    if rule not in SELECTION_RULES:
        raise ValueError(f"unknown selection rule {rule!r}")
    candidates = list(selection["candidates"])
    if rule == "replay":
        receipt = replay(candidates, **selection["settings"])
    else:
        missing = [c for c in candidates if c not in evidence]
        extra = [c for c in evidence if c not in candidates]
        if missing or extra:
            raise ValueError(
                f"selection blocked: evidence candidates differ from the declared "
                f"ones (missing {missing}, undeclared {extra})"
            )
        ordered = {c: evidence[c] for c in candidates}
        if rule == "legacy-validation-profile-v1":
            receipt = validation_profile(
                ordered,
                normalization_decisions=selection["settings"][
                    "normalization_decisions"
                ],
                seed_role=selection["seed_role"],
            )
        elif rule == "legacy-mission-profile-v1":
            receipt = mission_profile(
                ordered,
                retain=selection["settings"]["retain"],
                seed_role=selection["seed_role"],
            )
        else:
            receipt = online_profile(ordered, seed_role=selection["seed_role"])
    # Branch entries are row names or {row, operation} entries (one form per selection).
    branches = selection.get("branches", {})
    receipt["selected_branches"] = sorted(
        (e for c in receipt["selected"] for e in branches.get(c, [])), key=_entry_order
    )
    receipt["skipped_branches"] = sorted(
        (
            e
            for c, entries in branches.items()
            if c not in receipt["selected"]
            for e in entries
        ),
        key=_entry_order,
    )
    return receipt
