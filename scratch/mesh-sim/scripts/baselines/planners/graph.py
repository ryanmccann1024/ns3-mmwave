"""Rootless mesh connectivity and single-node-loss graph facts."""

import numpy as np


def components(connected: np.ndarray) -> list[frozenset[int]]:
    """Connected components ordered by their smallest index; the diagonal is ignored."""
    adjacency = np.asarray(connected, dtype=bool)
    n = len(adjacency)
    label = np.full(n, -1)
    result = []
    for root in range(n):
        if label[root] >= 0:
            continue
        label[root] = len(result)
        stack, members = [root], [root]
        while stack:
            node = stack.pop()
            for other in np.nonzero(adjacency[node])[0]:
                if label[other] < 0:
                    label[other] = len(result)
                    stack.append(int(other))
                    members.append(int(other))
        result.append(frozenset(members))
    return result


def core(parts: list[frozenset[int]]) -> frozenset[int]:
    """Largest component; ties go to the one holding the smallest roster index."""
    if not parts:
        raise ValueError("no components: the roster is empty")
    return min(parts, key=lambda part: (-len(part), min(part)))


def vulnerability_pairs(connected: np.ndarray, core_members, victims) -> int:
    """Sum over victims of core pairs (victim excluded) split once the victim is removed."""
    adjacency = np.asarray(connected, dtype=bool)
    members = frozenset(core_members)
    total = 0
    for victim in victims:
        survivors = sorted(members - {victim})
        if len(survivors) < 2:
            continue
        reduced = adjacency.copy()
        reduced[victim, :] = False
        reduced[:, victim] = False
        label = {}
        for index, part in enumerate(components(reduced)):
            for node in part:
                label[node] = index
        sizes: dict[int, int] = {}
        for node in survivors:
            sizes[label[node]] = sizes.get(label[node], 0) + 1
        m = len(survivors)
        total += m * (m - 1) // 2 - sum(k * (k - 1) // 2 for k in sizes.values())
    return total
