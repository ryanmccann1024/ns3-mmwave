"""Launch experiment steps and always stop and reap their process groups."""

import os
import signal
import subprocess
import sys
from contextlib import contextmanager

from scripts.sim_support import find_mesh_root

STOP_WAIT_S = 5.0
_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class ProcessInterrupted(KeyboardInterrupt):
    """A termination signal interrupted a managed experiment step."""

    def __init__(self, signum):
        self.signum = signum
        super().__init__(signal.Signals(signum).name)


def _interrupt(signum, frame):
    for selected in _SIGNALS:
        signal.signal(selected, signal.SIG_IGN)
    raise ProcessInterrupted(signum)


def launch_step(step):
    return subprocess.Popen([sys.executable, "-m", step["module"], *step["args"]],
                            cwd=str(find_mesh_root()), start_new_session=True)


def stop_group(process):
    """Stop descendants even when the group leader already exited, and reap it."""
    def send(signum):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            if process.poll() is None:
                process.send_signal(signum)
    send(signal.SIGTERM)
    try:
        process.wait(timeout=STOP_WAIT_S)
    except subprocess.TimeoutExpired:
        pass
    finally:
        send(signal.SIGKILL)
        process.wait()


@contextmanager
def managed_step(step, launch=None, on_start=None):
    previous = {sig: signal.signal(sig, _interrupt) for sig in _SIGNALS}
    process = None
    try:
        process = (launch or launch_step)(step)
        if on_start is not None:
            on_start(process)
        yield process
    finally:
        for sig in _SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if isinstance(process, subprocess.Popen):
                stop_group(process)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def execute_step(step, on_start=None):
    with managed_step(step, on_start=on_start) as process:
        return process.wait()
