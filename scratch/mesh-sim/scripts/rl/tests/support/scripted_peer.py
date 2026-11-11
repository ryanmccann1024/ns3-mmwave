#!/usr/bin/env python3
"""Scripted stand-in simulator: replays JSON ops so tests can emit exact messages.

Ops (a JSON list in $SCRIPTED_PEER_SCRIPT), run in order:
  {"emit": <obj>}        write json.dumps(obj) + newline (NaN allowed)
  {"raw": "<text>"}      write text + newline verbatim
  {"read": true}         read one stdin line, log it; on EOF exit 0
  {"stderr": "<text>"}   write a line to stderr
  {"exit": <code>}       exit immediately with that code
  {"ignore_term": true}  ignore SIGTERM from now on
  {"hang": <seconds>}    sleep, ignoring stdin, then continue
Argv is appended to $SCRIPTED_PEER_ARGV; actions to $SCRIPTED_PEER_LOG.
"""

import json
import os
import signal
import sys
import time


def _append(path_var: str, payload) -> None:
    path = os.environ.get(path_var)
    if path:
        with open(path, "a") as fh:
            fh.write(json.dumps(payload) + "\n")


def main() -> int:
    _append("SCRIPTED_PEER_ARGV", sys.argv[1:])
    with open(os.environ["SCRIPTED_PEER_SCRIPT"]) as fh:
        ops = json.load(fh)
    for op in ops:
        if "emit" in op:
            sys.stdout.write(json.dumps(op["emit"]) + "\n")
            sys.stdout.flush()
        elif "raw" in op:
            sys.stdout.write(op["raw"] + "\n")
            sys.stdout.flush()
        elif "read" in op:
            line = sys.stdin.readline()
            if not line:
                _append("SCRIPTED_PEER_LOG", "EOF")
                return 0
            _append("SCRIPTED_PEER_LOG", json.loads(line))
        elif "stderr" in op:
            print(op["stderr"], file=sys.stderr, flush=True)
        elif "exit" in op:
            return int(op["exit"])
        elif "ignore_term" in op:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        elif "hang" in op:
            time.sleep(float(op["hang"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
