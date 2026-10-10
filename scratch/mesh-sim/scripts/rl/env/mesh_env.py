"""Gymnasium adapter for the mesh simulator's RL protocol."""

from pathlib import Path

import gymnasium
import numpy as np
from gymnasium import spaces

from .config import read_scenario_seed
from .episode import EpisodeSession
from .protocol import CentralizedProtocol, ProtocolError, SLOT_ACTIONS, validate_message


class MeshRlEnv(gymnasium.Env):
    """Run one simulator process per episode with a fixed training seed."""

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 4}

    def __init__(self, sim_binary: str, run_config: str, seed: int | None = None,
                 output_dir: str = "", band: str | None = None,
                 render_mode: str | None = None):
        super().__init__()
        if not output_dir:
            raise ValueError("MeshRlEnv requires output_dir (the training output root)")

        self._run_config = run_config
        self._output_dir = Path(output_dir)
        self._session = EpisodeSession(sim_binary, run_config, self._output_dir, band)
        if seed is not None:
            self.seed_value = int(seed)
            self.seed_source = "cli"
        else:
            ini_seed = read_scenario_seed(run_config)
            if ini_seed is None:
                raise ValueError(
                    "No seed available: pass seed=<int> to MeshRlEnv or set "
                    f"[scenario] seed in {run_config}"
                )
            self.seed_value = ini_seed
            self.seed_source = "run.ini"

        self.action_space: spaces.Space | None = None
        self.observation_space: spaces.Space | None = None
        self._signature: dict | None = None
        self._control_mode: str | None = None
        self._contract: dict | None = None
        self._protocol: CentralizedProtocol | None = None


        self.window_size = 512
        self.render_mode = render_mode

    @property
    def control_mode(self) -> str | None:
        return self._control_mode

    @property
    def contract(self) -> dict | None:
        return dict(self._contract) if self._contract is not None else None

    @property
    def _proc(self):
        return self._session.proc

    @property
    def _cmd(self):
        return self._session.command

    def reset(self, *, seed=None, options=None):
        if seed is not None and int(seed) != self.seed_value:
            self.seed_value = int(seed)
            self.seed_source = "gym"

        self._session.stop("interrupted", "reset")
        self._session.start(self.seed_value, self.seed_source)
        first = self._session.read_message()
        try:
            validate_message(first)
        except ProtocolError as exc:
            self._session.protocol_error(str(exc))
        if first.get("type") != "init":
            self._session.protocol_error("Expected an 'init' message; legacy control is unsupported")
        return self._reset_centralized(first)

    def step(self, action):
        if self._protocol is None:
            raise RuntimeError("reset() must succeed before step()")
        action_value = self._protocol.joint_action(action)
        self._session.send_action(action_value)
        msg = self._session.read_message()
        obs = self._validated_step(self._protocol, msg)
        info = self._centralized_info(msg)
        reward = float(msg["reward"])
        terminated = bool(msg["done"])
        self._session.record_step(msg, reward)
        if terminated:
            self._session.stop("completed", "done")
        return obs, reward, terminated, False, info

    def render(self):
        pass

    def _render_frame(self):
        pass

    def action_masks(self) -> np.ndarray:
        if self._protocol is None or self._protocol.mask is None:
            raise RuntimeError("reset() must succeed before action_masks()")
        return self._protocol.mask.astype(bool)

    def valid_action_mask(self) -> np.ndarray:
        return self.action_masks()

    def close(self):
        self._session.stop("interrupted", "close")

    def _reset_centralized(self, init: dict):
        try:
            protocol = CentralizedProtocol(init)
        except ProtocolError as exc:
            self._session.protocol_error(str(exc))
        slots = int(init["max_controlled_nodes"])
        signature = {
            "control_mode": "centralized",
            "contract": init["contract"],
            "dimensions": init["dimensions"],
            "action_meanings": tuple(init["action_meanings"]),
            "num_mesh_nodes": init["num_mesh_nodes"],
            "max_controlled_nodes": slots,
            "obs_dim": init["obs_dim"],
            "mask_dim": init["mask_dim"],
            "nvec": (SLOT_ACTIONS,) * slots,
            "slot_node_ids": tuple(init["slot_node_ids"]),
            "slot_speed_mps": tuple(init["slot_speed_mps"]),
            "tick_s": init["tick_s"],
            "decision_interval_s": init["decision_interval_s"],
            "decision_interval_ticks": init["decision_interval_ticks"],
            "num_ticks": init["num_ticks"],
            "num_decisions": init["num_decisions"],
            "reward_type": init["reward_type"],
            "reward_window": init["reward_window"],
            "warmup_s": init["warmup_s"],
            "reward_warmup": init["reward_warmup"],
            "wall_policy": init["wall_policy"],
        }
        self._check_signature(signature)
        self._control_mode = "centralized"
        self._contract = dict(init)
        self._protocol = protocol
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(init["obs_dim"],), dtype=np.float64
        )
        self.action_space = spaces.MultiDiscrete([SLOT_ACTIONS] * slots)
        self._session.set_contract(init)

        msg = self._session.read_message()
        obs = self._validated_step(protocol, msg, first=True)
        return obs, self._centralized_info(msg)

    def _validated_step(self, protocol, msg: dict, first: bool = False):
        try:
            return protocol.validate_step(msg, first=first)
        except ProtocolError as exc:
            self._session.protocol_error(str(exc))

    @staticmethod
    def _centralized_info(msg: dict) -> dict:
        return {
            "tick": msg["tick"],
            "time_s": msg["time_s"],
            "decision": msg["decision"],
            "ticks_in_step": msg["ticks_in_step"],
            "scored_ticks": msg["scored_ticks"],
            "revalidated_slots": list(msg["revalidated_slots"]),
        }

    def _check_signature(self, signature: dict) -> None:
        if self._signature is None:
            self._signature = signature
            return
        if signature == self._signature:
            return
        keys = sorted(set(self._signature) | set(signature))
        diffs = "; ".join(
            f"{key}: first={self._signature.get(key)!r} now={signature.get(key)!r}"
            for key in keys if self._signature.get(key) != signature.get(key)
        )
        self._session.protocol_error(
            f"Simulator contract changed between resets ({diffs})"
        )
