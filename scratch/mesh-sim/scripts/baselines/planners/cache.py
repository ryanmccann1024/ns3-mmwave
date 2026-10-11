"""Bounded full-layout result reuse and incremental candidate evaluation."""

from collections import OrderedDict
from itertools import islice
import sys

import numpy as np


class LayoutCache:
    def __init__(self, scorer, max_bytes=32 * 1024 * 1024):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
            raise ValueError("cache max_bytes must be an integer >= 0")
        self._scorer = scorer
        self.max_bytes = max_bytes
        self.bytes_used = 0
        self._results = OrderedDict()

    @staticmethod
    def _size(key, result):
        arrays = (
            getattr(result, name, None)
            for name in ("connected", "sinr_db", "capacity_mbps", "is_los")
        )
        size = (
            sys.getsizeof(key)
            + sys.getsizeof(result)
            + sys.getsizeof(getattr(result, "__dict__", {}))
            + 256
        )
        size += sum(sys.getsizeof(array) for array in arrays if array is not None)
        coverage = getattr(result, "coverage", None)
        if coverage is not None:
            size += sys.getsizeof(coverage)
            size += sum(sys.getsizeof(row) + sum(sys.getsizeof(k) for k in row) for row in coverage)
        size += sys.getsizeof(getattr(result, "diagnostics", ()))
        size += sum(sys.getsizeof(x) for x in getattr(result, "diagnostics", ()))
        return size

    def _remember(self, key, result):
        size = self._size(key, result)
        if size > self.max_bytes:
            return
        while self._results and self.bytes_used + size > self.max_bytes:
            _, (_, old_size) = self._results.popitem(last=False)
            self.bytes_used -= old_size
        self._results[key] = (result, size)
        self.bytes_used += size

    def iter_evaluate(self, layouts):
        source = iter(layouts)
        batch_size = min(getattr(self._scorer, "max_layouts", 32), 32)
        while batch := list(islice(source, batch_size)):
            arrays = [np.ascontiguousarray(layout, dtype=float) for layout in batch]
            keys = [array.tobytes() for array in arrays]
            fresh = {key: self._results[key][0] for key in keys if key in self._results}
            missing = {key: array for key, array in zip(keys, arrays) if key not in self._results}
            if missing:
                fresh.update(zip(missing, self._scorer.evaluate(missing.values())))
            for key in keys:
                if key in self._results:
                    result, _ = self._results[key]
                    self._results.move_to_end(key)
                else:
                    result = fresh[key]
                    self._remember(key, result)
                yield result

    def evaluate(self, layouts):
        return list(self.iter_evaluate(layouts))
