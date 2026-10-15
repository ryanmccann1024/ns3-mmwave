"""Benchmark: process-tree sampling edges, run refusals and tolerance, estimate math.

Expectations come from scripts/rl/ops/README.md "Benchmark". No real process
is benchmarked here: launches and ps snapshots are injected.
"""


from scripts.rl.ops import measurement as benchmark
from scripts.sim_support import find_mesh_root


TRACKED_MATRIX = find_mesh_root() / "inputs/experiments/bypass-smoke-matrix.json"


# --- process tree ------------------------------------------------------------


def test_descendants_still_count_after_the_root_exited():
    table = benchmark.parse_ps("11 10 200\n12 11 300\n")
    assert benchmark.tree_usage(table, 10) == {"rss_kb": 500, "count": 2,
                                               "max_rss_kb": 300}


def _reader(*outcomes):
    queue = list(outcomes)

    def read():
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item
    return read


def test_the_first_sample_is_taken_immediately_after_spawn():
    sampler = benchmark.TreeSampler(10, 3600.0, _reader("10 1 42\n"))
    sampler.start()
    sampler.stop()
    assert sampler.result()["samples"] == 1
    assert sampler.result()["peak_tree_rss_kb"] == 42


# --- run ---------------------------------------------------------------------


# --- estimate ----------------------------------------------------------------
