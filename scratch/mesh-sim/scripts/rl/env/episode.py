"""Per-episode simulator process lifecycle and diagnostics."""

import json
import subprocess
import threading
import time
from pathlib import Path

from scripts.sim_support import find_mesh_root, simulator_env, tail_lines

from .episode_artifacts import EpisodeArtifacts

_STDERR_TAIL_LINES = 40
_BAD_LINE_CHARS = 200
_MAX_ERROR_CHARS = 1000
_CLEANUP_BUDGET_S = 10.0
_NATURAL_EXIT_S = 5.0
_ESCALATION_WAIT_S = 2.0
_DRAIN_CHUNK = 64 * 1024


class EpisodeSession:
    def __init__(self, sim_binary: str, run_config: str, output_dir: Path,
                 band: str | None):
        self._sim_binary = sim_binary
        self._run_config = run_config
        self._artifacts = EpisodeArtifacts(output_dir)
        self._band = band
        self._proc: subprocess.Popen | None = None
        self._stderr_file = None
        self._stderr_path: Path | None = None
        self._episode_dir: Path | None = None
        self._episode_index: int | None = None
        self._cmd: list[str] = []
        self._msg_count = 0
        self._last_tail = "(no stderr captured)"

    @property
    def proc(self) -> subprocess.Popen | None:
        return self._proc

    @property
    def command(self) -> list[str]:
        return self._cmd

    @property
    def manifest(self) -> dict | None:
        return self._artifacts.manifest

    def start(self, seed: int, seed_source: str) -> None:
        self._episode_dir, self._episode_index = self._artifacts.allocate()
        self._cmd = [
            self._sim_binary,
            f"--run-config={self._run_config}",
            "--rl-mode",
            f"--seed={seed}",
            f"--output-dir={self._episode_dir}",
        ]
        if self._band is not None:
            self._cmd.append(f"--band={self._band}")
        self._artifacts.begin(self._episode_index, seed, seed_source, self._cmd)
        self._stderr_path = self._episode_dir / "sim_stderr.log"
        self._stderr_file = open(self._stderr_path, "w")
        self._msg_count = 0
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
                text=True,
                bufsize=1,
                env=self._child_env(),
            )
        except OSError as exc:
            self._artifacts.finish("failed", None)
            self._close_stderr()
            raise RuntimeError(f"Failed to launch simulator {self._cmd}: {exc}") from exc

    def set_contract(self, init: dict) -> None:
        self._artifacts.set_contract(init)

    def set_selection(self, selection, observation_schema: dict, reward_schema: dict) -> None:
        self._artifacts.set_selection(selection, observation_schema, reward_schema)

    def record_reset(self, msg: dict, obs) -> None:
        self._artifacts.record_reset(msg, obs)

    def record_step(self, msg: dict, reward: float, detail: dict | None = None) -> None:
        self._artifacts.record_step(msg, reward, detail)

    def protocol_error(self, detail: str):
        message = f"{detail} on message line {self._msg_count}"
        if self._artifacts.manifest is not None:
            self._artifacts.manifest["error"] = message[:_MAX_ERROR_CHARS]
        rc = self.stop("failed", "error")
        raise RuntimeError(
            f"{message}\n"
            f"command: {self._cmd}\n"
            f"exit code: {rc}\n"
            f"last {_STDERR_TAIL_LINES} stderr lines:\n{self._last_tail}"
        )

    def send_action(self, action) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._artifacts.action = action
        message = json.dumps({"action": action})
        try:
            self._proc.stdin.write(message + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def _child_env(self) -> dict:
        return simulator_env(find_mesh_root(__file__))

    def _stderr_tail(self) -> str:
        self._close_stderr()
        if self._stderr_path is None or not self._stderr_path.is_file():
            return "(no stderr captured)"
        return tail_lines(self._stderr_path, _STDERR_TAIL_LINES) or "(stderr empty)"

    def read_message(self) -> dict:
        assert self._proc is not None and self._proc.stdout is not None
        line = self._proc.stdout.readline()
        self._msg_count += 1
        if not line:
            if self._artifacts.manifest is not None:
                self._artifacts.manifest["error"] = "sim process ended unexpectedly"
            rc = self.stop("failed", "error")
            raise RuntimeError(
                f"Sim process ended unexpectedly (exit code {rc})\n"
                f"command: {self._cmd}\n"
                f"last {_STDERR_TAIL_LINES} stderr lines:\n{self._last_tail}"
            )
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            bad = line.rstrip("\n")[:_BAD_LINE_CHARS]
            message = f"Invalid JSON from sim on message line {self._msg_count}: {exc}"
            if self._artifacts.manifest is not None:
                self._artifacts.manifest["error"] = message[:_MAX_ERROR_CHARS]
            rc = self.stop("failed", "error")
            raise RuntimeError(
                f"{message}\n"
                f"offending line: {bad!r}\n"
                f"command: {self._cmd}\n"
                f"exit code: {rc}\n"
                f"last {_STDERR_TAIL_LINES} stderr lines:\n{self._last_tail}"
            ) from exc

    def _close_stderr(self) -> None:
        if self._stderr_file is not None:
            try:
                self._stderr_file.flush()
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None

    @staticmethod
    def _start_drain(proc: subprocess.Popen) -> threading.Thread:
        stream = proc.stdout

        def drain() -> None:
            if stream is None:
                return
            try:
                while stream.read(_DRAIN_CHUNK):
                    pass
            except (ValueError, OSError):
                pass

        thread = threading.Thread(target=drain, name="mesh-sim-drain", daemon=True)
        thread.start()
        return thread

    @staticmethod
    def _close_stream(stream) -> None:
        if stream is None or stream.closed:
            return
        try:
            stream.close()
        except Exception:
            pass

    def stop(self, status: str, stop_reason: str | None = None) -> int | None:
        proc, self._proc = self._proc, None
        artifact_error = None
        try:
            self._artifacts.close_recorder()
        except Exception as exc:
            artifact_error = exc
            status, stop_reason = "failed", "error"
            if self.manifest is not None:
                self.manifest["error"] = f"Telemetry close failed: {exc}"[:_MAX_ERROR_CHARS]
        if proc is None:
            if status == "failed":
                self._last_tail = self._stderr_tail()
            self._close_stderr()
            if self._artifacts.manifest is not None:
                self._artifacts.finish(status, None, stop_reason, None)
            if artifact_error is not None:
                raise artifact_error
            return None

        deadline = time.monotonic() + _CLEANUP_BUDGET_S
        reader = self._start_drain(proc)
        self._close_stream(proc.stdin)

        escalation = "exited"
        rc = self._reap(proc, min(_NATURAL_EXIT_S, self._remaining(deadline)))
        if rc is None:
            proc.terminate()
            escalation = "terminated"
            rc = self._reap(proc, min(_ESCALATION_WAIT_S, self._remaining(deadline)))
        if rc is None:
            proc.kill()
            escalation = "killed"
            rc = self._reap(proc, min(_ESCALATION_WAIT_S, self._remaining(deadline)))

        reader.join(timeout=self._remaining(deadline))
        self._close_stream(proc.stdout)
        if status == "failed" or stop_reason == "done":
            self._last_tail = self._stderr_tail()
        self._close_stderr()

        if stop_reason == "done":
            status = "completed" if rc == 0 else "failed"
        self._artifacts.finish(status, rc, stop_reason, escalation)
        if artifact_error is not None:
            raise artifact_error
        return rc

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    @staticmethod
    def _reap(proc: subprocess.Popen, timeout: float) -> int | None:
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
