"""Check simulator features and stationary scenario difficulty before a campaign."""

import json

from scripts.rl import evaluate
from scripts.rl.scenario_check.preflight import check_difficulty as check_difficulty
from scripts.rl.scenario_check.preflight import criteria as criteria
from scripts.rl.scenario_check.preflight import main as _main
from scripts.rl.scenario_check.preflight import signature as signature


def _evaluate_hold(name, ini, binary, target, _selection, seeds):
    # Retain the campaign entry point's evaluation CLI and its exit-code checks.
    code = evaluate.main(
        [
            "--sim-binary",
            str(binary),
            "--run-config",
            str(ini),
            "--output-dir",
            str(target),
            "--seeds",
            ",".join(map(str, seeds)),
            "--policies",
            "hold",
        ]
    )
    if code:
        raise RuntimeError(f"{name}: hold preflight failed ({code})")
    manifest = json.loads((target / "eval_manifest.json").read_text())
    return manifest["policies"]["hold"]["episodes"]


def main(argv=None):
    return _main(argv, evaluate_hold=_evaluate_hold)


if __name__ == "__main__":
    raise SystemExit(main())
