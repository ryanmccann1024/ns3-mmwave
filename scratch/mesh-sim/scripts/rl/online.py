"""Continue PPO learning during moving-jammer operation with a matched sampled control."""

import argparse
import sys

# Compatibility re-exports of the names this module historically defined or imported;
# legacy callers and tests use or patch them. Removed at C5 with the legacy tree.
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.logger import configure

from scripts.rl.cli_common import now_iso, write_json
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.policy import operation as _operation
from scripts.rl.policy.bundle import eval_selection, parameter_digest, read_bundle, selection_from_manifest
from scripts.rl.policy.compat import check_compatibility
from scripts.rl.policy.episode_review import endpoint_metrics
from scripts.rl.policy.evaluate import ModelPolicy, episode_metrics, run_episode
from scripts.rl.policy.operation import DEFAULT_MODES, UpdateRecorder, operation_modes
from scripts.rl.policy.reward_matrix import write_reward_matrix
from scripts.sim_support import parse_seed_spec

REEXPORTED = ("ActionMasker", "DEFAULT_MODES", "MaskablePPO", "MeshRlEnv", "ModelPolicy", "UpdateRecorder",
              "check_compatibility", "configure", "endpoint_metrics", "episode_metrics", "eval_selection",
              "now_iso", "operation_modes", "parameter_digest", "parse_seed_spec", "read_bundle",
              "read_scenario_identity", "run_episode", "selection_from_manifest", "write_json",
              "write_reward_matrix")
_PASSED_THROUGH = ("ActionMasker", "MaskablePPO", "MeshRlEnv", "ModelPolicy", "UpdateRecorder",
                   "check_compatibility", "configure", "endpoint_metrics", "episode_metrics", "eval_selection",
                   "now_iso", "parameter_digest", "read_bundle", "read_scenario_identity", "run_episode",
                   "selection_from_manifest", "write_json", "write_reward_matrix")


def run_online(*args, **kwargs):
    """``policy.operation.run_online`` using this module's current names, as before the move."""
    module = sys.modules[__name__]
    collaborators = _operation.sb3_collaborators(**{name: getattr(module, name) for name in _PASSED_THROUGH})
    return _operation.run_online(*args, collaborators=collaborators, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--sim-binary", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seeds", default="401-405")
    parser.add_argument("--n-steps", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=60)
    parser.add_argument("--learning-rate", type=float)
    parser.add_argument("--ent-coef", type=float, default=.001)
    parser.add_argument("--target-kl", type=float, default=.02)
    parser.add_argument("--modes", nargs="+", choices=DEFAULT_MODES, default=list(DEFAULT_MODES),
                        help="Operation modes; fixed_sampled alone never performs optimizer updates")
    parser.add_argument("--model", default="best", help="Verified best, final or checkpoints/<name>.zip selection")
    args = parser.parse_args()
    run_online(args.run_dir, args.sim_binary, args.output_dir, parse_seed_spec(args.seeds),
               args.n_steps, args.batch_size, args.learning_rate, args.ent_coef, args.target_kl, args.model, args.modes)


if __name__ == "__main__":
    main()
