#!/usr/bin/env python3
"""CLI for selective, add-missing retrieval of experiment results."""

import argparse
import sys

from scripts.rl.ops.retrieval import CATEGORY_INCLUDES, fetch


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Copy selected experiment results from a run to this machine")
    p.add_argument("--remote", required=True,
                   help="rsync source: [user@host:]/abs/output-root")
    p.add_argument("--dest", required=True,
                   help="Local destination directory; nothing existing is overwritten")
    p.add_argument("--select", default=None,
                   help="Comma list of categories: "
                        f"{', '.join(sorted(CATEGORY_INCLUDES))}")
    p.add_argument("--update", action="store_true",
                   help="Add missing files only; existing files stay stale. Use a new --dest to refresh")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the rsync argv and exit without transferring")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    return fetch(args.remote, args.dest, args.select, args.update, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
