"""Managed fake processes exercise cleanup without a simulator or ps query."""

import os
import signal
import subprocess
import sys
import time

import pytest

from scripts.rl.ops.process import ProcessInterrupted, managed_step


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_stops_parent_and_descendant_and_restores_handlers(tmp_path, signum):
    ready = tmp_path / "ready"
    parent = None
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    program = '''import pathlib, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def stop(sig, frame):
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
while True:
    time.sleep(0.1)
'''

    def launch(step):
        nonlocal parent
        parent = subprocess.Popen([sys.executable, "-c", program, str(ready)],
                                  start_new_session=True)
        deadline = time.monotonic() + 5
        while not ready.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("fake process did not start")
            time.sleep(0.01)
        return parent

    try:
        with pytest.raises(ProcessInterrupted) as interrupted:
            with managed_step({}, launch=launch):
                os.kill(os.getpid(), signum)
        assert interrupted.value.signum == signum
        assert parent.returncode is not None
        child_pid = int(ready.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        with pytest.raises(ProcessLookupError):
            os.killpg(parent.pid, 0)
        assert {sig: signal.getsignal(sig) for sig in previous} == previous
    finally:
        if parent is not None and parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait()
