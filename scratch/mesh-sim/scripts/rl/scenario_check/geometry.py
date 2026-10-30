"""Scenario-check routing interface over the env geometry and scripted-policy owners.

`inputs`, `placement` and `correction` share these route helpers. The scripted
reference implementation belongs to `policy.scripted`.
"""

from scripts.rl.env.geometry import route, safe_segment, segment_hits, swept_distance  # noqa: F401
from scripts.rl.policy.scripted import ReferencePolicy  # noqa: F401
